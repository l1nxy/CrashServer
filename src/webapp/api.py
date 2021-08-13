from . import db
from .models import Minidump, Annotation, Project, Symbol
from pathlib import Path
from flask import Blueprint, request, current_app
from werkzeug.utils import secure_filename
import magic
import tasks

api = Blueprint("api", __name__)

def validate_request():
    # Error out if encoding is gzip. TODO(james): Handle gzip
    if request.content_encoding == "gzip":
        return {"error": "Cannot accept gzip"}, 400

    # Ensure endpoint was called with API key, and that the key exists
    apikey = request.args.get("api-key", default=None)
    if apikey is None:
        return {"error": "Missing api key"}, 400

    project = Project.query\
        .with_entities(Project.id)\
        .filter_by(api_key=apikey)\
        .first()
    if project is None:
        return {"error": "Bad api key"}, 400

    return project

@api.route('/api/minidump/upload', methods=["POST"])
def upload_minidump():
    """
    A Crashpad_handler sets this endpoint as their upload url with the "-no-upload-gzip"
    argument, and it will save and prepare the file for processing
    :return:
    """
    project = validate_request()
    if project is not Project:
        return project

    # Ensure minidump file was uploaded
    if "upload_file_minidump" not in request.files.keys():
        return {"error": "Missing minidump"}, 400
    minidump = request.files["upload_file_minidump"]
    minidump_fname = secure_filename(minidump.filename)

    # Validate magic number
    magic_number = magic.from_buffer(minidump.stream.read(2048), mime=True)
    if magic_number != "application/x-dmp":
        return {"error": "Bad Minidump"}, 400

    # At this point, we have received a minidump validated to be the correct type.
    # Save the file, insert annotations, and insert minidump records.

    # Save the minidump
    minidump_file = Path(current_app.config["cfg"]["storage"]["minidump_location"]) / str(project.id) / minidump_fname
    minidump_file.parent.mkdir(parents=True, exist_ok=True)
    minidump.stream.seek(0)
    minidump.save(minidump_file.absolute())

    # Add minidump to database
    new_dump = Minidump(
        filename=minidump_fname,
        project_id=project.id,
        client_guid=request.args.get("guid", default=None))
    db.session.add(new_dump)
    db.session.flush()

    # Add annotations to database
    annotation = dict(request.values)
    annotation.pop("guid", None)  # Remove GUID value from annotations
    annotation.pop("api-key", None)
    for key, value in annotation.items():
        new_annotation = Annotation(minidump_id=new_dump.id, key=key, value=value)
        db.session.add(new_annotation)

    db.session.commit()

    tasks.decode_minidump(new_dump.id)()

    return {"status": "success"}, 200


@api.route('/api/symbol/upload/', methods=["POST"])
def upload_symbol():
    """
    Endpoint to upload a symbol file
    Required parameters:
    - api-key
    - symbol-file

    body parameters :
    - metadata

    :return:
    """
    project = validate_request()
    if project is not Project:
        return project

    # Get first line of the file
    symfile = request.files.get("symbol-file", default=None)
    if symfile is None:
        return {"error": "Missing symbol file"}, 400

    # Get relevant module info from first line of file
    metadata = symfile.stream.readline().rstrip().decode('utf-8').split(' ')
    build_id, module_id = metadata[3], metadata[4]

    # Check if module_id already exists
    res = Symbol.query.filter_by(build_id=build_id).first()
    if res:
        return {"error": "Symbol file already uploaded"}, 400

    dir_location = Path(module_id, build_id, secure_filename(symfile.filename))
    sym_loc = Path(current_app.config["cfg"]["storage"]["symbol_location"], str(project.id)) / dir_location
    sym_loc.parent.mkdir(parents=True, exist_ok=True)

    # Save to filesystem
    symfile.save(sym_loc)

    # Commit to Database
    new_sym = Symbol(project_id=project.id, file_location=str(dir_location), build_id=build_id)
    db.session.add(new_sym)
    db.session.commit()

    return {"message": "success"}, 200
