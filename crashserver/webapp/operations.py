"""
symbol.py: Operations which coordinate transactions between
the filesystem and the database on each api request
"""
import dataclasses

import flask
import magic

from crashserver.webapp.models import Symbol, BuildMetadata, Minidump, Annotation
from crashserver import tasks


# %% Models
@dataclasses.dataclass
class SymbolData:
    """
    These attributes uniquely identify any symbol file. It is used over the Symbol db model as the db model is
    organized different to keep data duplication to a minimum
    """

    os: str = ""
    arch: str = ""
    build_id: str = ""
    module_id: str = ""
    app_version: str = None

    @staticmethod
    def from_module_line(module_line: str):
        metadata = module_line.strip().split(" ")
        return SymbolData(
            os=metadata[1],
            arch=metadata[2],
            build_id=metadata[3],
            module_id=metadata[4],
        )


def symbol_upload(session, project_id: str, symbol_file: bytes, symbol_data: SymbolData):
    """
    Store the symbol in the correct location, and track it in the database.

    While usually the data in `symbol_data` will be taken from `symbol_file` depending
    on the caller of this function (whether it be the sym-upload protocol, or the CrashServer
    web upload interface, the data might be from a different source.

    TODO(james): Is it worth separating this function out like this? The SymbolData struct
        will almost always be from the first line of the symbol file.

    :param session: The database session object
    :param project_id: The project_id to relate the symbol to
    :param symbol_file: The bytes to store in the file
    :param symbol_data: Metadata about the symfile param
    :return: The response to the client making this request
    """
    # Check if a minidump was already uploaded with the current module_id and build_id
    build = (
        session.query(BuildMetadata)
        .filter_by(
            project_id=project_id,
            build_id=symbol_data.build_id,
            module_id=symbol_data.module_id,
        )
        .first()
    )
    if build is None:
        # If we can't find the metadata for the symbol (which will usually be the case unless a minidump was uploaded
        # before the symbol file was uploaded), then create a new BuildMetadata, flush, and relate to symbol
        build = BuildMetadata(
            project_id=project_id,
            module_id=symbol_data.module_id,
            build_id=symbol_data.build_id,
        )
        session.add(build)

    if build.symbol:
        return {"error": "Symbol file already uploaded"}, 203

    build.symbol = Symbol(
        project_id=project_id,
        os=symbol_data.os,
        arch=symbol_data.arch,
        app_version=symbol_data.app_version,
    )
    build.symbol.store_file(symbol_file)
    session.commit()

    # Send all minidump id's to task processor to for decoding
    for dump in build.unprocessed_dumps:
        tasks.decode_minidump(dump.id)

    res = {
        "id": build.symbol.id,
        "os": build.symbol.os,
        "arch": build.symbol.arch,
        "build_id": build.build_id,
        "module_id": build.module_id,
        "date_created": build.symbol.date_created.isoformat(),
    }

    return res, 200


def minidump_upload(session, project_id: str, annotations: dict, minidump_file: bytearray):

    # Verify file is actually a minidump based on magic number
    # Validate magic number
    magic_number = magic.from_buffer(minidump_file, mime=True)
    if magic_number != "application/x-dmp":
        return flask.make_response({"error": "Bad Minidump"}, 400)

    # Add minidump to database
    new_dump = Minidump(project_id=project_id)
    new_dump.store_minidump(minidump_file)
    session.add(new_dump)
    session.flush()

    # Add annotations to database, after removing guid and api_key
    if annotations:
        annotations.pop("guid", None)
        annotations.pop("api_key", None)
        for key, value in annotations.items():
            new_dump.annotations.append(Annotation(key=key, value=value))

    session.commit()
    tasks.decode_minidump(new_dump.id)

    return flask.make_response({"status": "success", "id": str(new_dump.id)}, 200)
