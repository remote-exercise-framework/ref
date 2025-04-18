from __future__ import annotations

import base64
import datetime
import enum
import hashlib
import pickle
import threading
import time
import typing
from collections import defaultdict
from io import BytesIO
from pathlib import Path
from typing import Collection, List

import docker
import yaml
from flask import current_app
from rq.job import Job
from sqlalchemy import Column, Integer, PickleType, and_, create_engine, or_
from sqlalchemy.orm import joinedload, raiseload

from flask_bcrypt import check_password_hash, generate_password_hash
from ref import db

from .enums import ExerciseBuildStatus
from .instance import Instance, Submission
from .util import CommonDbOpsMixin, ModelToStringMixin


class ConfigParsingError(Exception):

    def __init__(self, msg: str, path: str = None):
        if path:
            msg = f'{msg} ({path})'
        super().__init__(msg)

class RessourceLimits(CommonDbOpsMixin, ModelToStringMixin, db.Model):

    __to_str_fields__ = ['id', 'cpu_cnt_max', 'cpu_shares', 'pids_max', 'memory_in_mb', 'memory_swap_in_mb', 'memory_kernel_in_mb']
    __tablename__ = 'exercise_ressource_limits'
    id = db.Column(db.Integer, primary_key=True)

    cpu_cnt_max: float = db.Column(db.Float(), nullable=True, default=None)
    cpu_shares: int = db.Column(db.Integer(), nullable=True, default=None)

    pids_max: int = db.Column(db.Integer(), nullable=True, default=None)

    memory_in_mb: int = db.Column(db.Integer(), nullable=True, default=None)
    memory_swap_in_mb: int = db.Column(db.Integer(), nullable=True, default=None)
    memory_kernel_in_mb: int = db.Column(db.Integer(), nullable=True, default=None)

class ExerciseEntryService(CommonDbOpsMixin, ModelToStringMixin, db.Model):
    """
    Each Exercise must have exactly one ExerciseEntryService that represtens the service
    that serves as entry point for it.
    """
    __to_str_fields__ = ['id', 'exercise_id']
    __tablename__ = 'exercise_entry_service'
    __allow_unmapped__ = True

    id = db.Column(db.Integer, primary_key=True)

    #The exercise this entry service belongs to
    exercise_id: int = db.Column(db.Integer, db.ForeignKey('exercise.id', ondelete='RESTRICT'), nullable=False)
    exercise: 'Exercise' = db.relationship("Exercise", foreign_keys=[exercise_id], back_populates="entry_service")

    #Path inside the container that is persistet
    persistance_container_path: str = db.Column(db.Text(), nullable=True)

    files: List[str] = db.Column(PickleType(), nullable=True)

    # List of commands that are executed when building the service's Docker image.
    build_cmd: List[str] = db.Column(db.PickleType(), nullable=True)

    no_randomize_files: typing.Optional[List[str]] = db.Column(db.PickleType(), nullable=True)

    disable_aslr: bool = db.Column(db.Boolean(), nullable=False)

    # Command that is executed as soon a user connects (list)
    cmd: List[str] = db.Column(db.PickleType(), nullable=False)

    readonly: bool = db.Column(db.Boolean(), nullable=False, default=False)

    allow_internet: bool = db.Column(db.Boolean(), nullable=False, default=False)

    #options for the flag that is placed inside the container
    flag_path: str = db.Column(db.Text(), nullable=True)
    flag_value: str = db.Column(db.Text(), nullable=True)
    flag_user: str = db.Column(db.Text(), nullable=True)
    flag_group: str = db.Column(db.Text(), nullable=True)
    flag_permission: str = db.Column(db.Text(), nullable=True)

    ressource_limit_id: int = db.Column(db.Integer, db.ForeignKey('exercise_ressource_limits.id', ondelete='RESTRICT'), nullable=True)
    ressource_limit: RessourceLimits = db.relationship("RessourceLimits", foreign_keys=[ressource_limit_id])

    @property
    def persistance_lower(self) -> str:
        """
        Path to the local directory that contains the data located at persistance_container_path
        in the exercise image.
        """
        return self.exercise.persistence_path + f'/entry-server/lower'

    @property
    def image_name(self) -> str:
        """
        Name of the docker image that was build based on this configuration.
        """
        return f'{current_app.config["DOCKER_RESSOURCE_PREFIX"]}{self.exercise.short_name}-entry:v{self.exercise.version}'


