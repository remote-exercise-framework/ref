import base64
import datetime
import enum
import hashlib
import pickle
import threading
import time
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Collection, List

import docker
import yaml
from flask import current_app
from rq.job import Job
from sqlalchemy import Column, Integer, PickleType, and_, create_engine, or_

from flask_bcrypt import check_password_hash, generate_password_hash
from ref import db

from .enums import ExerciseBuildStatus
from .user import User
from .util import CommonDbOpsMixin, ModelToStringMixin

#Avoid cyclic dependencies for type hinting
if TYPE_CHECKING:
    from .exercise import Exercise, ExerciseEntryService, ExerciseService

class InstanceService(CommonDbOpsMixin, ModelToStringMixin, db.Model):
    """
    An InstanceService is an instance of a ExerciseService and its functionality
    is entirely defined by an ExerciseService (.exercise_service).
    Each InstanceService belongs to an Instance and is responsible to keep
    runtime information of the service it is impelmenting.
    """

    __to_str_fields__ = ['id', 'instance_id', 'exercise_service_id', 'container_id']
    __tablename__ = 'instance_service'

    # 1. Each instance only uses a specific service once.
    __table_args__ = (db.UniqueConstraint('instance_id', 'exercise_service_id'), )

    id: int = db.Column(db.Integer, primary_key=True)

    #The exercise service describing this service (backref is exercise_service)
    exercise_service_id: int = db.Column(db.Integer, db.ForeignKey('exercise_service.id', ondelete='RESTRICT'), nullable=False)
    exercise_service: 'ExerciseService' = db.relationship('ExerciseService', foreign_keys=[exercise_service_id], back_populates="instances")

    #The instance this service belongs to.
    instance_id: int = db.Column(db.Integer, db.ForeignKey('exercise_instance.id', ondelete='RESTRICT'), nullable=False)
    instance: 'Instance' = db.relationship('Instance', foreign_keys=[instance_id], back_populates="peripheral_services")

    #The docker container id of this service.
    container_id: str = db.Column(db.Text(), unique=True)

    @property
    def hostname(self):
        return self.exercise_service.name

class InstanceEntryService(CommonDbOpsMixin, ModelToStringMixin, db.Model):
    """
    An InstanceEntryService is an instance of an ExerciseEntryService and
    serves as the entrypoint for a user.
    Such an InstanceEntryService is exposed via SSH and supports data persistance.
    """
    __to_str_fields__ = ['id', 'instance_id', 'container_id']
    __tablename__ = 'exercise_instance_entry_service'
    id: int = db.Column(db.Integer, primary_key=True)

    #The instance this entry service belongs to
    instance_id: int = db.Column(db.Integer, db.ForeignKey('exercise_instance.id', ondelete='RESTRICT'), nullable=False)
    instance: 'Instance' = db.relationship('Instance', foreign_keys=[instance_id], back_populates="entry_service")

    #ID of the docker container.
    container_id: int = db.Column(db.Text(), unique=True)

    @property
    def overlay_submitted(self) -> str:
        """
        Directory that is used as lower dir besides the "base" files of the exercise.
        This directory can be used to store submitted files.
        """
        return f'{self.instance.persistance_path}/entry-submitted'

    @property
    def overlay_upper(self) -> str:
        """
        Path to the directory that contains the persisted user data.
        This directory is used as the 'upper' directory for overlayfs.
        """
        return f'{self.instance.persistance_path}/entry-upper'

    @property
    def overlay_work(self) -> str:
        """
        Path to the working directory used by overlayfs for persistance.
        """
        return f'{self.instance.persistance_path}/entry-work'

    @property
    def overlay_merged(self) -> str:
        """
        Path to the directory that contains the merged content of the upper and lower directory.
        """
        return f'{self.instance.persistance_path}/entry-merged'

    @property
    def hostname(self):
        return self.instance.exercise.short_name

