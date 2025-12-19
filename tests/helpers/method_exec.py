"""
Method Executors for REF Integration Tests

These functions execute webapp methods via remote_exec, using the same
abstraction layers (managers, view logic) that the web interface uses.

IMPORTANT: Tests should never directly manipulate database objects.
Instead, they should use manager classes (ExerciseManager, InstanceManager,
ExerciseImageManager) or replicate the logic from view functions.
This ensures tests exercise the same code paths as the real application.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from helpers.ref_instance import REFInstance


def create_user(
    ref_instance: "REFInstance",
    mat_num: str,
    first_name: str,
    surname: str,
    password: str,
    generate_ssh_key: bool = True,
) -> dict[str, Any]:
    """
    Create a user using UserManager.create_student().

    Uses the same UserManager abstraction as ref/view/student.py.

    Args:
        ref_instance: The REF instance to execute in
        mat_num: Matriculation number (unique identifier)
        first_name: User's first name
        surname: User's surname
        password: User's password (will be hashed)
        generate_ssh_key: Whether to generate SSH key pair

    Returns:
        Dict with user info including 'id', 'mat_num', and optionally 'private_key'
    """

    def _create() -> dict[str, Any]:
        from flask import current_app

        from ref.core.user import UserManager

        # Generate SSH key pair if requested (like the view does)
        pubkey = None
        privkey = None

        if generate_ssh_key:
            from Crypto.PublicKey import RSA

            key = RSA.generate(2048)
            pubkey = key.export_key(format="OpenSSH").decode()
            privkey = key.export_key().decode()

        # Use UserManager like the view does
        user = UserManager.create_student(
            mat_num=mat_num,
            first_name=first_name,
            surname=surname,
            password=password,
            pub_key=pubkey,
            priv_key=privkey,
        )

        current_app.db.session.add(user)
        current_app.db.session.commit()

        return {
            "id": user.id,
            "mat_num": user.mat_num,
            "private_key": privkey,
        }

    return ref_instance.remote_exec(_create)


def delete_user(ref_instance: "REFInstance", mat_num: str) -> bool:
    """
    Delete a user using UserManager.delete_with_instances().

    Uses the UserManager abstraction to remove associated instances
    and delete the user.

    Returns True if deleted, False if not found.
    """

    def _delete() -> bool:
        from flask import current_app

        from ref.core.user import UserManager
        from ref.model.user import User

        user = User.query.filter_by(mat_num=mat_num).first()
        if user is None:
            return False

        # Use UserManager to delete user and associated instances
        UserManager.delete_with_instances(user)
        current_app.db.session.commit()
        return True

    return ref_instance.remote_exec(_delete)


def import_exercise(
    ref_instance: "REFInstance",
    template_path: str,
) -> dict[str, Any]:
    """
    Import an exercise following the same pattern as exercise_do_import view.

    Uses ExerciseManager.from_template() and ExerciseManager.create()
    as the view does in ref/view/exercise.py.

    Args:
        ref_instance: The REF instance to execute in
        template_path: Path to the exercise template directory (containing settings.yml).
                       Can be a host path (will be translated to container path).

    Returns:
        Dict with exercise info including 'id' and 'short_name'
    """
    from pathlib import Path

    # Translate host path to container path
    # Host: /tmp/.../exercises0/exercise_name -> Container: /exercises/exercise_name
    host_path = Path(template_path)
    exercises_dir = ref_instance.exercises_dir

    if host_path.is_relative_to(exercises_dir):
        relative_path = host_path.relative_to(exercises_dir)
        container_path = f"/exercises/{relative_path}"
    else:
        # Assume it's already a container path or absolute path
        container_path = template_path

    def _import() -> dict[str, Any]:
        from flask import current_app

        from ref.core.exercise import ExerciseManager

        # Use ExerciseManager like the view does
        exercise = ExerciseManager.from_template(container_path)
        ExerciseManager.create(exercise)

        current_app.db.session.add_all([exercise.entry_service, exercise])
        current_app.db.session.commit()

        return {
            "id": exercise.id,
            "short_name": exercise.short_name,
            "version": exercise.version,
            "category": exercise.category,
        }

    return ref_instance.remote_exec(_import)


def delete_exercise(ref_instance: "REFInstance", exercise_id: int) -> bool:
    """
    Delete an exercise following the same pattern as exercise_delete view.

    This replicates the deletion logic from ref/view/exercise.py:
    - Removes associated instances via InstanceManager
    - Uses ExerciseImageManager.remove() to clean up Docker images
    - Deletes related services and exercise from DB

    Returns True if deleted, False if not found.
    """

    def _delete() -> bool:
        from flask import current_app

        from ref.core.image import ExerciseImageManager
        from ref.core.instance import InstanceManager
        from ref.model.exercise import Exercise

        exercise = Exercise.query.get(exercise_id)
        if exercise is None:
            return False

        # Remove associated instances first (like the view does)
        for instance in list(exercise.instances):
            mgr = InstanceManager(instance)
            mgr.remove()

        # Use ExerciseImageManager to clean up Docker images (like the view does)
        img_mgr = ExerciseImageManager(exercise)
        img_mgr.remove()

        # Delete related services (like the view does)
        for service in exercise.services:
            current_app.db.session.delete(service)

        current_app.db.session.delete(exercise.entry_service)
        current_app.db.session.delete(exercise)
        current_app.db.session.commit()
        return True

    return ref_instance.remote_exec(_delete)


def build_exercise(
    ref_instance: "REFInstance",
    exercise_id: int,
    timeout: float = 300.0,
) -> bool:
    """
    Build an exercise Docker image using ExerciseImageManager.

    Uses ExerciseImageManager.build() as the view does in ref/view/exercise.py.

    Args:
        ref_instance: The REF instance to execute in
        exercise_id: The exercise ID to build
        timeout: Build timeout in seconds

    Returns:
        True if build succeeded, False otherwise
    """

    def _build() -> bool:
        from flask import current_app

        from ref.core.image import ExerciseImageManager
        from ref.model.exercise import Exercise

        exercise = Exercise.query.get(exercise_id)
        if exercise is None:
            return False

        # Use ExerciseImageManager like the view does
        mgr = ExerciseImageManager(exercise)
        mgr.build()
        current_app.db.session.commit()

        return exercise.build_job_status.value == "FINISHED"

    return ref_instance.remote_exec(_build, timeout=timeout)


def enable_exercise(ref_instance: "REFInstance", exercise_id: int) -> bool:
    """
    Enable an exercise (set as default) following exercise_toggle_default view.

    This sets is_default=True as the view does in ref/view/exercise.py.

    Returns True if enabled, False if not found.
    """

    def _enable() -> bool:
        from flask import current_app

        from ref.model.exercise import Exercise

        exercise = Exercise.query.get(exercise_id)
        if exercise is None:
            return False

        # Set default flag like the view does
        exercise.is_default = True
        current_app.db.session.commit()
        return True

    return ref_instance.remote_exec(_enable)


def create_instance(
    ref_instance: "REFInstance",
    mat_num: str,
    exercise_short_name: str,
    start: bool = True,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """
    Create (and optionally start) an instance using InstanceManager.

    Uses InstanceManager.create_instance() and InstanceManager.start()
    as the API endpoint does in ref/view/api.py.

    Args:
        ref_instance: The REF instance to execute in
        mat_num: User's matriculation number
        exercise_short_name: Exercise short name
        start: Whether to start the instance (creates containers)
        timeout: Timeout for starting the instance

    Returns:
        Dict with instance info
    """

    def _create() -> dict[str, Any]:
        from flask import current_app

        from ref.core.instance import InstanceManager
        from ref.model.exercise import Exercise
        from ref.model.user import User

        user = User.query.filter_by(mat_num=mat_num).first()
        if user is None:
            raise ValueError(f"User not found: {mat_num}")

        exercise = Exercise.query.filter_by(
            short_name=exercise_short_name, is_default=True
        ).first()
        if exercise is None:
            raise ValueError(f"Exercise not found: {exercise_short_name}")

        # Use InstanceManager factory method like the API does
        instance = InstanceManager.create_instance(user, exercise)
        current_app.db.session.commit()

        if start:
            mgr = InstanceManager(instance)
            mgr.start()
            current_app.db.session.commit()

        return {
            "id": instance.id,
            "user_id": instance.user_id,
            "exercise_id": instance.exercise_id,
            "network_id": instance.network_id,
        }

    return ref_instance.remote_exec(_create, timeout=timeout)


def stop_instance(ref_instance: "REFInstance", instance_id: int) -> bool:
    """
    Stop an instance using InstanceManager.stop().

    Uses the same pattern as instance_stop view in ref/view/instances.py.
    """

    def _stop() -> bool:
        from flask import current_app

        from ref.core.instance import InstanceManager
        from ref.model.instance import Instance

        instance = Instance.query.get(instance_id)
        if instance is None:
            return False

        mgr = InstanceManager(instance)
        mgr.stop()
        current_app.db.session.commit()
        return True

    return ref_instance.remote_exec(_stop)


def remove_instance(ref_instance: "REFInstance", instance_id: int) -> bool:
    """
    Remove an instance using InstanceManager.remove().

    Uses the same pattern as instance_delete view in ref/view/instances.py.
    """

    def _remove() -> bool:
        from flask import current_app

        from ref.core.instance import InstanceManager
        from ref.model.instance import Instance

        instance = Instance.query.get(instance_id)
        if instance is None:
            return False

        mgr = InstanceManager(instance)
        mgr.remove()
        current_app.db.session.commit()
        return True

    return ref_instance.remote_exec(_remove)


def create_submission(
    ref_instance: "REFInstance",
    instance_id: int,
    test_results: list[dict[str, Any]],
    timeout: float = 60.0,
) -> dict[str, Any]:
    """
    Create a submission using InstanceManager.create_submission().

    Uses the same pattern as instance_manual_submit view in ref/view/instances.py.

    Args:
        ref_instance: The REF instance to execute in
        instance_id: The instance ID to submit
        test_results: List of test result dicts with 'task_name', 'success', 'score'

    Returns:
        Dict with submission info
    """

    def _create() -> dict[str, Any]:
        from flask import current_app

        from ref.core.instance import InstanceManager
        from ref.model.instance import Instance, SubmissionTestResult

        instance = Instance.query.get(instance_id)
        if instance is None:
            raise ValueError(f"Instance not found: {instance_id}")

        # Create test results like the view does
        results = [
            SubmissionTestResult(
                task_name=tr["task_name"],
                output=tr.get("output", ""),
                success=tr["success"],
                score=tr.get("score"),
            )
            for tr in test_results
        ]

        # Use InstanceManager.create_submission() like the view does
        mgr = InstanceManager(instance)
        submitted_instance = mgr.create_submission(results)
        current_app.db.session.commit()

        submission = submitted_instance.submission
        return {
            "id": submission.id,
            "origin_instance_id": submission.origin_instance_id,
            "submitted_instance_id": submission.submitted_instance_id,
            "submission_ts": (
                submission.submission_ts.isoformat()
                if submission.submission_ts
                else None
            ),
            "test_result_count": len(results),
        }

    return ref_instance.remote_exec(_create, timeout=timeout)


def sign_file_browser_path(
    ref_instance: "REFInstance",
    path_prefix: str,
) -> str:
    """
    Generate a signed file browser token for the given path prefix.

    Uses the same URLSafeTimedSerializer as ref/view/file_browser.py
    to create a valid token that authorizes access to files under
    the given path prefix.

    Args:
        ref_instance: The REF instance to execute in
        path_prefix: Absolute path prefix to authorize access to

    Returns:
        A signed token string that can be used with /admin/file-browser/load-file
    """

    def _sign() -> str:
        import dataclasses

        from flask import current_app
        from itsdangerous import URLSafeTimedSerializer

        @dataclasses.dataclass
        class PathSignatureToken:
            path_prefix: str

        token = PathSignatureToken(path_prefix)
        signer = URLSafeTimedSerializer(
            current_app.config["SECRET_KEY"], salt="file-browser"
        )
        return signer.dumps(dataclasses.asdict(token))

    return ref_instance.remote_exec(_sign)
