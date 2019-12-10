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

from .util import ModelToStringMixin, CommonDbOpsMixin

class ConfigParsingError(Exception):

    def __init__(self, msg, path=None):
        if path:
            msg = f'{msg} ({path})'
        super().__init__(msg)

class ParsingError(Exception):
    pass

class InstanceService(CommonDbOpsMixin, ModelToStringMixin, db.Model):

    __to_str_fields__ = ['id', 'instance_id', 'exercise_service_id', 'container_id']
    __tablename__ = 'instance_service'
    __table_args__ = (db.UniqueConstraint('id', 'instance_id'), db.UniqueConstraint('id', 'exercise_service_id'))

    id = db.Column(db.Integer, primary_key=True)

    exercise_service_id = db.Column(db.Integer, db.ForeignKey('exercise_service.id'))
    instance_id = db.Column(db.Integer, db.ForeignKey('exercise_instance.id'))
    container_id = db.Column(db.Text(), unique=True)

class InstanceEntryService(CommonDbOpsMixin, ModelToStringMixin, db.Model):
    """
    Container that represents the entrypoint for a specific task instance.
    Such and InstanceEntryService is exposed via SSH and supports data persistance.
    """
    __to_str_fields__ = ['id', 'instance_id', 'container_id']
    __tablename__ = 'exercise_instance_entry_service'
    id = db.Column(db.Integer, primary_key=True)

    #The instance this entry service belongs to
    instance_id = db.Column(db.Integer, db.ForeignKey('exercise_instance.id', ondelete='RESTRICT'), nullable=False)

    #ID of the container
    container_id = db.Column(db.Text(), unique=True)

    @property
    def overlay_upper(self):
        """
        Path to the directory that contains the persisted user data.
        This directory is used as the 'upper' directory for overlayfs.
        """
        return f'{self.instance.persistance_path}/entry-upper'

    @property
    def overlay_work(self):
        """
        Path to the working directory used by overlayfs for persistance.
        """
        return f'{self.instance.persistance_path}/entry-work'

    @property
    def overlay_merged(self):
        """
        Path to the directory that contains the merged content of the upper and lower directory.
        """
        return f'{self.instance.persistance_path}/entry-merged'

class Instance(CommonDbOpsMixin, ModelToStringMixin, db.Model):
    """
    An Instance represents a instance of an exercise.
    Such an instance is bound to a single user.
    """
    __to_str_fields__ = ['id', 'exercise', 'entry_service', 'user', 'network_id', 'peripheral_services_internet_network_id', 'peripheral_services_network_id']
    __tablename__ = 'exercise_instance'

    id = db.Column(db.Integer, primary_key=True)

    entry_service = db.relationship("InstanceEntryService", uselist=False, backref="instance")
    peripheral_services = db.relationship('InstanceService', backref='instance', lazy=True)

    #The network the entry service is connected to the ssh server by
    network_id = db.Column(db.Text(), unique=True)

    #Network the entry service is connected to the peripheral services
    peripheral_services_internet_network_id = db.Column(db.Text(), nullable=True, unique=True)
    peripheral_services_network_id = db.Column(db.Text(), nullable=True, unique=True)

    #Exercise this instance belongs to (backref name is exercise)
    exercise_id = db.Column(db.Integer, db.ForeignKey('exercise.id', ondelete='RESTRICT'),
        nullable=False)

    #Student this instance belongs to (backref name is user)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='RESTRICT'),
        nullable=False)

    creation_ts = db.Column(db.DateTime(), nullable=True)

    @property
    def long_name(self):
        return f'{self.exercise.short_name}-v{self.exercise.version}'

    @property
    def persistance_path(self):
        """
        Path used to store all data that belongs to this instance.
        """
        return self.exercise.persistence_path + f'/instances/{self.user.id}'

    @classmethod
    def all(cls):
        return cls.query.all()

    @staticmethod
    def get_instances_by_exercise(short_name, version=None):
        instances = Instance.query.all()
        ret = []
        for i in instances:
            if i.exercise.short_name == short_name and (version is None or i.exercise.version == version):
                ret.append(i)
        return ret

    @staticmethod
    def get_by_user(user_id):
        ret = []
        instances = Instance.all()
        for i in instances:
            if i.user.id == user_id:
                ret.append(i)
        return ret

class ExerciseEntryService(CommonDbOpsMixin, ModelToStringMixin, db.Model):
    """
    Each Exercise must have exactly one ExerciseEntryService that represtens the service
    that serves as entry point for an exercise.
    """
    __to_str_fields__ = ['id', 'exercise_id']
    __tablename__ = 'exercise_entry_service'
    id = db.Column(db.Integer, primary_key=True)

    #The exercise this entry service belongs to
    exercise_id = db.Column(db.Integer, db.ForeignKey('exercise.id', ondelete='RESTRICT'), nullable=False)

    #Path inside the container that is persistet
    persistance_container_path = db.Column(db.Text(), nullable=True)

    files = db.Column(PickleType(), nullable=True)

    build_cmd = db.Column(db.PickleType(), nullable=True)

    disable_aslr = db.Column(db.Boolean(), nullable=False)

    #Command that is executed as soon a user connects (list)
    cmd = db.Column(db.PickleType(), nullable=False)

    readonly = db.Column(db.Boolean(), nullable=False, default=False)

    allow_internet = db.Column(db.Boolean(), nullable=False, default=False)

    #flag config option
    flag_path = db.Column(db.Text(), nullable=True)
    flag_value = db.Column(db.Text(), nullable=True)
    flag_user = db.Column(db.Text(), nullable=True)
    flag_group = db.Column(db.Text(), nullable=True)
    flag_permission = db.Column(db.Text(), nullable=True)

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
        return f'{current_app.config["DOCKER_RESSOURCE_PREFIX"]}-{self.exercise.short_name}-entry:v{self.exercise.version}'


