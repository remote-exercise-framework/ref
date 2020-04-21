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

class ExerciseEntryService(CommonDbOpsMixin, ModelToStringMixin, db.Model):
    """
    Each Exercise must have exactly one ExerciseEntryService that represtens the service
    that serves as entry point for it.
    """
    __to_str_fields__ = ['id', 'exercise_id']
    __tablename__ = 'exercise_entry_service'
    id = db.Column(db.Integer, primary_key=True)

    #The exercise this entry service belongs to
    exercise_id: int = db.Column(db.Integer, db.ForeignKey('exercise.id', ondelete='RESTRICT'), nullable=False)

    #Path inside the container that is persistet
    persistance_container_path: str = db.Column(db.Text(), nullable=True)

    files: List[str] = db.Column(PickleType(), nullable=True)

    build_cmd: List[str] = db.Column(db.PickleType(), nullable=True)

    disable_aslr: bool = db.Column(db.Boolean(), nullable=False)

    #Command that is executed as soon a user connects (list)
    cmd: List[str] = db.Column(db.PickleType(), nullable=False)

    readonly: bool = db.Column(db.Boolean(), nullable=False, default=False)

    allow_internet: bool = db.Column(db.Boolean(), nullable=False, default=False)

    #options for the flag that is placed inside the container
    flag_path: str = db.Column(db.Text(), nullable=True)
    flag_value: str = db.Column(db.Text(), nullable=True)
    flag_user: str = db.Column(db.Text(), nullable=True)
    flag_group: str = db.Column(db.Text(), nullable=True)
    flag_permission: str = db.Column(db.Text(), nullable=True)

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
    id: int = db.Column(db.Integer, primary_key=True)

    name: str = db.Column(db.Text())

    #Backref is exercise
    exercise_id: int = db.Column(db.Integer, db.ForeignKey('exercise.id', ondelete='RESTRICT'), nullable=False)

    files: List[str] = db.Column(PickleType(), nullable=True)
    build_cmd: List[str] = db.Column(db.PickleType(), nullable=True)

    disable_aslr: bool = db.Column(db.Boolean(), nullable=False)
    cmd: List[str] = db.Column(db.PickleType(), nullable=False)

    readonly: bool = db.Column(db.Boolean(), nullable=True, default=False)

    allow_internet: bool = db.Column(db.Boolean(), nullable=True, default=False)

    instances: List[Instance] = db.relationship("InstanceService", backref="exercise_service", lazy=True, passive_deletes='all')

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

    id: int = db.Column(db.Integer, primary_key=True)

    #The services that defnies the entrypoint of this exercise
    entry_service: ExerciseEntryService = db.relationship("ExerciseEntryService", uselist=False, backref="exercise",  passive_deletes='all')

    #Additional services that are mapped into the network for this exercise.
    services: List[ExerciseService] = db.relationship('ExerciseService', backref='exercise', lazy=True, passive_deletes='all')

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

    description: str = db.Column(db.Text(), nullable=True)

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
    instances: List[Instance] = db.relationship('Instance', backref='exercise', lazy=True,  passive_deletes='all')

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

    def predecessor(self) -> Exercise:
        predecessors = self.predecessors()
        if predecessors:
            return predecessors[0]
        else:
            return None

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
        if for_update:
            q.with_for_update()
        return q.one_or_none()

    @staticmethod
    def get_exercise(short_name, version, for_update=False) -> Exercise:
        exercise = Exercise.query.filter(
            and_(
                Exercise.short_name == short_name,
                Exercise.version == version
                )
        )
        if for_update:
            exercise.with_for_update()
        return exercise.one_or_none()

    @staticmethod
    def get_exercises(short_name) -> List[Exercise]:
        exercises = Exercise.query.filter(
            Exercise.short_name == short_name
        )
        return exercises.all()

    def deadine_passed(self) -> bool:
        assert self.submission_deadline_end is not None
        return datetime.datetime.now() > self.submission_deadline_end

    def has_deadline(self) -> bool:
        return self.submission_deadline_end is not None

    def has_started(self) -> bool:
        return self.submission_deadline_start is None or datetime.datetime.now() > self.submission_deadline_start

    def submission_heads(self) -> List[Submission]:
        """
        Returns the most recent submission for this exercise for each user.
        Note: This function does not consider Submissions of other
        version of this exercise.
        """
        ret = []
        submissions_per_user = defaultdict(list)
        for instance in self.instances:
            if not instance.submission:
                continue
            submissions_per_user[instance.user] += [instance]
        for _, v in submissions_per_user.items():
            ret += [max(v, key=lambda e: e.creation_ts)]
        return [e.submission for e in ret if e.submission]

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

    def has_submissions(self) -> bool:
        return self.submissions()

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
        submissions = [e.grading for e in self.submission_heads() if e.grading]
        if not submissions:
            return None
        return sum([g.points_reached for g in submissions]) / len(submissions)
