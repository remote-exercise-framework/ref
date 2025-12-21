import datetime
import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

from flask import current_app
from sqlalchemy import ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ref import db

from .user import User
from .util import CommonDbOpsMixin, ModelToStringMixin

# Avoid cyclic dependencies for type hinting
if TYPE_CHECKING:
    from .exercise import Exercise, ExerciseService


class InstanceService(CommonDbOpsMixin, ModelToStringMixin, db.Model):
    """
    An InstanceService is an instance of a ExerciseService and its functionality
    is entirely defined by an ExerciseService (.exercise_service).
    Each InstanceService belongs to an Instance and is responsible to keep
    runtime information of the service it is impelmenting.
    """

    __to_str_fields__ = ["id", "instance_id", "exercise_service_id", "container_id"]
    __tablename__ = "instance_service"

    # 1. Each instance only uses a specific service once.
    __table_args__ = (UniqueConstraint("instance_id", "exercise_service_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)

    # The exercise service describing this service (backref is exercise_service)
    exercise_service_id: Mapped[int] = mapped_column(
        ForeignKey("exercise_service.id", ondelete="RESTRICT")
    )
    exercise_service: Mapped["ExerciseService"] = relationship(
        "ExerciseService",
        foreign_keys=[exercise_service_id],
        back_populates="instances",
    )

    # The instance this service belongs to.
    instance_id: Mapped[int] = mapped_column(
        ForeignKey("exercise_instance.id", ondelete="RESTRICT")
    )
    instance: Mapped["Instance"] = relationship(
        "Instance", foreign_keys=[instance_id], back_populates="peripheral_services"
    )

    # The docker container id of this service.
    container_id: Mapped[Optional[str]] = mapped_column(Text, unique=True)

    @property
    def hostname(self):
        return self.exercise_service.name


class InstanceEntryService(CommonDbOpsMixin, ModelToStringMixin, db.Model):
    """
    An InstanceEntryService is an instance of an ExerciseEntryService and
    serves as the entrypoint for a user.
    Such an InstanceEntryService is exposed via SSH and supports data persistance.
    """

    __to_str_fields__ = ["id", "instance_id", "container_id"]
    __tablename__ = "exercise_instance_entry_service"

    id: Mapped[int] = mapped_column(primary_key=True)

    # The instance this entry service belongs to
    instance_id: Mapped[int] = mapped_column(
        ForeignKey("exercise_instance.id", ondelete="RESTRICT")
    )
    instance: Mapped["Instance"] = relationship(
        "Instance", foreign_keys=[instance_id], back_populates="entry_service"
    )

    # ID of the docker container.
    container_id: Mapped[Optional[str]] = mapped_column(Text, unique=True)

    @property
    def overlay_submitted(self) -> str:
        """
        Directory that is used as lower dir besides the "base" files of the exercise.
        This directory can be used to store submitted files.
        """
        return f"{self.instance.persistance_path}/entry-submitted"

    @property
    def overlay_upper(self) -> str:
        """
        Path to the directory that contains the persisted user data.
        This directory is used as the 'upper' directory for overlayfs.
        """
        return f"{self.instance.persistance_path}/entry-upper"

    @property
    def overlay_work(self) -> str:
        """
        Path to the working directory used by overlayfs for persistance.
        """
        return f"{self.instance.persistance_path}/entry-work"

    @property
    def overlay_merged(self) -> str:
        """
        Path to the directory that contains the merged content of the upper, submitted, and lower directory.
        """
        return f"{self.instance.persistance_path}/entry-merged"

    @property
    def hostname(self):
        return self.instance.exercise.short_name

    """
    A folder that is mounted into the instance and can be used to transfer data
    between the host and the instance.
    """

    @property
    def shared_folder(self):
        return f"{self.instance.persistance_path}/shared-folder"


class Instance(CommonDbOpsMixin, ModelToStringMixin, db.Model):
    """
    An Instance represents a instance of an exercise.
    Such an instance is bound to a single user.
    """

    __to_str_fields__ = [
        "id",
        "exercise",
        "entry_service",
        "user",
        "network_id",
        "peripheral_services_internet_network_id",
        "peripheral_services_network_id",
    ]
    __tablename__ = "exercise_instance"

    id: Mapped[int] = mapped_column(primary_key=True)

    entry_service: Mapped[Optional[InstanceEntryService]] = relationship(
        "InstanceEntryService",
        uselist=False,
        back_populates="instance",
        passive_deletes="all",
    )
    peripheral_services: Mapped[List[InstanceService]] = relationship(
        "InstanceService", back_populates="instance", lazy=True, passive_deletes="all"
    )

    # The network the entry service is connected to the ssh server by
    network_id: Mapped[Optional[str]] = mapped_column(Text, unique=True)

    # Network the entry service is connected to the peripheral services
    peripheral_services_internet_network_id: Mapped[Optional[str]] = mapped_column(
        Text, unique=True
    )
    peripheral_services_network_id: Mapped[Optional[str]] = mapped_column(
        Text, unique=True
    )

    # Exercise this instance belongs to (backref name is exercise)
    exercise_id: Mapped[int] = mapped_column(
        ForeignKey("exercise.id", ondelete="RESTRICT")
    )
    exercise: Mapped["Exercise"] = relationship(
        "Exercise", foreign_keys=[exercise_id], back_populates="instances"
    )

    # Student this instance belongs to (backref name is user)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="RESTRICT"))
    user: Mapped["User"] = relationship(
        "User", foreign_keys=[user_id], back_populates="exercise_instances"
    )

    creation_ts: Mapped[Optional[datetime.datetime]]

    # All submission of this instance. If this list is empty, the instance was never submitted.
    submissions: Mapped[List["Submission"]] = relationship(
        "Submission",
        foreign_keys="Submission.origin_instance_id",
        lazy="joined",
        back_populates="origin_instance",
        passive_deletes="all",
    )

    # If this instance is part of a subission, this field points to the Submission. If this field is set, submissions must be empty.
    submission: Mapped[Optional["Submission"]] = relationship(
        "Submission",
        foreign_keys="Submission.submitted_instance_id",
        uselist=False,
        back_populates="submitted_instance",
        lazy="joined",
        passive_deletes="all",
    )

    def get_latest_submission(self) -> Optional["Submission"]:
        assert not self.submission
        if not self.submissions:
            return None
        return max(self.submissions, key=lambda e: e.submission_ts)

    def get_key(self) -> bytes:
        secret_key = current_app.config["SECRET_KEY"]
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
        return f"{self.exercise.short_name}-v{self.exercise.version}"

    @property
    def persistance_path(self) -> str:
        """
        Path used to store all data that belongs to this instance.
        """
        # Make sure there is a PK by flushing pending DB ops
        current_app.db.session.flush(objects=[self])
        assert self.id is not None
        return self.exercise.persistence_path + f"/instances/{self.id}"

    @staticmethod
    def get_instances_by_exercise(short_name, version=None) -> List["Instance"]:
        instances = Instance.query.all()
        ret = []
        for i in instances:
            if i.exercise.short_name == short_name and (
                version is None or i.exercise.version == version
            ):
                ret.append(i)
        return ret

    @staticmethod
    def get_by_user(user_id) -> List["Instance"]:
        ret = []
        instances = Instance.all()
        for i in instances:
            if i.user.id == user_id:
                ret.append(i)
        return ret

    def is_modified(self) -> bool:
        upper_dir = Path(self.entry_service.overlay_upper)
        modified_files = set()
        for path in upper_dir.glob("*"):
            if path.parts[-1] in [".ssh", ".bash_history", ".mypy_cache"]:
                continue
            modified_files.add(path)
        current_app.logger.info(
            f"Instance {self} has following modified files {modified_files}"
        )
        return len(modified_files) != 0

    def is_submission(self) -> bool:
        return self.submission is not None


class SubmissionTestResult(CommonDbOpsMixin, ModelToStringMixin, db.Model):
    __to_str_fields__ = ["id"]
    __tablename__ = "submission_test_result"

    id: Mapped[int] = mapped_column(primary_key=True)

    # The name of the task this results belongs to.
    task_name: Mapped[str] = mapped_column(Text)
    # The output of the test.
    output: Mapped[str] = mapped_column(Text)
    # Whether the test was successfull.
    success: Mapped[bool]

    # If the task supports grading, this is the score that was reached.
    score: Mapped[Optional[float]]

    # ondelete='CASCADE' => Delete result if associated submission is deleted (realized via db-constraint)
    submission_id: Mapped[int] = mapped_column(
        ForeignKey("submission.id", ondelete="CASCADE")
    )
    submission: Mapped["Submission"] = relationship(
        "Submission",
        foreign_keys=[submission_id],
        back_populates="submission_test_results",
    )

    def __init__(
        self, task_name: str, output: str, success: bool, score: Optional[float]
    ) -> None:
        super().__init__()
        self.task_name = task_name
        self.output = output
        self.success = success
        self.score = score


class SubmissionExtendedTestResult(CommonDbOpsMixin, ModelToStringMixin, db.Model):
    __to_str_fields__ = ["id"]
    __tablename__ = "submission_extended_test_result"

    id: Mapped[int] = mapped_column(primary_key=True)

    # The name of the task this results belongs to.
    task_name: Mapped[str] = mapped_column(Text)
    # The output of the test.
    output: Mapped[str] = mapped_column(Text)
    # Whether the test was successfull.
    success: Mapped[bool]

    # If the task supports grading, this is the score that was reached.
    score: Mapped[Optional[float]]

    # ondelete='CASCADE' => Delete result if associated submission is deleted (realized via db-constraint)
    submission_id: Mapped[int] = mapped_column(
        ForeignKey("submission.id", ondelete="CASCADE")
    )
    submission: Mapped["Submission"] = relationship(
        "Submission",
        foreign_keys=[submission_id],
        back_populates="extended_submission_test_results",
    )


class Submission(CommonDbOpsMixin, ModelToStringMixin, db.Model):
    """
    A submission represents a specific state of an instance at one point in time (snapshot).
    """

    __to_str_fields__ = ["id", "origin_instance_id", "submitted_instance_id"]
    __tablename__ = "submission"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Reference to the Instance that was submitted. Hence, submitted_instance is a snapshot of origin_instance.
    origin_instance_id: Mapped[int] = mapped_column(
        ForeignKey("exercise_instance.id", ondelete="RESTRICT")
    )
    origin_instance: Mapped[Instance] = relationship(
        "Instance", foreign_keys=[origin_instance_id], back_populates="submissions"
    )

    # Reference to the Instance that represents the state of origin_instance at the time the submission was created.
    # This instance uses the changed data (upper overlay) of the submitted instance as lower layer of its overlayfs.
    submitted_instance_id: Mapped[int] = mapped_column(
        ForeignKey("exercise_instance.id", ondelete="RESTRICT")
    )
    submitted_instance: Mapped[Instance] = relationship(
        "Instance", foreign_keys=[submitted_instance_id], back_populates="submission"
    )

    # Point in time the submission was created.
    submission_ts: Mapped[datetime.datetime]

    # Set if this Submission was graded
    # ondelete='RESTRICT' => restrict deletetion of referenced row if it is still referenced from here.
    grading_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("grading.id", ondelete="RESTRICT")
    )
    grading: Mapped[Optional["Grading"]] = relationship(
        "Grading", foreign_keys=[grading_id], back_populates="submission"
    )

    # passive_deletes=True => actual delete is performed by database constraint (ForeignKey ondelete='CASCADE')
    submission_test_results: Mapped[List[SubmissionTestResult]] = relationship(
        "SubmissionTestResult",
        back_populates="submission",
        lazy=True,
        cascade="all",
        passive_deletes=True,
    )
    extended_submission_test_results: Mapped[List[SubmissionExtendedTestResult]] = (
        relationship(
            "SubmissionExtendedTestResult",
            back_populates="submission",
            lazy=True,
            cascade="all",
            passive_deletes=True,
        )
    )

    def is_graded(self) -> bool:
        return self.grading_id is not None

    def is_modified(self) -> bool:
        return self.submitted_instance.is_modified()

    def successors(self) -> List["Submission"]:
        """
        Get all Submissions that belong to the same origin and have higher
        (where created later) creation timestamp then this Submission.
        """
        submissions = self.origin_instance.submissions
        return [s for s in submissions if s.submission_ts > self.submission_ts]


class Grading(CommonDbOpsMixin, ModelToStringMixin, db.Model):
    __to_str_fields__ = ["id"]
    __tablename__ = "grading"

    id: Mapped[int] = mapped_column(primary_key=True)

    # The graded submission
    submission: Mapped[Optional[Submission]] = relationship(
        "Submission",
        foreign_keys="Submission.grading_id",
        uselist=False,
        back_populates="grading",
        passive_deletes="all",
    )

    points_reached: Mapped[int]
    comment: Mapped[Optional[str]] = mapped_column(Text)

    # Not that is never shown to the user
    private_note: Mapped[Optional[str]] = mapped_column(Text)

    # Reference to the last user that applied changes
    last_edited_by_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    last_edited_by: Mapped[User] = relationship(
        "User", foreign_keys=[last_edited_by_id]
    )
    update_ts: Mapped[datetime.datetime]

    # Reference to the user that created this submission
    created_by_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    created_by: Mapped[User] = relationship("User", foreign_keys=[created_by_id])
    created_ts: Mapped[datetime.datetime]
