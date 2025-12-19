"""
Integration Tests: Exercise Lifecycle

Tests exercise import, build, and enable by calling core methods via remote_exec.
Uses shared pre/post condition assertions from helpers/conditions.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable

import pytest

from helpers.conditions import ExerciseConditions
from helpers.method_exec import (
    build_exercise,
    delete_exercise,
    enable_exercise,
    import_exercise,
)

if TYPE_CHECKING:
    from helpers.ref_instance import REFInstance


class TestExerciseImport:
    """Tests for exercise import via direct method calls."""

    @pytest.mark.integration
    def test_import_exercise(
        self,
        ref_instance: "REFInstance",
        temp_exercise_dir: Path,
        unique_exercise_name: str,
        cleanup_exercise: Callable[[int], int],
    ):
        """
        Test importing an exercise via ExerciseManager.

        Pre-condition: Exercise does not exist
        Action: Import exercise from template
        Post-conditions:
            - Exercise exists in database
            - Build status is NOT_BUILD
            - Exercise is not enabled (is_default=False)
        """
        # Pre-condition
        ExerciseConditions.pre_exercise_not_exists(ref_instance, unique_exercise_name)

        # Action
        result = import_exercise(ref_instance, str(temp_exercise_dir))

        # Track for cleanup
        cleanup_exercise(result["id"])

        # Verify return value
        assert result["short_name"] == unique_exercise_name
        assert result["id"] is not None
        assert result["version"] == 1

        # Post-conditions (shared assertions)
        exercise_data = ExerciseConditions.post_exercise_imported(
            ref_instance, unique_exercise_name
        )
        assert exercise_data["category"] == "Integration Tests"

    @pytest.mark.integration
    def test_import_duplicate_exercise_fails(
        self,
        ref_instance: "REFInstance",
        temp_exercise_dir: Path,
        unique_exercise_name: str,
        cleanup_exercise: Callable[[int], int],
    ):
        """
        Test that importing the same exercise twice fails.
        """
        # Import first time
        result = import_exercise(ref_instance, str(temp_exercise_dir))
        cleanup_exercise(result["id"])

        # Try to import again - should fail
        with pytest.raises(Exception):
            import_exercise(ref_instance, str(temp_exercise_dir))


class TestExerciseBuild:
    """Tests for exercise build via direct method calls."""

    @pytest.mark.integration
    @pytest.mark.slow
    @pytest.mark.timeout(360)
    def test_build_exercise(
        self,
        ref_instance: "REFInstance",
        temp_exercise_dir: Path,
        unique_exercise_name: str,
        cleanup_exercise: Callable[[int], int],
    ):
        """
        Test building an exercise via ExerciseImageManager.

        Pre-condition: Exercise is imported but not built
        Action: Build exercise Docker image
        Post-condition: Build status is FINISHED
        """
        # Setup: Import exercise
        result = import_exercise(ref_instance, str(temp_exercise_dir))
        exercise_id = cleanup_exercise(result["id"])

        # Verify pre-condition (imported but not built)
        exercise_data = ExerciseConditions.post_exercise_imported(
            ref_instance, unique_exercise_name
        )
        assert exercise_data["build_job_status"] == "NOT_BUILD"

        # Action: Build exercise
        build_result = build_exercise(ref_instance, exercise_id, timeout=300.0)
        assert build_result is True

        # Post-condition
        ExerciseConditions.post_exercise_built(ref_instance, exercise_id)

    @pytest.mark.integration
    def test_build_nonexistent_exercise_fails(
        self,
        ref_instance: "REFInstance",
    ):
        """
        Test that building a nonexistent exercise returns False.
        """
        result = build_exercise(ref_instance, 999999)
        assert result is False


class TestExerciseEnable:
    """Tests for exercise enable/disable via direct method calls."""

    @pytest.mark.integration
    @pytest.mark.slow
    @pytest.mark.timeout(360)
    def test_enable_exercise(
        self,
        ref_instance: "REFInstance",
        temp_exercise_dir: Path,
        unique_exercise_name: str,
        cleanup_exercise: Callable[[int], int],
    ):
        """
        Test enabling an exercise.

        Pre-conditions:
            - Exercise is imported and built
            - Exercise is not enabled
        Action: Enable exercise
        Post-condition: Exercise is enabled (is_default=True)
        """
        # Setup: Import and build exercise
        result = import_exercise(ref_instance, str(temp_exercise_dir))
        exercise_id = cleanup_exercise(result["id"])
        build_exercise(ref_instance, exercise_id, timeout=300.0)

        # Verify not enabled
        exercise_data = ExerciseConditions.get_exercise_by_name(
            ref_instance, unique_exercise_name
        )
        assert exercise_data is not None
        assert exercise_data["is_default"] is False

        # Action: Enable exercise
        enable_result = enable_exercise(ref_instance, exercise_id)
        assert enable_result is True

        # Post-condition
        ExerciseConditions.post_exercise_enabled(ref_instance, exercise_id)

    @pytest.mark.integration
    def test_enable_nonexistent_exercise_fails(
        self,
        ref_instance: "REFInstance",
    ):
        """
        Test that enabling a nonexistent exercise returns False.
        """
        result = enable_exercise(ref_instance, 999999)
        assert result is False


class TestExerciseDelete:
    """Tests for exercise deletion."""

    @pytest.mark.integration
    def test_delete_exercise(
        self,
        ref_instance: "REFInstance",
        temp_exercise_dir: Path,
        unique_exercise_name: str,
    ):
        """
        Test deleting an exercise.

        Pre-condition: Exercise exists
        Action: Delete exercise
        Post-condition: Exercise no longer exists
        """
        # Setup: Import exercise
        result = import_exercise(ref_instance, str(temp_exercise_dir))
        exercise_id = result["id"]

        # Verify exercise exists
        exercise_data = ExerciseConditions.get_exercise_by_name(
            ref_instance, unique_exercise_name
        )
        assert exercise_data is not None

        # Action: Delete exercise
        delete_result = delete_exercise(ref_instance, exercise_id)
        assert delete_result is True

        # Post-condition: Exercise should no longer exist
        ExerciseConditions.pre_exercise_not_exists(ref_instance, unique_exercise_name)

    @pytest.mark.integration
    def test_delete_nonexistent_exercise(
        self,
        ref_instance: "REFInstance",
    ):
        """
        Test that deleting a nonexistent exercise returns False.
        """
        result = delete_exercise(ref_instance, 999999)
        assert result is False
