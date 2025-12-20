"""
Integration Tests: Submission Workflow

Tests instance creation and submission by calling core methods via remote_exec.
Uses shared pre/post condition assertions from helpers/conditions.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Generator

import pytest

from helpers.conditions import (
    InstanceConditions,
    SubmissionConditions,
)
from helpers.method_exec import (
    build_exercise,
    create_instance,
    create_submission,
    create_user,
    delete_user,
    enable_exercise,
    import_exercise,
    remove_instance,
    stop_instance,
)

if TYPE_CHECKING:
    from helpers.ref_instance import REFInstance


@pytest.fixture(scope="module")
def built_exercise(
    ref_instance: "REFInstance",
    exercises_path: Path,
) -> Generator[dict[str, Any], None, None]:
    """
    Module-scoped fixture that provides a built and enabled exercise.

    This is expensive (building takes time), so we share it across tests.
    """
    import shutil
    import uuid

    from helpers.exercise_factory import create_sample_exercise

    exercise_name = f"submission_test_{uuid.uuid4().hex[:6]}"
    exercise_dir = exercises_path / exercise_name

    if exercise_dir.exists():
        shutil.rmtree(exercise_dir)

    create_sample_exercise(
        exercise_dir,
        short_name=exercise_name,
        version=1,
        category="Submission Tests",
        has_deadline=True,
        has_submission_test=True,
        grading_points=10,
    )

    # Import exercise
    result = import_exercise(ref_instance, str(exercise_dir))
    exercise_id = result["id"]

    # Build exercise
    build_exercise(ref_instance, exercise_id, timeout=300.0)

    # Enable exercise
    enable_exercise(ref_instance, exercise_id)

    yield {
        "id": exercise_id,
        "short_name": exercise_name,
        "path": exercise_dir,
    }

    # Cleanup
    if exercise_dir.exists():
        shutil.rmtree(exercise_dir)


class TestInstanceCreation:
    """Tests for instance creation via direct method calls."""

    @pytest.mark.integration
    @pytest.mark.slow
    @pytest.mark.timeout(120)
    def test_create_instance(
        self,
        ref_instance: "REFInstance",
        built_exercise: dict[str, Any],
        unique_mat_num: str,
    ):
        """
        Test creating an instance via InstanceManager.

        Pre-condition: No instance exists for user/exercise
        Action: Create instance
        Post-condition: Instance exists with network_id
        """
        exercise_name = built_exercise["short_name"]

        # Create user for this test
        user_result = create_user(
            ref_instance,
            mat_num=unique_mat_num,
            first_name="Instance",
            surname="Test",
            password="TestPassword123!",
        )

        result: dict[str, object] | None = None
        try:
            # Pre-condition
            InstanceConditions.pre_no_instance(
                ref_instance, unique_mat_num, exercise_name
            )

            # Action: Create instance (but don't start it yet)
            result = create_instance(
                ref_instance,
                mat_num=unique_mat_num,
                exercise_short_name=exercise_name,
                start=False,
            )

            # Verify return value
            assert result["id"] is not None
            assert result["user_id"] == user_result["id"]

        finally:
            # Cleanup
            if result is not None and "id" in result:
                try:
                    instance_id = result["id"]
                    assert isinstance(instance_id, int)
                    remove_instance(ref_instance, instance_id)
                except Exception:
                    pass
            delete_user(ref_instance, unique_mat_num)

    @pytest.mark.integration
    @pytest.mark.slow
    @pytest.mark.timeout(180)
    def test_create_and_start_instance(
        self,
        ref_instance: "REFInstance",
        built_exercise: dict[str, Any],
        unique_mat_num: str,
    ):
        """
        Test creating and starting an instance.

        Pre-condition: No instance exists for user/exercise
        Action: Create and start instance
        Post-conditions:
            - Instance exists with network_id
            - Instance has entry service
        """
        exercise_name = built_exercise["short_name"]
        instance_id = None

        # Create user for this test
        create_user(
            ref_instance,
            mat_num=unique_mat_num,
            first_name="StartInstance",
            surname="Test",
            password="TestPassword123!",
        )

        try:
            # Pre-condition
            InstanceConditions.pre_no_instance(
                ref_instance, unique_mat_num, exercise_name
            )

            # Action: Create and start instance
            result = create_instance(
                ref_instance,
                mat_num=unique_mat_num,
                exercise_short_name=exercise_name,
                start=True,
                timeout=120.0,
            )
            instance_id = result["id"]

            # Post-condition
            instance_data = InstanceConditions.post_instance_created(
                ref_instance, unique_mat_num, exercise_name
            )
            assert instance_data["network_id"] is not None
            assert instance_data["has_entry_service"] is True

        finally:
            # Cleanup
            if instance_id is not None:
                try:
                    stop_instance(ref_instance, instance_id)
                    remove_instance(ref_instance, instance_id)
                except Exception:
                    pass
            delete_user(ref_instance, unique_mat_num)


class TestInstanceIsolation:
    """Tests for instance isolation between users."""

    @pytest.mark.integration
    @pytest.mark.slow
    @pytest.mark.timeout(300)
    def test_instances_are_isolated(
        self,
        ref_instance: "REFInstance",
        built_exercise: dict[str, Any],
    ):
        """
        Test that two users get separate, isolated instances.

        Pre-condition: No instances exist for either user
        Action: Create instances for both users
        Post-condition: Instances have different IDs and network IDs
        """
        import uuid

        exercise_name = built_exercise["short_name"]

        mat_num1 = str(uuid.uuid4().int)[:8]
        mat_num2 = str(uuid.uuid4().int)[:8]
        instance1_id = None
        instance2_id = None

        # Create users
        create_user(
            ref_instance,
            mat_num=mat_num1,
            first_name="User",
            surname="One",
            password="TestPassword123!",
        )
        create_user(
            ref_instance,
            mat_num=mat_num2,
            first_name="User",
            surname="Two",
            password="TestPassword123!",
        )

        try:
            # Pre-conditions
            InstanceConditions.pre_no_instance(ref_instance, mat_num1, exercise_name)
            InstanceConditions.pre_no_instance(ref_instance, mat_num2, exercise_name)

            # Action: Create instances for both users
            result1 = create_instance(
                ref_instance,
                mat_num=mat_num1,
                exercise_short_name=exercise_name,
                start=True,
                timeout=120.0,
            )
            instance1_id = result1["id"]

            result2 = create_instance(
                ref_instance,
                mat_num=mat_num2,
                exercise_short_name=exercise_name,
                start=True,
                timeout=120.0,
            )
            instance2_id = result2["id"]

            # Post-condition: Instances are isolated
            InstanceConditions.post_instances_isolated(
                ref_instance, mat_num1, mat_num2, exercise_name
            )

        finally:
            # Cleanup
            for inst_id in [instance1_id, instance2_id]:
                if inst_id is not None:
                    try:
                        stop_instance(ref_instance, inst_id)
                        remove_instance(ref_instance, inst_id)
                    except Exception:
                        pass
            for mat_num in [mat_num1, mat_num2]:
                try:
                    delete_user(ref_instance, mat_num)
                except Exception:
                    pass


class TestSubmissionCreation:
    """Tests for submission creation via direct method calls."""

    @pytest.mark.integration
    @pytest.mark.slow
    @pytest.mark.timeout(180)
    def test_create_submission(
        self,
        ref_instance: "REFInstance",
        built_exercise: dict[str, Any],
        unique_mat_num: str,
    ):
        """
        Test creating a submission via InstanceManager.

        Pre-conditions:
            - User exists
            - Instance is running
            - No submission exists
        Action: Create submission with test results
        Post-conditions:
            - Submission exists with timestamp
            - Submission has test results
            - Submission is not graded
        """
        exercise_name = built_exercise["short_name"]
        instance_id = None

        # Create user
        create_user(
            ref_instance,
            mat_num=unique_mat_num,
            first_name="Submission",
            surname="Test",
            password="TestPassword123!",
        )

        try:
            # Create and start instance
            result = create_instance(
                ref_instance,
                mat_num=unique_mat_num,
                exercise_short_name=exercise_name,
                start=True,
                timeout=120.0,
            )
            instance_id = result["id"]

            # Pre-condition: No submission yet
            SubmissionConditions.pre_no_submission(
                ref_instance, unique_mat_num, exercise_name
            )

            # Action: Create submission with test results
            test_results = [
                {
                    "task_name": "test_add",
                    "success": True,
                    "score": 5.0,
                    "output": "OK",
                },
                {
                    "task_name": "test_sub",
                    "success": True,
                    "score": 5.0,
                    "output": "OK",
                },
            ]
            submission_result = create_submission(
                ref_instance,
                instance_id=instance_id,
                test_results=test_results,
            )

            # Verify return value
            assert submission_result["id"] is not None
            assert submission_result["submission_ts"] is not None
            assert submission_result["test_result_count"] == 2

            # Post-conditions (shared assertions)
            submission_data = SubmissionConditions.post_submission_created(
                ref_instance, unique_mat_num, exercise_name
            )
            assert submission_data["submission_ts"] is not None

            SubmissionConditions.post_submission_has_test_results(
                ref_instance, submission_result["id"], min_tests=2
            )
            SubmissionConditions.post_submission_not_graded(
                ref_instance, submission_result["id"]
            )

        finally:
            # Cleanup - note: we don't remove the instance since it's now a submission
            # The submission instance is separate from the origin instance
            if instance_id is not None:
                try:
                    stop_instance(ref_instance, instance_id)
                except Exception:
                    pass
            delete_user(ref_instance, unique_mat_num)

    @pytest.mark.integration
    @pytest.mark.slow
    @pytest.mark.timeout(180)
    def test_submission_with_failed_tests(
        self,
        ref_instance: "REFInstance",
        built_exercise: dict[str, Any],
        unique_mat_num: str,
    ):
        """
        Test creating a submission where some tests fail.
        """
        exercise_name = built_exercise["short_name"]
        instance_id = None

        # Create user
        create_user(
            ref_instance,
            mat_num=unique_mat_num,
            first_name="FailedTests",
            surname="Test",
            password="TestPassword123!",
        )

        try:
            # Create and start instance
            result = create_instance(
                ref_instance,
                mat_num=unique_mat_num,
                exercise_short_name=exercise_name,
                start=True,
                timeout=120.0,
            )
            instance_id = result["id"]

            # Action: Create submission with mixed test results
            test_results = [
                {
                    "task_name": "test_pass",
                    "success": True,
                    "score": 5.0,
                    "output": "OK",
                },
                {
                    "task_name": "test_fail",
                    "success": False,
                    "score": 0.0,
                    "output": "FAIL",
                },
            ]
            submission_result = create_submission(
                ref_instance,
                instance_id=instance_id,
                test_results=test_results,
            )

            # Post-condition: Check test results
            test_data = SubmissionConditions.post_submission_has_test_results(
                ref_instance, submission_result["id"], min_tests=2
            )

            # Verify we have both passed and failed tests
            assert test_data["passed_tests"] == 1
            assert test_data["failed_tests"] == 1

        finally:
            if instance_id is not None:
                try:
                    stop_instance(ref_instance, instance_id)
                except Exception:
                    pass
            delete_user(ref_instance, unique_mat_num)
