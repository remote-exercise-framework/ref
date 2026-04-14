"""Endpoints called from inside running exercise containers.

Each request carries a payload signed with the instance's own key (see
``Instance.get_key``). The outer body has a plain ``instance_id`` used
only to look up the verification key; the verified inner ``instance_id``
is what subsequent code trusts.
"""

import json
import typing as ty
from dataclasses import dataclass

from flask import Request, abort, current_app, request
from itsdangerous import TimedSerializer

from ref import limiter, refbp
from ref.core import InstanceManager, datetime_to_string
from ref.core.logging import get_logger
from ref.model import Instance, SystemSettingsManager, User
from ref.model.instance import SubmissionTestResult

from . import error_response, ok_response

log = get_logger(__name__)


class SignatureUnwrappingError(Exception):
    """Raised when a container request can't be verified.

    ``user_error_message`` is safe to surface to callers; it never
    contains sensitive crypto details.
    """

    def __init__(self, user_error_message: str):
        self.user_error_message = user_error_message
        super().__init__(self, user_error_message)


def _unwrap_signed_container_request(req: Request, max_age_s: int = 60) -> ty.Any:
    """Verify and return the inner payload of a container request.

    Expected wire format::

        {
          "instance_id": int,       # lookup key (untrusted until verified)
          "data": {                 # signed with Instance.get_key()
            "instance_id": int,     # MUST match the outer instance_id
            ...
          }
        }
    """
    content = req.get_json(force=True, silent=True)
    if not content:
        log.warning("Got request without JSON body")
        raise SignatureUnwrappingError("Request is missing JSON body")

    if not isinstance(content, str):
        log.warning(f"Invalid type {type(content)}")
        raise SignatureUnwrappingError("Invalid request")

    s = TimedSerializer(b"", salt="from-container-to-web")
    try:
        _, unsafe_content = s.loads_unsafe(content)
    except Exception:
        log.warning("Failed to decode payload", exc_info=True)
        raise SignatureUnwrappingError("Error during decoding")

    instance_id = unsafe_content.get("instance_id")
    if instance_id is None:
        log.warning("Missing instance_id")
        raise SignatureUnwrappingError("Missing instance_id")

    try:
        instance_id = int(instance_id)
    except Exception:
        log.warning(f"Failed to convert {instance_id} to int", exc_info=True)
        raise SignatureUnwrappingError("Invalid instance ID")

    instance = Instance.query.filter(Instance.id == instance_id).one_or_none()
    if not instance:
        log.warning(f"Failed to find instance with ID {instance_id}")
        raise SignatureUnwrappingError("Unable to find given instance")

    instance_key = instance.get_key()

    s = TimedSerializer(instance_key, salt="from-container-to-web")
    try:
        signed_content = s.loads(content, max_age=max_age_s)
    except Exception:
        log.warning("Invalid request", exc_info=True)
        raise SignatureUnwrappingError("Invalid request")

    return signed_content


@refbp.route("/api/instance/reset", methods=("GET", "POST"))
@limiter.limit("3 per minute; 24 per day")
def api_instance_reset():
    """Reset the container to its pristine per-exercise state.

    Body (signed): ``{"instance_id": int}``.
    """
    try:
        content = _unwrap_signed_container_request(request)
    except SignatureUnwrappingError as e:
        return error_response(e.user_error_message)

    instance_id = content.get("instance_id")
    try:
        instance_id = int(instance_id)
    except ValueError:
        log.warning(f"Invalid instance id {instance_id}", exc_info=True)
        return error_response("Invalid instance ID")

    log.info(f"Received reset request for instance_id={instance_id}")

    instance = Instance.query.filter(Instance.id == instance_id).one_or_none()
    if not instance:
        log.warning(f"Invalid instance id {instance_id}")
        return error_response("Invalid request")

    user = User.query.filter(User.id == instance.user.id).one_or_none()
    if not user:
        log.warning(f"Invalid user ID {instance.user.id}")
        return error_response("Invalid request")

    mgr = InstanceManager(instance)
    mgr.reset()
    current_app.db.session.commit()

    return ok_response("OK")


