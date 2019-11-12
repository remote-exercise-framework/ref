import datetime
import enum
import pickle
import threading
import time
from io import BytesIO

from sqlalchemy import and_, or_

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

class InstanceEntryService(db.Model):
    """
    Container that represents the entrypoint for a specific task instance.
    Such and InstanceEntryService is exposed via SSH and supports data persistance.
    """
    __tablename__ = 'exercise_instance_entry_service'
    id = db.Column(db.Integer, primary_key=True)

    #The instance this entry service belongs to
    instance_id = db.Column(db.Integer, db.ForeignKey('exercise_instance.id'))

    #ID of the container
    container_id = db.Column(db.Text(), unique=True)

    def overlay_upper(self):
        """
        Path to the directory that contains the persisted user data.
        This directory is used as the 'upper' directory for overlayfs.
        """
        return f'{self.instance.persistance_path}/entry-upper'

    def overlay_work(self):
        """
        Path to the working directory used by overlayfs for persistance.
        """
        return f'{self.instance.persistance_path}/entry-work'

    def overlay_merged(self):
        """
        Path to the directory that contains the merged content of the upper and lower directory.
        """
        return f'{self.instance.persistance_path}/entry-merged'

class Instance(db.Model):
    """
    An Instance represents a instance of an exercise.
    Such an instance is bound to a single user.
    """
    __tablename__ = 'exercise_instance'
    id = db.Column(db.Integer, primary_key=True)

    entry_service = db.relationship("InstanceEntryService", uselist=False, backref="instance")

    #The network the entry service is connected to the ssh server by
    network_id = db.Column(db.Text(), unique=True)

    #peripheral_services =  db.relationship("...", uselist=False, backref="instance")

    #Network the entry service is connected to the peripheral services
    #services_network_id = db.Column(db.Text(), unique=True)

    #Exercise this instance belongs to (backref name is exercise)
    exercise_id = db.Column(db.Integer, db.ForeignKey('exercise.id'),
        nullable=False)

    #Student this instance belongs to (backref name is user)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'),
        nullable=False)

    @property
    def persistance_path(self):
        """
        Path used to store all data that belongs to this instance.
        """
        return self.exercise.persistence_path + f'/instances/{self.user.id}'


class ExerciseEntryService(db.Model):
    """
    Each Exercise must have exactly one ExerciseEntryService that represtens the service
    that serves as entry point for an exercise.
    """
    __tablename__ = 'exercise_entry_service'
    id = db.Column(db.Integer, primary_key=True)

    #The exercise this entry service belongs to
    exercise_id = db.Column(db.Integer, db.ForeignKey('exercise.id'), nullable=False)

    #Path inside the container that is persistet
    persistance_container_path = db.Column(db.Text())

    files = db.Column(PickleType())

    build_cmd = db.Column(db.PickleType(), nullable=True)

    disable_aslr = db.Column(db.Boolean(), nullable=False)
    cmd = db.Column(db.Text(), nullable=True)

    bind_executable = db.Column(db.Text(), nullable=True)

    readonly = db.Column(db.Boolean(), default=False)

    @property
    def persistance_lower(self):
        """
        Path to the local directory that contains the data located at persistance_container_path
        in the exercise image.
        """
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

    #Used to group the exercises
    category = db.Column(db.Text(), nullable=True, unique=False)

    description = db.Column(db.Text(), nullable=False)
    version = db.Column(db.Integer(), nullable=False)

    #Is this Exercise version deployed by default in case a instance is requested?
    #At most one exercise with same short_name can have this flag.
    is_default = db.Column(db.Boolean(), nullable=False)

    allow_internet = db.Column(db.Boolean(), nullable=True, default=False)

    build_job_result = db.Column(db.Text(), nullable=True)
    build_job_status: ExerciseBuildStatus = db.Column(db.Enum(ExerciseBuildStatus), nullable=False)

    #All running instances of this exercise
    instances = db.relationship('Instance', backref='exercise', lazy=True)

    def predecessor(self):
        exercise = Exercise.query.filter(
            and_(
                Exercise.short_name == self.short_name,
                Exercise.version < self.version
                )
            ).order_by(Exercise.version.desc()).first()
        return exercise

    def successor(self):
        exercise = Exercise.query.filter(
            and_(
                Exercise.short_name == self.short_name,
                Exercise.version > self.version
                )
            ).order_by(Exercise.version).first()
        return exercise
