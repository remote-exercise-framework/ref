"""
Integration Test Configuration and Fixtures

These tests call webapp methods directly via remote_exec.
The ref_instance fixture from the root conftest.py is reused.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Generator

import pytest

if TYPE_CHECKING:
    from helpers.ref_instance import REFInstance


@pytest.fixture(scope="function")
def unique_mat_num() -> str:
    """Generate a unique matriculation number for each test."""
    return str(uuid.uuid4().int)[:8]


@pytest.fixture(scope="function")
def unique_exercise_name() -> str:
    """Generate a unique exercise name for each test."""
    return f"integ_test_{uuid.uuid4().hex[:6]}"


@pytest.fixture(scope="function")
def temp_exercise_dir(
    exercises_path: Path,
    unique_exercise_name: str,
) -> Generator[Path, None, None]:
    """
    Create a temporary exercise directory for testing.

    The directory is created before the test and cleaned up after.
    """
    import shutil

    from helpers.exercise_factory import create_sample_exercise

    exercise_dir = exercises_path / unique_exercise_name

    if exercise_dir.exists():
        shutil.rmtree(exercise_dir)

    create_sample_exercise(
        exercise_dir,
        short_name=unique_exercise_name,
        version=1,
        category="Integration Tests",
        has_deadline=True,
        has_submission_test=True,
        grading_points=10,
    )

    yield exercise_dir

    # Cleanup
    if exercise_dir.exists():
        shutil.rmtree(exercise_dir)


@pytest.fixture(scope="function")
def cleanup_user(ref_instance: "REFInstance"):
    """
    Factory fixture that tracks users to clean up after test.

    Usage:
        def test_something(cleanup_user):
            mat_num = "12345678"
            cleanup_user(mat_num)
            # ... create user with mat_num ...
            # User will be deleted after test
    """
    users_to_cleanup: list[str] = []

    def _track(mat_num: str) -> str:
        users_to_cleanup.append(mat_num)
        return mat_num

    yield _track

    # Cleanup users after test
    from helpers.method_exec import delete_user

    for mat_num in users_to_cleanup:
        try:
            delete_user(ref_instance, mat_num)
        except Exception:
            pass


@pytest.fixture(scope="function")
def cleanup_exercise(ref_instance: "REFInstance"):
    """
    Factory fixture that tracks exercises to clean up after test.

    Usage:
        def test_something(cleanup_exercise):
            exercise_id = 123
            cleanup_exercise(exercise_id)
            # ... work with exercise ...
            # Exercise will be deleted after test
    """
    exercises_to_cleanup: list[int] = []

    def _track(exercise_id: int) -> int:
        exercises_to_cleanup.append(exercise_id)
        return exercise_id

    yield _track

    # Cleanup exercises after test
    from helpers.method_exec import delete_exercise

    for exercise_id in exercises_to_cleanup:
        try:
            delete_exercise(ref_instance, exercise_id)
        except Exception:
            pass
