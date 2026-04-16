"""
Shared Pre/Post Condition Assertions for REF Tests

These condition classes provide reusable assertions that can be used by both:
- Integration tests (calling methods directly via remote_exec)
- E2E tests (using web interface)

All methods execute database queries via remote_exec to verify state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from helpers.ref_instance import REFInstance


class UserConditions:
    """Pre/post conditions for user-related operations."""

    @staticmethod
    def pre_user_not_exists(ref_instance: "REFInstance", mat_num: str) -> None:
        """Assert that a user with the given mat_num does NOT exist."""

        def _check() -> bool:
            from ref.model.user import User

            return User.query.filter_by(mat_num=mat_num).first() is None

        result = ref_instance.remote_exec(_check)
        assert result, f"User with mat_num={mat_num} should not exist (pre-condition)"

    @staticmethod
    def post_user_created(
        ref_instance: "REFInstance",
        mat_num: str,
        first_name: str,
        surname: str,
    ) -> dict[str, Any]:
        """
        Assert that a user exists with the correct attributes.

        Returns the user data as a dict for further assertions.
        """

        def _check() -> dict[str, Any] | None:
            from ref.model.user import User

            user = User.query.filter_by(mat_num=mat_num).first()
            if user is None:
                return None
            return {
                "id": user.id,
                "mat_num": user.mat_num,
                "first_name": user.first_name,
                "surname": user.surname,
                "is_student": user.is_student,
                "is_admin": user.is_admin,
                "is_grading_assistant": user.is_grading_assistant,
                "has_pub_key": bool(user.pub_key),
                "has_password": bool(user.password),
                "registered_date": (
                    user.registered_date.isoformat() if user.registered_date else None
                ),
            }

        user_data = ref_instance.remote_exec(_check)
        assert user_data is not None, f"User with mat_num={mat_num} should exist"
        assert user_data["mat_num"] == mat_num
        assert user_data["first_name"] == first_name
        assert user_data["surname"] == surname
        return user_data

    @staticmethod
    def post_user_is_student(ref_instance: "REFInstance", mat_num: str) -> None:
        """Assert that the user has student authorization."""

        def _check() -> bool:
            from ref.model.user import User

            user = User.query.filter_by(mat_num=mat_num).first()
            return user is not None and user.is_student

        result = ref_instance.remote_exec(_check)
        assert result, f"User {mat_num} should have student authorization"

    @staticmethod
    def post_user_has_ssh_key(ref_instance: "REFInstance", mat_num: str) -> None:
        """Assert that the user has an SSH public key set."""

        def _check() -> bool:
            from ref.model.user import User

            user = User.query.filter_by(mat_num=mat_num).first()
            return user is not None and bool(user.pub_key)

        result = ref_instance.remote_exec(_check)
        assert result, f"User {mat_num} should have SSH public key"

    @staticmethod
    def post_user_has_password(ref_instance: "REFInstance", mat_num: str) -> None:
        """Assert that the user has a password set."""

        def _check() -> bool:
            from ref.model.user import User

            user = User.query.filter_by(mat_num=mat_num).first()
            return user is not None and bool(user.password)

        result = ref_instance.remote_exec(_check)
        assert result, f"User {mat_num} should have password set"


class ExerciseConditions:
    """Pre/post conditions for exercise-related operations."""

    @staticmethod
    def pre_exercise_not_exists(ref_instance: "REFInstance", short_name: str) -> None:
        """Assert that an exercise with the given short_name does NOT exist."""

        def _check() -> bool:
            from ref.model.exercise import Exercise

            return Exercise.query.filter_by(short_name=short_name).first() is None

        result = ref_instance.remote_exec(_check)
        assert result, f"Exercise {short_name} should not exist (pre-condition)"

    @staticmethod
    def post_exercise_imported(
        ref_instance: "REFInstance",
        short_name: str,
    ) -> dict[str, Any]:
        """
        Assert that an exercise exists after import.

        Returns the exercise data as a dict for further assertions.
        """

        def _check() -> dict[str, Any] | None:
            from ref.model.exercise import Exercise

            exercise = Exercise.query.filter_by(short_name=short_name).first()
            if exercise is None:
                return None
            return {
                "id": exercise.id,
                "short_name": exercise.short_name,
                "version": exercise.version,
                "category": exercise.category,
                "build_job_status": (
                    exercise.build_job_status.value
                    if exercise.build_job_status
                    else None
                ),
                "is_default": exercise.is_default,
                "submission_test_enabled": exercise.submission_test_enabled,
                "max_grading_points": exercise.max_grading_points,
            }

        exercise_data = ref_instance.remote_exec(_check)
        assert exercise_data is not None, (
            f"Exercise {short_name} should exist after import"
        )
        assert exercise_data["short_name"] == short_name
        assert exercise_data["build_job_status"] == "NOT_BUILD"
        assert exercise_data["is_default"] is False
        return exercise_data

    @staticmethod
    def post_exercise_built(
        ref_instance: "REFInstance",
        exercise_id: int,
    ) -> None:
        """Assert that an exercise has been successfully built."""

        def _check() -> str | None:
            from ref.model.exercise import Exercise

            exercise = Exercise.query.get(exercise_id)
            if exercise is None:
                return None
            return (
                exercise.build_job_status.value if exercise.build_job_status else None
            )

        status = ref_instance.remote_exec(_check)
        assert status is not None, f"Exercise {exercise_id} should exist"
        assert status == "FINISHED", (
            f"Exercise build status should be FINISHED, got {status}"
        )

    @staticmethod
    def post_exercise_enabled(
        ref_instance: "REFInstance",
        exercise_id: int,
    ) -> None:
        """Assert that an exercise is enabled (set as default)."""

        def _check() -> bool | None:
            from ref.model.exercise import Exercise

            exercise = Exercise.query.get(exercise_id)
            if exercise is None:
                return None
            return exercise.is_default

        is_default = ref_instance.remote_exec(_check)
        assert is_default is not None, f"Exercise {exercise_id} should exist"
        assert is_default is True, f"Exercise {exercise_id} should be enabled"

    @staticmethod
    def get_exercise_by_name(
        ref_instance: "REFInstance",
        short_name: str,
    ) -> dict[str, Any] | None:
        """Get exercise data by short_name. Returns None if not found."""

        def _query() -> dict[str, Any] | None:
            from ref.model.exercise import Exercise

            exercise = Exercise.query.filter_by(short_name=short_name).first()
            if exercise is None:
                return None
            return {
                "id": exercise.id,
                "short_name": exercise.short_name,
                "version": exercise.version,
                "category": exercise.category,
                "build_job_status": (
                    exercise.build_job_status.value
                    if exercise.build_job_status
                    else None
                ),
                "is_default": exercise.is_default,
            }

        return ref_instance.remote_exec(_query)


class InstanceConditions:
    """Pre/post conditions for instance-related operations."""

    @staticmethod
    def pre_no_instance(
        ref_instance: "REFInstance",
        mat_num: str,
        exercise_short_name: str,
    ) -> None:
        """Assert that no instance exists for the user/exercise pair."""

        def _check() -> bool:
            from ref.model.exercise import Exercise
            from ref.model.instance import Instance
            from ref.model.user import User

            user = User.query.filter_by(mat_num=mat_num).first()
            if user is None:
                return True

            exercise = Exercise.query.filter_by(
                short_name=exercise_short_name, is_default=True
            ).first()
            if exercise is None:
                return True

            instance = Instance.query.filter_by(
                user_id=user.id,
                exercise_id=exercise.id,
            ).first()
            return instance is None or instance.submission is not None

        result = ref_instance.remote_exec(_check)
        assert result, (
            f"No active instance should exist for {mat_num}/{exercise_short_name}"
        )

    @staticmethod
    def post_instance_created(
        ref_instance: "REFInstance",
        mat_num: str,
        exercise_short_name: str,
    ) -> dict[str, Any]:
        """
        Assert that an instance exists for the user/exercise pair.

        Returns the instance data as a dict.
        """

        def _query() -> dict[str, Any] | None:
            from ref.model.exercise import Exercise
            from ref.model.instance import Instance
            from ref.model.user import User

            user = User.query.filter_by(mat_num=mat_num).first()
            if user is None:
                return None

            exercise = Exercise.query.filter_by(
                short_name=exercise_short_name, is_default=True
            ).first()
            if exercise is None:
                return None

            instance = Instance.query.filter_by(
                user_id=user.id,
                exercise_id=exercise.id,
            ).first()
            if instance is None or instance.submission is not None:
                return None

            return {
                "id": instance.id,
                "user_id": instance.user_id,
                "exercise_id": instance.exercise_id,
                "network_id": instance.network_id,
                "creation_ts": (
                    instance.creation_ts.isoformat() if instance.creation_ts else None
                ),
                "has_entry_service": instance.entry_service is not None,
            }

        instance_data = ref_instance.remote_exec(_query)
        assert instance_data is not None, (
            f"Instance should exist for {mat_num}/{exercise_short_name}"
        )
        assert instance_data["network_id"] is not None, (
            "Instance should have network_id"
        )
        return instance_data

    @staticmethod
    def post_instances_isolated(
        ref_instance: "REFInstance",
        mat_num1: str,
        mat_num2: str,
        exercise_short_name: str,
    ) -> None:
        """Assert that two users have separate, isolated instances."""

        def _query() -> dict[str, Any] | None:
            from ref.model.exercise import Exercise
            from ref.model.instance import Instance
            from ref.model.user import User

            user1 = User.query.filter_by(mat_num=mat_num1).first()
            user2 = User.query.filter_by(mat_num=mat_num2).first()
            if user1 is None or user2 is None:
                return None

            exercise = Exercise.query.filter_by(
                short_name=exercise_short_name, is_default=True
            ).first()
            if exercise is None:
                return None

            inst1 = Instance.query.filter_by(
                user_id=user1.id, exercise_id=exercise.id
            ).first()
            inst2 = Instance.query.filter_by(
                user_id=user2.id, exercise_id=exercise.id
            ).first()

            if inst1 is None or inst2 is None:
                return None

            # Filter out submission instances
            if inst1.submission is not None or inst2.submission is not None:
                return None

            return {
                "instance1_id": inst1.id,
                "instance2_id": inst2.id,
                "instance1_network": inst1.network_id,
                "instance2_network": inst2.network_id,
                "instance1_user": inst1.user_id,
                "instance2_user": inst2.user_id,
            }

        data = ref_instance.remote_exec(_query)
        assert data is not None, "Both users should have instances"
        assert data["instance1_id"] != data["instance2_id"], (
            "Instance IDs should differ"
        )
        assert data["instance1_network"] != data["instance2_network"], (
            "Network IDs should differ"
        )
        assert data["instance1_user"] != data["instance2_user"], (
            "User IDs should differ"
        )


class SubmissionConditions:
    """Pre/post conditions for submission-related operations."""

    @staticmethod
    def pre_no_submission(
        ref_instance: "REFInstance",
        mat_num: str,
        exercise_short_name: str,
    ) -> None:
        """Assert that no submission exists for the user/exercise pair."""

        def _check() -> int:
            from ref.model.exercise import Exercise
            from ref.model.user import User

            user = User.query.filter_by(mat_num=mat_num).first()
            if user is None:
                return 0

            exercise = Exercise.query.filter_by(
                short_name=exercise_short_name, is_default=True
            ).first()
            if exercise is None:
                return 0

            count = 0
            for instance in user.exercise_instances:
                if instance.exercise_id == exercise.id and instance.submission:
                    count += 1
            return count

        count = ref_instance.remote_exec(_check)
        assert count == 0, (
            f"No submission should exist for {mat_num}/{exercise_short_name}"
        )

    @staticmethod
    def post_submission_created(
        ref_instance: "REFInstance",
        mat_num: str,
        exercise_short_name: str,
    ) -> dict[str, Any]:
        """
        Assert that at least one submission exists for the user/exercise pair.

        Returns the latest submission data as a dict.
        """

        def _query() -> dict[str, Any] | None:
            from ref.model.exercise import Exercise
            from ref.model.user import User

            user = User.query.filter_by(mat_num=mat_num).first()
            if user is None:
                return None

            exercise = Exercise.query.filter_by(
                short_name=exercise_short_name, is_default=True
            ).first()
            if exercise is None:
                return None

            # Find the origin instance
            origin_instance = None
            for inst in user.exercise_instances:
                if inst.exercise_id == exercise.id and inst.submission is None:
                    origin_instance = inst
                    break

            if origin_instance is None:
                return None

            latest = origin_instance.get_latest_submission()
            if latest is None:
                return None

            return {
                "id": latest.id,
                "submission_ts": (
                    latest.submission_ts.isoformat() if latest.submission_ts else None
                ),
                "origin_instance_id": latest.origin_instance_id,
                "submitted_instance_id": latest.submitted_instance_id,
                "is_graded": latest.is_graded(),
                "test_result_count": len(latest.submission_test_results or []),
            }

        submission_data = ref_instance.remote_exec(_query)
        assert submission_data is not None, (
            f"Submission should exist for {mat_num}/{exercise_short_name}"
        )
        assert submission_data["submission_ts"] is not None
        return submission_data

    @staticmethod
    def post_submission_has_test_results(
        ref_instance: "REFInstance",
        submission_id: int,
        min_tests: int = 1,
    ) -> dict[str, Any]:
        """
        Assert that a submission has test results recorded.

        Returns detailed test results.
        """

        def _query() -> dict[str, Any] | None:
            from ref.model.instance import Submission

            submission = Submission.query.get(submission_id)
            if submission is None:
                return None

            results = submission.submission_test_results or []
            passed = sum(1 for r in results if r.success)

            return {
                "submission_id": submission.id,
                "total_tests": len(results),
                "passed_tests": passed,
                "failed_tests": len(results) - passed,
                "test_results": [
                    {
                        "task_name": tr.task_name,
                        "success": tr.success,
                        "score": tr.score,
                    }
                    for tr in results
                ],
            }

        data = ref_instance.remote_exec(_query)
        assert data is not None, f"Submission {submission_id} should exist"
        assert data["total_tests"] >= min_tests, (
            f"Expected at least {min_tests} test results, got {data['total_tests']}"
        )
        return data

    @staticmethod
    def post_submission_not_graded(
        ref_instance: "REFInstance",
        submission_id: int,
    ) -> None:
        """Assert that a submission has not been graded yet."""

        def _check() -> bool | None:
            from ref.model.instance import Submission

            submission = Submission.query.get(submission_id)
            if submission is None:
                return None
            return not submission.is_graded()

        result = ref_instance.remote_exec(_check)
        assert result is not None, f"Submission {submission_id} should exist"
        assert result is True, f"Submission {submission_id} should not be graded yet"
