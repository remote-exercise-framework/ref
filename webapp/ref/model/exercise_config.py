from __future__ import annotations

import datetime
from typing import Optional

from sqlalchemy import JSON, Text
from sqlalchemy.orm import Mapped, mapped_column

from ref import db

from .util import CommonDbOpsMixin, ModelToStringMixin


class ExerciseConfig(CommonDbOpsMixin, ModelToStringMixin, db.Model):
    """
    Holds administrative configuration shared across all versions of an exercise.
    Each exercise (identified by short_name) has exactly one ExerciseConfig.
    Fields here are editable via the web interface and are not tied to
    a specific exercise version or Docker image build.
    """

    __to_str_fields__ = ["id", "short_name", "category"]
    __tablename__ = "exercise_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    short_name: Mapped[str] = mapped_column(Text, unique=True)

    # Used to group exercises (e.g., assignment name for scoreboard)
    category: Mapped[Optional[str]] = mapped_column(Text)

    submission_deadline_start: Mapped[Optional[datetime.datetime]]
    submission_deadline_end: Mapped[Optional[datetime.datetime]]

    submission_test_enabled: Mapped[bool] = mapped_column(default=False)

    # Max points a user can get for this exercise. Might be None.
    max_grading_points: Mapped[Optional[int]]

    # Per-task scoring policies keyed by task_name, as discovered from the
    # exercise's submission_tests file. Tasks without an entry score as
    # pass-through (raw score). Each value has the same shape as the
    # legacy single-policy dict: {"mode": ..., "max_points": ..., ...}.
    per_task_scoring_policies: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True
    )

    def has_deadline(self) -> bool:
        return self.submission_deadline_end is not None

    def deadline_passed(self) -> bool:
        assert self.has_deadline(), "Exercise config does not have a deadline"
        return datetime.datetime.now() > self.submission_deadline_end

    def has_started(self) -> bool:
        return (
            self.submission_deadline_start is None
            or datetime.datetime.now() > self.submission_deadline_start
        )