class ExerciseService(CommonDbOpsMixin, ModelToStringMixin, db.Model):
    """
    A ExerciseService descrives a service that is provided to the user.

    """
    __to_str_fields__ = ['id', 'exercise_id']

    __tablename__ = 'exercise_service'
    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.Text())

    #Backref is exercise
    exercise_id = db.Column(db.Integer, db.ForeignKey('exercise.id', ondelete='RESTRICT'), nullable=False)

    files = db.Column(PickleType(), nullable=True)
    build_cmd = db.Column(db.PickleType(), nullable=True)

    disable_aslr = db.Column(db.Boolean(), nullable=False)
    cmd = db.Column(db.PickleType(), nullable=False)

    readonly = db.Column(db.Boolean(), nullable=True, default=False)

    allow_internet = db.Column(db.Boolean(), nullable=True, default=False)

    instances = db.relationship("InstanceService", backref="exercise_service", lazy=True)

    flag_path = db.Column(db.Text(), nullable=True)
    flag_value = db.Column(db.Text(), nullable=True)
    flag_user = db.Column(db.Text(), nullable=True)
    flag_group = db.Column(db.Text(), nullable=True)
    flag_permission = db.Column(db.Text(), nullable=True)

    @property
    def image_name(self):
        """
        Name of the docker image that was build based on this configuration.
        """
        return f'{current_app.config["DOCKER_RESSOURCE_PREFIX"]}-{self.exercise.short_name}-{self.name}:v{self.exercise.version}'

class Exercise(CommonDbOpsMixin, ModelToStringMixin, db.Model):
    """
    An Exercise is a description of a task that can be deployed for the user.
    A single exercise consists of at least one ExerciseService.
    In order to make a exercise available to a student, an ExerciseInstance must be
    created.
    """
    __to_str_fields__ = ['id', 'short_name', 'version', 'category', 'build_job_status']
    __tablename__ = 'exercise'

    id = db.Column(db.Integer, primary_key=True)

    #The services that defnies the entrypoint of this exercise
    #entry_service = db.relationship("ExerciseEntryService", uselist=False, back_populates="exercise")
    entry_service = db.relationship("ExerciseEntryService", uselist=False, backref="exercise")

    #Additional services that are mapped into the network for this exercise.
    services = db.relationship('ExerciseService', backref='exercise', lazy=True)

    #Folder the template was initially imported from
    template_import_path = db.Column(db.Text(), nullable=False, unique=False)

    #Folder where a copy of the template is stored for persisting it after import
    template_path = db.Column(db.Text(), nullable=False, unique=True)

    #Path to the folder that contains all persisted data of this exercise.
    persistence_path = db.Column(db.Text(), nullable=False, unique=True)

    #Name that identifies the exercise
    short_name = db.Column(db.Text(), nullable=False, unique=False)

    #Version of the exercise used for updating mechanism.
    version = db.Column(db.Integer(), nullable=False)

    #Used to group the exercises
    category = db.Column(db.Text(), nullable=True, unique=False)

    description = db.Column(db.Text(), nullable=True)

    #Is this Exercise version deployed by default in case a instance is requested?
    #At most one exercise with same short_name can have this flag.
    is_default = db.Column(db.Boolean(), nullable=False)

    #Log of the last build run
    build_job_result = db.Column(db.Text(), nullable=True)

    #Build status of the docker images that belong to the exercise
    build_job_status: ExerciseBuildStatus = db.Column(db.Enum(ExerciseBuildStatus), nullable=False)

    #All running instances of this exercise
    instances = db.relationship('Instance', backref='exercise', lazy=True)

    def get_users_instance(self, user):
        for instance in self.instances:
            if instance.user == user:
                return instance
        return None

    def predecessors(self):
        exercises = Exercise.query.filter(
            and_(
                Exercise.short_name == self.short_name,
                Exercise.version < self.version
                )
            ).order_by(Exercise.version.desc()).all()
        return exercises

    def predecessor(self):
        predecessors = self.predecessors()
        if predecessors:
            return predecessors[0]
        else:
            return None

    def successors(self):
        exercises = Exercise.query.filter(
            and_(
                Exercise.short_name == self.short_name,
                Exercise.version > self.version
                )
            ).order_by(Exercise.version).all()
        return exercises

    def successor(self):
        successors = self.successors()
        if successors:
            return successors[0]
        else:
            return None

    @staticmethod
    def get_default_exercise(short_name, for_update=False):
        """
        Returns and locks the default exercise for the given short_name.
        """
        q = Exercise.query.filter(Exercise.short_name == short_name).filter(Exercise.is_default == True)
        if for_update:
            q.with_for_update()
        return q.one_or_none()

    @staticmethod
    def get_exercise(short_name, version):
        exercise = Exercise.query.filter(
            and_(
                Exercise.short_name == short_name,
                Exercise.version == version
                )
        )
        return exercise.first()

    @staticmethod
    def get_exercises(short_name):
        exercises = Exercise.query.filter(
            Exercise.short_name == short_name
        )
        return exercises.all()

