from __future__ import annotations

import datetime
from collections import defaultdict
from typing import TYPE_CHECKING, List, Optional

from flask import current_app
from sqlalchemy import ForeignKey, PickleType, Text, and_
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ref import db

from .enums import ExerciseBuildStatus
from .exercise_config import ExerciseConfig
from .util import CommonDbOpsMixin, ModelToStringMixin

if TYPE_CHECKING:
    from .instance import Instance, InstanceService, Submission


class ConfigParsingError(Exception):
    def __init__(self, msg: str, path: Optional[str] = None):
        if path:
            msg = f"{msg} ({path})"
        super().__init__(msg)


class RessourceLimits(CommonDbOpsMixin, ModelToStringMixin, db.Model):
    __to_str_fields__ = [
        "id",
        "cpu_cnt_max",
        "cpu_shares",
        "pids_max",
        "memory_in_mb",
        "memory_swap_in_mb",
        "memory_kernel_in_mb",
    ]
    __tablename__ = "exercise_ressource_limits"

    id: Mapped[int] = mapped_column(primary_key=True)

    cpu_cnt_max: Mapped[Optional[float]] = mapped_column(default=None)
    cpu_shares: Mapped[Optional[int]] = mapped_column(default=None)

    pids_max: Mapped[Optional[int]] = mapped_column(default=None)

    memory_in_mb: Mapped[Optional[int]] = mapped_column(default=None)
    memory_swap_in_mb: Mapped[Optional[int]] = mapped_column(default=None)
    memory_kernel_in_mb: Mapped[Optional[int]] = mapped_column(default=None)


class ExerciseEntryService(CommonDbOpsMixin, ModelToStringMixin, db.Model):
    """
    Each Exercise must have exactly one ExerciseEntryService that represtens the service
    that serves as entry point for it.
    """

    __to_str_fields__ = ["id", "exercise_id"]
    __tablename__ = "exercise_entry_service"

    id: Mapped[int] = mapped_column(primary_key=True)

    # The exercise this entry service belongs to
    exercise_id: Mapped[int] = mapped_column(
        ForeignKey("exercise.id", ondelete="RESTRICT")
    )
    exercise: Mapped["Exercise"] = relationship(
        "Exercise", foreign_keys=[exercise_id], back_populates="entry_service"
    )

    # Path inside the container that is persistet
    persistance_container_path: Mapped[Optional[str]] = mapped_column(Text)

    files: Mapped[Optional[List[str]]] = mapped_column(PickleType)

    # List of commands that are executed when building the service's Docker image.
    build_cmd: Mapped[Optional[List[str]]] = mapped_column(PickleType)

    no_randomize_files: Mapped[Optional[List[str]]] = mapped_column(PickleType)

    disable_aslr: Mapped[bool]

    # Command that is executed as soon a user connects (list)
    cmd: Mapped[List[str]] = mapped_column(PickleType)

    readonly: Mapped[bool] = mapped_column(default=False)

    allow_internet: Mapped[bool] = mapped_column(default=False)

    # options for the flag that is placed inside the container
    flag_path: Mapped[Optional[str]] = mapped_column(Text)
    flag_value: Mapped[Optional[str]] = mapped_column(Text)
    flag_user: Mapped[Optional[str]] = mapped_column(Text)
    flag_group: Mapped[Optional[str]] = mapped_column(Text)
    flag_permission: Mapped[Optional[str]] = mapped_column(Text)

    ressource_limit_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("exercise_ressource_limits.id", ondelete="RESTRICT")
    )
    ressource_limit: Mapped[Optional[RessourceLimits]] = relationship(
        "RessourceLimits", foreign_keys=[ressource_limit_id]
    )

    @property
    def persistance_lower(self) -> str:
        """
        Path to the local directory that contains the data located at persistance_container_path
        in the exercise image.
        """
        return self.exercise.persistence_path + "/entry-server/lower"

    @property
    def image_name(self) -> str:
        """
        Name of the docker image that was build based on this configuration.
        """
        return f"{current_app.config['DOCKER_RESSOURCE_PREFIX']}{self.exercise.short_name}-entry:v{self.exercise.version}"