class Instance(CommonDbOpsMixin, ModelToStringMixin, db.Model):
    """
    An Instance represents a instance of an exercise.
    Such an instance is bound to a single user.
    """
    __to_str_fields__ = ['id', 'exercise', 'entry_service', 'user', 'network_id', 'peripheral_services_internet_network_id', 'peripheral_services_network_id']
    __tablename__ = 'exercise_instance'

    id: int = db.Column(db.Integer, primary_key=True)

    entry_service: InstanceEntryService = db.relationship("InstanceEntryService", uselist=False, back_populates="instance", passive_deletes='all')
    peripheral_services: List[InstanceService] = db.relationship('InstanceService', back_populates='instance', lazy=True,  passive_deletes='all')

    #The network the entry service is connected to the ssh server by
    network_id: str = db.Column(db.Text(), unique=True)

    #Network the entry service is connected to the peripheral services
    peripheral_services_internet_network_id: str = db.Column(db.Text(), nullable=True, unique=True)
    peripheral_services_network_id: str = db.Column(db.Text(), nullable=True, unique=True)

    #Exercise this instance belongs to (backref name is exercise)
    exercise_id: int = db.Column(db.Integer, db.ForeignKey('exercise.id', ondelete='RESTRICT'),
        nullable=False)
    exercise: 'Exercise' = db.relationship('Exercise', foreign_keys=[exercise_id], back_populates="instances")

    #Student this instance belongs to (backref name is user)
    user_id: int = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='RESTRICT'),
        nullable=False)
    user: 'User' = db.relationship('User', foreign_keys=[user_id], back_populates="exercise_instances")

    creation_ts: datetime.datetime = db.Column(db.DateTime(), nullable=True)

    #All submission of this instance. If this list is empty, the instance was never submitted.
    submissions: List['Submission']  = db.relationship('Submission', foreign_keys='Submission.origin_instance_id', back_populates='origin_instance', lazy=True, passive_deletes='all')

    #If this instance is part of a subission, this field points to the Submission. If this field is set, submissions must be empty.
    submission: List['Submission'] = db.relationship("Submission", foreign_keys='Submission.submitted_instance_id', uselist=False, back_populates="submitted_instance", passive_deletes='all')

    def get_latest_submission(self) -> 'Submission':
        assert not self.submission
        if not self.submissions:
            return None
        return max(self.submissions, key=lambda e: e.submission_ts)

    def get_key(self) -> bytes:
        secret_key = current_app.config['SECRET_KEY']
        instance_key = hashlib.sha256()
        instance_key.update(secret_key.encode())
        instance_key.update(str(self.id).encode())
        instance_key = instance_key.digest()
        return instance_key

    @property
    def long_name(self) -> str:
        """
        Name and version of the exercise this instance is based on.
        """
        return f'{self.exercise.short_name}-v{self.exercise.version}'

    @property
    def persistance_path(self) -> str:
        """
        Path used to store all data that belongs to this instance.
        """
        #Make sure there is a PK by flushing pending DB ops
        current_app.db.session.flush(objects=[self])
        assert self.id is not None
        return self.exercise.persistence_path + f'/instances/{self.id}'

    @staticmethod
    def get_instances_by_exercise(short_name, version=None) -> List['Instance']:
        instances = Instance.query.all()
        ret = []
        for i in instances:
            if i.exercise.short_name == short_name and (version is None or i.exercise.version == version):
                ret.append(i)
        return ret

    @staticmethod
    def get_by_user(user_id) -> 'Instance':
        ret = []
        instances = Instance.all()
        for i in instances:
            if i.user.id == user_id:
                ret.append(i)
        return ret

    def is_modified(self) -> bool:
        upper_dir = Path(self.entry_service.overlay_upper)
        modified_files = set()
        for path in upper_dir.glob('*'):
            if path.parts[-1] in ['.ssh', '.bash_history', '.mypy_cache']:
                continue
            modified_files.add(path)
        current_app.logger.info(f'Instance {self} has following modified files {modified_files}')
        return len(modified_files) != 0

    def is_submission(self) -> bool:
        return self.submission


class Submission(CommonDbOpsMixin, ModelToStringMixin, db.Model):
    """
    A submission represents a specific state of an instance at one point in time (snapshot).
    """
    __to_str_fields__ = ['id', 'origin_instance_id', 'submitted_instance_id']
    __tablename__ = 'submission'

    id = db.Column(db.Integer, primary_key=True)

    #Reference to the Instance that was submitted. Hence, submitted_instance is a snapshot of origin_instance.
    origin_instance_id: int = db.Column(db.Integer, db.ForeignKey('exercise_instance.id', ondelete='RESTRICT'), nullable=False)
    origin_instance: Instance = db.relationship("Instance", foreign_keys=[origin_instance_id], back_populates="submissions")

    """
    Reference to the Instance that represents the state of origin_instance at the time the submission was created.
    This instance uses the changed data (upper overlay) of the submitted instance as lower layer of its overlayfs.
    """
    submitted_instance_id: int = db.Column(db.Integer, db.ForeignKey('exercise_instance.id', ondelete='RESTRICT'), nullable=False)
    submitted_instance: Instance = db.relationship("Instance", foreign_keys=[submitted_instance_id], back_populates="submission")

    #Point in time the submission was created.
    submission_ts: datetime.datetime = db.Column(db.DateTime(), nullable=False)

    #Set if this Submission was graded
    grading_id: int = db.Column(db.Integer, db.ForeignKey('grading.id', ondelete='RESTRICT'), nullable=True)
    grading: 'Grading' = db.relationship("Grading", foreign_keys=[grading_id], back_populates="submission")

    
    test_output: str = db.Column(db.Text(), nullable=True)
    test_passed: bool = db.Column(db.Boolean(), nullable=True)

    def is_modified(self) -> bool:
        return self.submitted_instance.is_modified()

    def successors(self) -> List['Submission']:
        """
        Get all Submissions that belong to the same origin and have higher
        (where created later) creation timestamp then this Submission.
        """
        submissions = self.origin_instance.submissions
        return [s for s in submissions if s.submission_ts > self.submission_ts]

class Grading(CommonDbOpsMixin, ModelToStringMixin, db.Model):
    __to_str_fields__ = ['id']
    __tablename__ = 'grading'

    id: int = db.Column(db.Integer, primary_key=True)

    #The graded submission
    submission: List[Submission] = db.relationship("Submission", foreign_keys='Submission.grading_id', uselist=False, back_populates="grading", passive_deletes='all')
    
    points_reached: int = db.Column(db.Integer(), nullable=False)
    comment: str = db.Column(db.Text(), nullable=True)
    
    #Not that is never shown to the user
    private_note: str = db.Column(db.Text(), nullable=True)

    #Reference to the last user that applied changes
    last_edited_by_id: int = db.Column(db.Integer(), db.ForeignKey('user.id'), nullable=False)
    last_edited_by: User = db.relationship("User", foreign_keys=[last_edited_by_id])
    update_ts: datetime.datetime = db.Column(db.DateTime(), nullable=False)

    #Reference to the user that created this submission
    created_by_id: int = db.Column(db.Integer(), db.ForeignKey('user.id'), nullable=False)
    created_by: User = db.relationship("User", foreign_keys=[created_by_id])
    created_ts: datetime.datetime = db.Column(db.DateTime(), nullable=False)
