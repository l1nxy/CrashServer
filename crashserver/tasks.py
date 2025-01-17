from pathlib import Path
import subprocess
import json

from loguru import logger
import requests

from crashserver.webapp.models import Minidump, BuildMetadata, SymCache
from crashserver.webapp.extensions import db
from crashserver.webapp import create_app
from crashserver.utility import processor
from crashserver import config


def download_windows_symbol(module_id: str, build_id: str):
    cached_sym = db.session.query(SymCache).filter_by(module_id=module_id, build_id=build_id).first()

    if cached_sym:
        logger.debug("SymCache Hit for {}:{}".format(module_id, build_id))
        return

    cached_sym = SymCache(module_id=module_id, build_id=build_id)
    logger.info("SymCache Miss. Attempting to download {}:{}".format(module_id, build_id))

    url = "https://msdl.microsoft.com/download/symbols/" + cached_sym.url_path
    res = requests.get(url)
    if res.status_code != 200:
        logger.warning("Symbol not available on Windows Symbol Server => {}:{}".format(module_id, build_id))
        return

    cached_sym.store_and_convert_symbol(res.content)
    db.session.add(cached_sym)
    db.session.commit()


def decode_minidump(crash_id):
    app = create_app()
    with app.app_context():
        stackwalker = str(Path("res/bin/linux/stackwalker").absolute())

        # Symbolicate without symbols to get metadata
        # TODO: Proper error handling for if executable fails
        minidump = db.session.query(Minidump).get(crash_id)
        if not minidump:
            logger.error(f"Unable to decode minidump: {minidump}")
            return

        dumpfile = str(Path(minidump.project.minidump_location) / minidump.filename)
        machine = subprocess.run([stackwalker, dumpfile], capture_output=True)
        json_stack = json.loads(machine.stdout.decode("utf-8"))
        crash_data = processor.ProcessedCrash.generate(json_stack)

        # Check if symbols exist for the main program
        minidump.build = (
            db.session.query(BuildMetadata).filter(BuildMetadata.build_id == crash_data.main_module.debug_id).first()
        )

        # The symbol file needed to decode this minidump does not exist.
        # Make a record in the CompileMetadata table with {build,module}_id. There will be a
        # relationship from that metadata to the minidump
        if minidump.build is None:
            minidump.build = BuildMetadata(
                project_id=minidump.project_id,
                module_id=crash_data.main_module.debug_file,
                build_id=crash_data.main_module.debug_id,
            )
            db.session.flush()

        # No symbols? Notify and return
        if not minidump.build.symbol:
            logger.info(
                "Symbol {} does not exist. Storing partial stacktrace for Minidump ID {}",
                crash_data.main_module.debug_id,
                crash_id,
            )
            minidump.stacktrace = json_stack
            minidump.symbolicated = False
            minidump.decode_task_complete = True
            db.session.commit()
            return

        # If we get here, then the symbol exists, and we should ensure we have all possible windows symbols before decoding
        # TODO(james): This is good as a prototype, but should be in a separate HTTP symbol supplier module/class
        if minidump.build.symbol.os == "windows":
            logger.info("Attempting to download windows symbols for minidump {}", minidump.id)
            for module in crash_data.modules_no_symbols:
                download_windows_symbol(module.debug_file, module.debug_id)
            logger.info("Symbol Download Complete for {}", minidump.id)

        def process(binary):
            return subprocess.run(
                [binary, dumpfile, minidump.project.symbol_location, config.get_appdata_directory("symcache")],
                capture_output=True,
            )

        json_stackwalk = process(stackwalker)
        minidump.stacktrace = json.loads(json_stackwalk.stdout.decode("utf-8"))
        minidump.symbolicated = True
        minidump.decode_task_complete = True
        db.session.commit()
        logger.info("Minidump {} decoded", minidump.id)