class ExerciseService(CommonDbOpsMixin, ModelToStringMixin, db.Model):
    """
    A ExerciseService describes a service that runs in the same network as
    the ExerciseEntryService. A usecase for an ExerciseService might be
    the implementation of a networked service that must be hacked by a user.
    """
    __to_str_fields__ = ['id', 'exercise_id']
    __tablename__ = 'exercise_service'
    __allow_unmapped__ = True

    id: int = db.Column(db.Integer, primary_key=True)

    name: str = db.Column(db.Text())

    #Backref is exercise
    exercise_id: int = db.Column(db.Integer, db.ForeignKey('exercise.id', ondelete='RESTRICT'), nullable=False)
    exercise: 'Exercise' = db.relationship("Exercise", foreign_keys=[exercise_id], back_populates="services")

    files: List[str] = db.Column(PickleType(), nullable=True)
    build_cmd: List[str] = db.Column(db.PickleType(), nullable=True)

    disable_aslr: bool = db.Column(db.Boolean(), nullable=False)
    cmd: List[str] = db.Column(db.PickleType(), nullable=False)

    readonly: bool = db.Column(db.Boolean(), nullable=True, default=False)

    allow_internet: bool = db.Column(db.Boolean(), nullable=True, default=False)

    instances: List[Instance] = db.relationship("InstanceService", back_populates="exercise_service", lazy=True, passive_deletes='all')

    # health_check_cmd: List[str] = db.Column(db.PickleType(), nullable=False)

    flag_path: str = db.Column(db.Text(), nullable=True)
    flag_value: str = db.Column(db.Text(), nullable=True)
    flag_user: str = db.Column(db.Text(), nullable=True)
    flag_group: str = db.Column(db.Text(), nullable=True)
    flag_permission: str = db.Column(db.Text(), nullable=True)

    @property
    def image_name(self) -> str:
        """
        Name of the docker image that was build based on this configuration.
        """
        return f'{current_app.config["DOCKER_RESSOURCE_PREFIX"]}{self.exercise.short_name}-{self.name}:v{self.exercise.version}'