class ExerciseService(CommonDbOpsMixin, ModelToStringMixin, db.Model):
    """
    A ExerciseService describes a service that runs in the same network as
    the ExerciseEntryService. A usecase for an ExerciseService might be
    the implementation of a networked service that must be hacked by a user.
    """

    __to_str_fields__ = ["id", "exercise_id"]
    __tablename__ = "exercise_service"

    id: Mapped[int] = mapped_column(primary_key=True)

    name: Mapped[Optional[str]] = mapped_column(Text)

    # Backref is exercise
    exercise_id: Mapped[int] = mapped_column(
        ForeignKey("exercise.id", ondelete="RESTRICT")
    )
    exercise: Mapped["Exercise"] = relationship(
        "Exercise", foreign_keys=[exercise_id], back_populates="services"
    )

    files: Mapped[Optional[List[str]]] = mapped_column(PickleType)
    build_cmd: Mapped[Optional[List[str]]] = mapped_column(PickleType)

    disable_aslr: Mapped[bool]
    cmd: Mapped[List[str]] = mapped_column(PickleType)

    readonly: Mapped[Optional[bool]] = mapped_column(default=False)

    allow_internet: Mapped[Optional[bool]] = mapped_column(default=False)

    instances: Mapped[List["InstanceService"]] = relationship(
        "InstanceService",
        back_populates="exercise_service",
        lazy=True,
        passive_deletes="all",
    )

    flag_path: Mapped[Optional[str]] = mapped_column(Text)
    flag_value: Mapped[Optional[str]] = mapped_column(Text)
    flag_user: Mapped[Optional[str]] = mapped_column(Text)
    flag_group: Mapped[Optional[str]] = mapped_column(Text)
    flag_permission: Mapped[Optional[str]] = mapped_column(Text)

    @property
    def image_name(self) -> str:
        """
        Name of the docker image that was build based on this configuration.
        """
        return f"{current_app.config['DOCKER_RESSOURCE_PREFIX']}{self.exercise.short_name}-{self.name}:v{self.exercise.version}"