@refbp.route("/api/instance/submit", methods=("GET", "POST"))
@limiter.limit("3 per minute; 24 per day")
def api_instance_submit():
    """Record a submission with its per-task test results.

    Body (signed)::

        {
          "instance_id": int,
          "output": str,            # user-controlled output capture
          "test_results": [
            {"task_name": str, "success": bool, "score": float | None},
            ...
          ]
        }
    """
    try:
        content: ty.Dict[str, ty.Any] = _unwrap_signed_container_request(request)
    except SignatureUnwrappingError as e:
        return error_response(e.user_error_message)

    instance_id = content["instance_id"]
    try:
        instance_id = int(instance_id)
    except ValueError:
        log.warning(f"Invalid instance id {instance_id}", exc_info=True)
        abort(400)

    log.info(f"Got submit request for instance_id={instance_id}")
    print(json.dumps(content, indent=4))

    # ! Keep in sync with ref-docker-base/task.py
    @dataclass
    class TestResult:
        task_name: str
        success: bool
        score: ty.Optional[float]

    test_results: ty.List[TestResult] = []
    try:
        test_results_list: ty.List[ty.Dict[ty.Any, ty.Any]] = content["test_results"]
        for r in test_results_list:
            test_results.append(TestResult(**r))

        # Postgres dislikes \x00 bytes in strings; replace with U+FFFD.
        user_controlled_test_output = content["output"].replace("\x00", "\ufffd")
    except Exception:
        log.warning("Invalid request", exc_info=True)
        abort(400)

    instance = Instance.query.filter(Instance.id == instance_id).one_or_none()
    if not instance:
        log.warning(f"Invalid instance id {instance_id}")
        return error_response("Invalid request")

    user = User.query.filter(User.id == instance.user.id).one_or_none()
    if not user:
        log.warning(f"Invalid user ID {instance.user.id}")
        return error_response("Invalid request")

    if instance.submission:
        log.warning(
            f"User tried to submit instance that is already submitted: {instance}"
        )
        return error_response("Unable to submit: Instance is a submission itself.")

    if not instance.exercise.has_deadline():
        log.info(f"User tried to submit instance {instance} without deadline")
        return error_response(
            'Unable to submit: This is an un-graded, open-end exercise rather than an graded assignment. Use "task check" to receive feedback.'
        )

    if instance.exercise.deadine_passed():
        log.info(f"User tried to submit instance {instance} after deadline :-O")
        deadline = datetime_to_string(instance.exercise.submission_deadline_end)
        return error_response(
            f"Unable to submit: The submission deadline already passed (was due before {deadline})"
        )

    if SystemSettingsManager.SUBMISSION_DISABLED.value:
        log.info("Rejecting submission request since submission is currently disabled.")
        return error_response(
            "Submission is currently disabled, please try again later."
        )

    mgr = InstanceManager(instance)

    # Creating the submission stops the instance it was made from. If the
    # subsequent commit fails, the user won't see any error feedback.
    test_result_objs = []
    for r in test_results:
        o = SubmissionTestResult(
            r.task_name, user_controlled_test_output, r.success, r.score
        )
        test_result_objs.append(o)
    new_instance = mgr.create_submission(test_result_objs)

    current_app.db.session.commit()
    log.info(f"Created submission: {new_instance.submission}")

    return ok_response(
        f"[+] Submission with ID {new_instance.id} successfully created!"
    )


@refbp.route("/api/instance/info", methods=("GET", "POST"))
@limiter.limit("10 per minute")
def api_instance_info():
    """Return a summary dict the container can display to the student.

    Body (signed): ``{"instance_id": int}``.
    """
    try:
        content = _unwrap_signed_container_request(request)
    except SignatureUnwrappingError as e:
        return error_response(e.user_error_message)

    instance_id = content.get("instance_id")
    try:
        instance_id = int(instance_id)
    except ValueError:
        log.warning(f"Invalid instance id {instance_id}", exc_info=True)
        return error_response("Invalid instance ID")

    log.info(f"Received info request for instance_id={instance_id}")

    instance: Instance = Instance.query.filter(Instance.id == instance_id).one_or_none()
    if not instance:
        log.warning(f"Invalid instance id {instance_id}")
        return error_response("Invalid request")

    exercise = instance.exercise
    user = instance.user

    return ok_response(
        {
            "instance_id": instance.id,
            "is_submission": bool(instance.submission),
            "user_full_name": user.full_name,
            "user_mat_num": user.mat_num,
            "is_admin": bool(user.is_admin),
            "is_grading_assistant": bool(user.is_grading_assistant),
            "exercise_short_name": exercise.short_name,
            "exercise_version": exercise.version,
        }
    )