class Exercise(CommonDbOpsMixin, ModelToStringMixin, db.Model):
    """
    An Exercise is a description of a task that can be deployed for a user.
    A single exercise consists of at least one ExerciseService.
    In order to make a exercise available to a student, an ExerciseInstance must be
    created.
    """
    __to_str_fields__ = ['id', 'short_name', 'version', 'category', 'build_job_status']
    __tablename__ = 'exercise'
    __allow_unmapped__ = True


    id: int = db.Column(db.Integer, primary_key=True)

    #The services that defines the entrypoint of this exercise
    entry_service: ExerciseEntryService = db.relationship("ExerciseEntryService", uselist=False, back_populates="exercise",  passive_deletes='all')

    #Additional services that are mapped into the network for this exercise.
    services: List[ExerciseService] = db.relationship('ExerciseService', back_populates='exercise', lazy=True, passive_deletes='all')

    #Folder the template was initially imported from
    template_import_path: str = db.Column(db.Text(), nullable=False, unique=False)

    #Folder where a copy of the template is stored for persisting it after import
    template_path: str = db.Column(db.Text(), nullable=False, unique=True)

    #Path to the folder that contains all persisted data of this exercise.
    persistence_path: str = db.Column(db.Text(), nullable=False, unique=True)

    #Name that identifies the exercise
    short_name: str = db.Column(db.Text(), nullable=False, unique=False)

    #Version of the exercise used for updating mechanism.
    version: int = db.Column(db.Integer(), nullable=False)

    #Used to group the exercises
    category: str = db.Column(db.Text(), nullable=True, unique=False)


    #Instances must be submitted before this point in time.
    submission_deadline_end: datetime.datetime = db.Column(db.DateTime(), nullable=True)

    submission_deadline_start: datetime.datetime = db.Column(db.DateTime(), nullable=True)

    submission_test_enabled: datetime.datetime = db.Column(db.Boolean(), nullable=False)

    #Max point a user can get for this exercise. Might be None.
    max_grading_points: int = db.Column(db.Integer, nullable=True)

    #Is this Exercise version deployed by default in case an instance is requested?
    #At most one exercise with same short_name can have this flag.
    is_default: bool = db.Column(db.Boolean(), nullable=False)

    #Log of the last build run
    build_job_result: str = db.Column(db.Text(), nullable=True)

    #Build status of the docker images that belong to the exercise
    build_job_status: ExerciseBuildStatus = db.Column(db.Enum(ExerciseBuildStatus), nullable=False)

    #All running instances of this exercise
    instances: List[Instance] = db.relationship('Instance', back_populates='exercise', lazy=True,  passive_deletes='all')

    def get_users_instance(self, user) -> List[Instance]:
        for instance in self.instances:
            if instance.user == user:
                return instance
        return None

    def predecessors(self) -> List[Exercise]:
        exercises = Exercise.query.filter(
            and_(
                Exercise.short_name == self.short_name,
                Exercise.version < self.version
                )
            ).order_by(Exercise.version.desc()).all()
        return exercises

    def is_update(self) -> bool:
        return len(self.predecessors()) > 0

    def predecessor(self) -> Exercise:
        predecessors = self.predecessors()
        if predecessors:
            return predecessors[0]
        else:
            return None

    def exists(self) -> bool:
        """
        Check whether an exercise with same short_name and version can be
        found in the DB.
        """
        exercise = self.get_exercise(self.short_name, self.version)
        return exercise is not None

    def successors(self) -> List[Exercise]:
        exercises = Exercise.query.filter(
            and_(
                Exercise.short_name == self.short_name,
                Exercise.version > self.version
                )
            ).order_by(Exercise.version).all()
        return exercises

    def successor(self) -> Exercise:
        successors = self.successors()
        if successors:
            return successors[0]
        else:
            return None

    def head(self) -> Exercise:
        """
        Returns the newest version of this exercise.
        """
        ret = self.successors() + [self]
        return max(ret, key=lambda e: e.version, default=None)

    def tail(self) -> Exercise:
        """
        Returns the oldest version of this exercise.
        """
        ret = self.predecessors() + [self]
        return min(ret, key=lambda e: e.version, default=None)

    @staticmethod
    def get_default_exercise(short_name, for_update=False) -> Exercise:
        """
        Returns and locks the default exercise for the given short_name.
        """
        q = Exercise.query.filter(Exercise.short_name == short_name).filter(Exercise.is_default == True)
        return q.one_or_none()

    @staticmethod
    def get_exercise(short_name, version, for_update=False) -> Exercise:
        exercise = Exercise.query.filter(
            and_(
                Exercise.short_name == short_name,
                Exercise.version == version
                )
        )
        return exercise.one_or_none()

    @staticmethod
    def get_exercises(short_name) -> List[Exercise]:
        exercises = Exercise.query.filter(
            Exercise.short_name == short_name
        )
        return exercises.all()

    def deadine_passed(self) -> bool:
        assert self.has_deadline(), 'Exercise does not have a deadline'
        return datetime.datetime.now() > self.submission_deadline_end

    def has_deadline(self) -> bool:
        return self.submission_deadline_end is not None

    def has_started(self) -> bool:
        return self.submission_deadline_start is None or datetime.datetime.now() > self.submission_deadline_start

    def submission_heads(self) -> List[Submission]:
        """
        Returns the most recent submission for this exercise for each user.
        Note: This function does not consider Submissions of other
        version of this exercise. Hence, the returned submissions might
        not be the most recent ones for an specific instance.
        """
        most_recent_instances = []
        instances_per_user = defaultdict(list)
        instances = Instance.query.filter(Instance.exercise == self, Instance.submission != None).all()

        for instance in instances:
            instances_per_user[instance.user] += [instance]
        for _, instances in instances_per_user.items():
            most_recent_instances += [max(instances, key=lambda e: e.creation_ts)]
        return [e.submission for e in most_recent_instances if e.submission]

    def submission_heads_global(self) -> List[Submission]:
        """
        Same as .submission_heads(), except only submissions
        that have no newer (based on a more recent exercise version)
        submission are returned.
        """
        submissions = []
        own_submissions = self.submission_heads()
        for exercise in [self] + self.successors():
            submissions += exercise.submission_heads()

        seen_users = set()
        ret = []

        # Iterate starting with the submissions belonging to the most recent exercise (highest version)
        for submission in submissions[::-1]:
            user = submission.submitted_instance.user
            if user in seen_users:
                continue
            seen_users.add(user)
            if submission in own_submissions:
                ret += [submission]

        return ret

    @property
    def active_instances(self) -> List[Instance]:
        """
        Get all instances of this exercise that are no submissions.
        Note: This function does not returns Instances that belong to
        another version of this exercise.
        """
        return [i for i in self.instances if not i.submission]

    def submissions(self, user=None) -> List[Submission]:
        """
        Get all submissions of this exercise.
        Note: This function does not returns Submissions that belong to
        another version of this exercise.
        """
        ret = [i.submission for i in self.instances if i.submission]
        if user:
            ret = [e for e in ret if e.user == user]
        return ret

    def ungraded_submissions(self, user=None):
        submissions = self.submissions(user=user)
        return [s for s in submissions if not s.grading and not s.successors()]

    def has_submissions(self) -> bool:
        for i in self.instances:
            if i.submission:
                return True
        return False

    def has_graded_submissions(self) -> bool:
        """
        Check whether this exercise has any graded submissions.
        Note: This function does not consider Submissions of other
        version of this exercise.
        """
        submissions = self.submissions()
        for s in submissions:
            if s.grading:
                return True
        return False

    def avg_points(self) -> float:
        """
        Returns the average points calculated over all submission heads.
        If there are no submissions, None is returned.
        Note: This function does not consider Submissions of other
        version of this exercise.
        """
        submissions = [e.grading for e in self.submission_heads() if e.is_graded()]
        if not submissions:
            return None
        return sum([g.points_reached for g in submissions]) / len(submissions)
