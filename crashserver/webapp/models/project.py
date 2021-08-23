import pathlib
import enum

from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text
from flask import current_app

from crashserver.webapp import db
from crashserver.utility import sysinfo
from crashserver.config import settings


class ProjectType(enum.Enum):
    SIMPLE = "Simple"
    VERSIONED = "Versioned"

    @staticmethod
    def get_type_from_str(ptype):
        if ptype == "simple":
            return ProjectType.SIMPLE
        if ptype == "versioned":
            return ProjectType.VERSIONED
        return None


class Project(db.Model):
    """
    Crash Server is capable of storing symbols for, and decoding minidumps for multiple projects.

    id: Generated GUID for this table
    date_created: The timestamp of when the minidump was uploaded
    project_name: User-friendly interface name of the project
    api_key: An api key to be used when uploading minidumps
    """

    __tablename__ = "project"
    id = db.Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    date_created = db.Column(db.DateTime(timezone=True), server_default=func.now())
    project_name = db.Column(db.Text(), nullable=False)
    project_type = db.Column(db.Enum(ProjectType), nullable=False)
    api_key = db.Column(db.String(length=32), nullable=False)

    # Relationships
    minidump = db.relationship("Minidump", viewonly=True)
    symbol = db.relationship("Symbol")

    def create_directories(self):
        self.symbol_location.mkdir(parents=True, exist_ok=True)
        self.minidump_location.mkdir(parents=True, exist_ok=True)

    @property
    def symbol_location(self):
        return pathlib.Path(settings.storage.symbol, str(self.id)).absolute()

    @property
    def minidump_location(self):
        return pathlib.Path(settings.storage.minidump, str(self.id)).absolute()

    @property
    def total_minidump_size(self):
        """:return: Size of this projects minidump location in bytes"""
        return sysinfo.get_directory_size(self.minidump_location)

    @property
    def total_symbol_size(self):
        """:return: Size of this projects symbol location in bytes"""
        return sysinfo.get_directory_size(self.symbol_location)
