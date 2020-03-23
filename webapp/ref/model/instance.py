import base64
import datetime
import enum
import hashlib
import pickle
import threading
import time
from io import BytesIO

import docker
import yaml
from flask import current_app
from rq.job import Job

from flask_bcrypt import check_password_hash, generate_password_hash
from ref import db
from sqlalchemy import Column, Integer, PickleType, and_, create_engine, or_

from .enums import ExerciseBuildStatus, ExerciseServiceType
from .util import CommonDbOpsMixin, ModelToStringMixin


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

    #Whether this is a normal entry service or a submission
    is_submission = db.Column(db.Boolean(), nullable=False)

    @property
    def overlay_submission_lower(self):
        """
        The directory that contains the files submitted by a user.
        """
        return f'{self.instance.persistance_path}/entry-submission-lower'

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

    def get_key(self) -> bytes:
        secret_key = current_app.config['SECRET_KEY']
        instance_key = hashlib.sha256()
        instance_key.update(secret_key.encode())
        instance_key.update(str(self.id).encode())
        instance_key = instance_key.digest()
        return instance_key

    def is_submission(self):
        """
        Whether this is a submitted instance (a solution submitted by a user)
        """
        return self.entry_service.is_submission

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
