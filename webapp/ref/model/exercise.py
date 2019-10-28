import datetime
import enum
import pickle
import threading
import time
from io import BytesIO

import docker
import yaml
from flask import current_app
from flask_bcrypt import check_password_hash, generate_password_hash
from rq.job import Job

from .enums import ExerciseBuildStatus, ExerciseServiceType
from ref import db
from sqlalchemy import Column, Integer, PickleType, create_engine

class ConfigParsingError(Exception):

    def __init__(self, msg, path=None):
        if path:
            msg = f'{msg} ({path})'
        super().__init__(msg)

class ParsingError(Exception):
    pass

#Upgrade -> stop old container -> start new container with new overlay

class ExerciseInstanceEntryService(db.Model):
    """
    An ExerciseInstanceContainer represents a container that belongs to a specififc
    ExerciseInstance. A ExerciseInstance can have multiple containers.
    """
    __tablename__ = 'exercise_instance_entry_service'
    id = db.Column(db.Integer, primary_key=True)

    #The instance this entry service belongs to
    instance_id = db.Column(db.Integer, db.ForeignKey('exercise_instance.id'))

    # exercise_entry_service_id = db.Column(db.Integer, db.ForeignKey('exercise_entry_service.id'),
    #     nullable=False)

    container_id = db.Column(db.Text(), unique=True)

    def overlay_upper(self):
        return f'{self.instance.persistance_path}/entry-upper'

    def overlay_work(self):
        return f'{self.instance.persistance_path}/entry-work'

    def overlay_merged(self):
        return f'{self.instance.persistance_path}/entry-merged'

class ExerciseInstance(db.Model):
    """
    An ExerciseInstance represents a instance of an exercise.
    Such a instance is bound to a single user.
    """
    __tablename__ = 'exercise_instance'
    id = db.Column(db.Integer, primary_key=True)

    entry_service = db.relationship("ExerciseInstanceEntryService", uselist=False, backref="instance")

    #Network id all containers of this exercise are connected to
    network_id = db.Column(db.Text(), unique=True)

    #Exercise this instance belongs to (backref name is exercise)
    exercise_id = db.Column(db.Integer, db.ForeignKey('exercise.id'),
        nullable=False)

    #Student this instance belongs to (backref name is user)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'),
        nullable=False)

    def persistance_path(self):
        return self.exercise.persistence_path + f'/instances/{self.user.id}'


class ExerciseEntryService(db.Model):
    """
    A ExerciseService descrives a service that is provided to the user.

    """
    __tablename__ = 'exercise_entry_service'
    id = db.Column(db.Integer, primary_key=True)

    exercise_id = db.Column(db.Integer, db.ForeignKey('exercise.id'), nullable=False)

    #Path inside the container that is persistet
    persistance_container_path = db.Column(db.Text())

    files = db.Column(PickleType())
    build_cmd = db.Column(db.PickleType(), nullable=True)

    disable_aslr = db.Column(db.Boolean(), nullable=False)
    cmd = db.Column(db.Text(), nullable=True)

    @property
    def persistance_lower(self):
        return self.exercise.persistence_path + f'/entry-server/lower'

    @property
    def image_name(self):
        """
        Name of the docker image that was build based on this configuration.
        """
        return f'remote-exercises-framework-{self.exercise.short_name}-entry:v{self.exercise.version}'


class ExerciseService(db.Model):
    """
    A ExerciseService descrives a service that is provided to the user.

    """
    __tablename__ = 'exercise_service'
    id = db.Column(db.Integer, primary_key=True)

    #Backref is exercise
    exercise_id = db.Column(db.Integer, db.ForeignKey('exercise.id'), nullable=False)

    files = db.Column(PickleType())
    build_cmd = db.Column(db.PickleType(), nullable=True)

    disable_aslr = db.Column(db.Boolean(), nullable=False)
    bind_executable = db.Column(db.Text(), nullable=True)


class Exercise(db.Model):
    """
    An Exercise is a description of a task that can be deployed for the user.
    A single exercise consists of at least one ExerciseService.
    In order to make a exercise available to a student, an ExerciseInstance must be
    created.
    """
    __tablename__ = 'exercise'
    id = db.Column(db.Integer, primary_key=True)

    #The services that defnies the entrypoint of this exercise
    #entry_service = db.relationship("ExerciseEntryService", uselist=False, back_populates="exercise")
    entry_service = db.relationship("ExerciseEntryService", uselist=False, backref="exercise")

    #Additional services that are mapped into the network for this exercise.
    services = db.relationship('ExerciseService', backref='exercise', lazy=True)

    #Folder the template was initially imported from
    template_import_path = db.Column(db.Text(), nullable=False, unique=False)

    #Folder where a copy of the template is stored during initial import
    template_path = db.Column(db.Text(), nullable=False, unique=True)

    persistence_path = db.Column(db.Text(), nullable=False, unique=True)

    #Name that identifies the exercise
    short_name = db.Column(db.Text(), nullable=False, unique=False)
    description = db.Column(db.Text(), nullable=False)
    version = db.Column(db.Integer(), nullable=False)

    #Is this Exercise version deployed by default in case a instance is requested?
    #At most one exercise with same short_name can have this flag.
    is_default = db.Column(db.Boolean(), nullable=False)

    allow_internet = db.Column(db.Boolean(), nullable=True, default=False)

    build_job_result = db.Column(db.Text(), nullable=True)
    build_job_status: ExerciseBuildStatus = db.Column(db.Enum(ExerciseBuildStatus), nullable=False)

    #All running instances of this exercise
    instances = db.relationship('ExerciseInstance', backref='exercise', lazy=True)