class Exercise(CommonDbOpsMixin, ModelToStringMixin, db.Model):
    """
    An Exercise is a description of a task that can be deployed for a user.
    A single exercise consists of at least one ExerciseService.
    In order to make a exercise available to a student, an ExerciseInstance must be
    created.
    """

    __to_str_fields__ = ["id", "short_name", "version", "category", "build_job_status"]
    __tablename__ = "exercise"

    id: Mapped[int] = mapped_column(primary_key=True)

    # The services that defines the entrypoint of this exercise
    entry_service: Mapped[Optional[ExerciseEntryService]] = relationship(
        "ExerciseEntryService",
        uselist=False,
        back_populates="exercise",
        passive_deletes="all",
    )

    # Additional services that are mapped into the network for this exercise.
    services: Mapped[List[ExerciseService]] = relationship(
        "ExerciseService", back_populates="exercise", lazy=True, passive_deletes="all"
    )

    # Folder the template was initially imported from
    template_import_path: Mapped[str] = mapped_column(Text)

    # Folder where a copy of the template is stored for persisting it after import
    template_path: Mapped[str] = mapped_column(Text, unique=True)

    # Path to the folder that contains all persisted data of this exercise.
    persistence_path: Mapped[str] = mapped_column(Text, unique=True)

    # Name that identifies the exercise. Denormalized from ExerciseConfig for
    # use in SQLAlchemy queries, Docker resource naming, and SSH routing.
    # Must be kept in sync with ExerciseConfig.short_name on rename.
    short_name: Mapped[str] = mapped_column(Text)

    # Version of the exercise used for updating mechanism.
    version: Mapped[int]

    # FK to shared administrative config (category, deadlines, grading, scoring)
    config_id: Mapped[int] = mapped_column(
        ForeignKey("exercise_config.id"), nullable=False
    )
    config: Mapped[ExerciseConfig] = relationship(
        "ExerciseConfig", foreign_keys=[config_id]
    )

    # Is this Exercise version deployed by default in case an instance is requested?
    # At most one exercise with same short_name can have this flag.
    is_default: Mapped[bool]

    # Log of the last build run
    build_job_result: Mapped[Optional[str]] = mapped_column(Text)

    # Build status of the docker images that belong to the exercise
    build_job_status: Mapped[ExerciseBuildStatus]

    # All running instances of this exercise
    instances: Mapped[List["Instance"]] = relationship(
        "Instance", back_populates="exercise", lazy=True, passive_deletes="all"
    )

    def get_users_instance(self, user) -> List["Instance"]:
        for instance in self.instances:
            if instance.user == user:
                return instance
        return None

    def predecessors(self) -> List[Exercise]:
        exercises = (
            Exercise.query.filter(
                and_(
                    Exercise.short_name == self.short_name,
                    Exercise.version < self.version,
                )
            )
            .order_by(Exercise.version.desc())
            .all()
        )
        return exercises

    def is_update(self) -> bool:
        return len(self.predecessors()) > 0

    def predecessor(self) -> Optional[Exercise]:
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
        exercises = (
            Exercise.query.filter(
                and_(
                    Exercise.short_name == self.short_name,
                    Exercise.version > self.version,
                )
            )
            .order_by(Exercise.version)
            .all()
        )
        return exercises

    def successor(self) -> Optional[Exercise]:
        successors = self.successors()
        if successors:
            return successors[0]
        else:
            return None

    def head(self) -> Optional[Exercise]:
        """
        Returns the newest version of this exercise.
        """
        ret = self.successors() + [self]
        return max(ret, key=lambda e: e.version, default=None)

    def tail(self) -> Optional[Exercise]:
        """
        Returns the oldest version of this exercise.
        """
        ret = self.predecessors() + [self]
        return min(ret, key=lambda e: e.version, default=None)

    @staticmethod
    def get_default_exercise(short_name, for_update=False) -> Optional[Exercise]:
        """
        Returns and locks the default exercise for the given short_name.
        """
        q = Exercise.query.filter(Exercise.short_name == short_name).filter(
            Exercise.is_default == True  # noqa: E712
        )
        return q.one_or_none()

    @staticmethod
    def get_exercise(short_name, version, for_update=False) -> Optional[Exercise]:
        exercise = Exercise.query.filter(
            and_(Exercise.short_name == short_name, Exercise.version == version)
        )
        return exercise.one_or_none()

    @staticmethod
    def get_exercises(short_name) -> List[Exercise]:
        exercises = Exercise.query.filter(Exercise.short_name == short_name)
        return exercises.all()

    # --- Proxy properties delegating to ExerciseConfig ---

    @property
    def category(self) -> Optional[str]:
        return self.config.category

    @property
    def submission_deadline_start(self) -> Optional[datetime.datetime]:
        return self.config.submission_deadline_start

    @property
    def submission_deadline_end(self) -> Optional[datetime.datetime]:
        return self.config.submission_deadline_end

    @property
    def submission_test_enabled(self) -> bool:
        return self.config.submission_test_enabled

    @property
    def max_grading_points(self) -> Optional[int]:
        return self.config.max_grading_points

    # --- Deadline helpers (delegate to config) ---

    def deadine_passed(self) -> bool:
        assert self.has_deadline(), "Exercise does not have a deadline"
        return datetime.datetime.now() > self.submission_deadline_end

    def has_deadline(self) -> bool:
        return self.submission_deadline_end is not None

    def has_started(self) -> bool:
        return (
            self.submission_deadline_start is None
            or datetime.datetime.now() > self.submission_deadline_start
        )

    def submission_heads(self) -> List["Submission"]:
        """
        Returns the most recent submission for this exercise for each user.
        Note: This function does not consider Submissions of other
        version of this exercise. Hence, the returned submissions might
        not be the most recent ones for an specific instance.
        """
        from .instance import Instance

        most_recent_instances = []
        instances_per_user = defaultdict(list)
        instances = Instance.query.filter(
            Instance.exercise == self,
            Instance.submission != None,  # noqa: E711
        ).all()

        for instance in instances:
            instances_per_user[instance.user] += [instance]
        for _, instances in instances_per_user.items():
            most_recent_instances += [max(instances, key=lambda e: e.creation_ts)]
        return [e.submission for e in most_recent_instances if e.submission]

    def submission_heads_global(self) -> List["Submission"]:
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

    @staticmethod
    def _group_key(user) -> tuple:
        """Return a unique bucket key for a user: the group id if set,
        otherwise a per-user sentinel so ungrouped users stay in their own
        bucket."""
        if user.group_id is not None:
            return ("g", user.group_id)
        return ("u", user.id)

    def submission_heads_by_group(self) -> List["Submission"]:
        """
        Returns the most recent submission for this exercise for each
        user-group. Users without a group each form their own bucket.
        Does not consider submissions from other exercise versions.
        """
        from .instance import Instance

        instances_per_group = defaultdict(list)
        instances = Instance.query.filter(
            Instance.exercise == self,
            Instance.submission != None,  # noqa: E711
        ).all()

        for instance in instances:
            instances_per_group[Exercise._group_key(instance.user)] += [instance]

        most_recent_instances = []
        for _, group_instances in instances_per_group.items():
            most_recent_instances += [max(group_instances, key=lambda e: e.creation_ts)]
        return [e.submission for e in most_recent_instances if e.submission]

    def submission_heads_by_group_global(self) -> List["Submission"]:
        """
        Same as submission_heads_by_group(), except only submissions that have
        no newer submission (from a more recent exercise version) by the same
        group are returned.
        """
        submissions = []
        own_submissions = self.submission_heads_by_group()
        for exercise in [self] + self.successors():
            submissions += exercise.submission_heads_by_group()

        seen_groups = set()
        ret = []

        for submission in submissions[::-1]:
            key = Exercise._group_key(submission.submitted_instance.user)
            if key in seen_groups:
                continue
            seen_groups.add(key)
            if submission in own_submissions:
                ret += [submission]

        return ret

    @property
    def active_instances(self) -> List["Instance"]:
        """
        Get all instances of this exercise that are no submissions.
        Note: This function does not returns Instances that belong to
        another version of this exercise.
        """
        return [i for i in self.instances if not i.submission]

    def submissions(self, user=None) -> List["Submission"]:
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

    def avg_points(self) -> Optional[float]:
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
