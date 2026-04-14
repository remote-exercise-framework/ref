"""SSH reverse-proxy hooks.

These endpoints are called by `ssh-reverse-proxy` to authenticate
connections, provision/resolve exercise instances, and fetch the SSH
welcome header. The proxy signs its requests with the shared
``SSH_TO_WEB_KEY`` HMAC secret (see ``_verify_signed_body``).
"""

import re

import arrow
from flask import Flask, current_app, request
from itsdangerous import Serializer

from ref import db, limiter, refbp
from ref.core import AnsiColorUtil as ansi
from ref.core import (
    ExerciseImageManager,
    InconsistentStateError,
    InstanceManager,
    utc_datetime_to_local_tz,
)
from ref.core.logging import get_logger
from ref.model import Exercise, Instance, SystemSettingsManager, User

from . import error_response, ok_response

log = get_logger(__name__)


class ApiRequestError(Exception):
    """Raised by the internal helpers when a request must be rejected.

    Holds the Flask response that the outer view returns to the caller.
    """

    def __init__(self, response):
        super().__init__(self)
        self.response = response


def _verify_signed_body(req):
    """Return the verified JSON payload or a Flask error response.

    Wraps the common ``SSH_TO_WEB_KEY`` signature check used by every
    proxy endpoint except the (historically unsigned) ssh-authenticated
    hook.
    """
    content = req.get_json(force=True, silent=True)
    if not content:
        log.warning("Missing JSON body in request")
        return None, error_response("Missing JSON body in request")

    s = Serializer(current_app.config["SSH_TO_WEB_KEY"])
    try:
        content = s.loads(content)
    except Exception as e:
        log.warning(f"Invalid request {e}")
        return None, error_response("Invalid request")

    if not isinstance(content, dict):
        log.warning(f"Unexpected data type {type(content)}")
        return None, error_response("Invalid request")

    return content, None


def start_and_return_instance(
    instance: Instance, requesting_user: User, requests_root_access: bool
):
    """Return ip/cmd/welcome for the given instance, starting it if needed.

    The returned response is ready to be forwarded as the final reply to
    the SSH reverse proxy. Raises ``ApiRequestError`` with a pre-built
    error response when the instance's underlying image is missing.
    """
    log.info(f"Start of instance {instance} was requested.")

    if not ExerciseImageManager(instance.exercise).is_build():
        log.error(
            f"User {instance.user} has an instance ({instance}) of an exercise that is not built. Possibly someone deleted the docker image?"
        )
        raise ApiRequestError(
            error_response(
                "Inconsistent build state! Please notify the system administrator immediately"
            )
        )

    instance_manager = InstanceManager(instance)
    if not instance_manager.is_running():
        log.info(f"Instance ({instance}) is not running. Starting..")
        instance_manager.start()

    try:
        ip = instance_manager.get_entry_ip()
    except Exception:
        log.error("Failed to get IP of instance. Stopping instance..", exc_info=True)
        instance_manager.stop()
        raise

    exercise: Exercise = instance.exercise

    header = SystemSettingsManager.SSH_WELCOME_MSG.value or ""
    msg_of_the_day = SystemSettingsManager.SSH_MESSAGE_OF_THE_DAY.value
    if msg_of_the_day:
        header += f"\n{ansi.green(msg_of_the_day)}"

    user_name = requesting_user.full_name
    greeting = f'Hello {user_name}!\n[+] Connecting to task "{exercise.short_name}"...'

    welcome_message = f"{header}\n{greeting}\n"

    if not instance.is_submission():
        latest_submission = instance.get_latest_submission()
        if not exercise.has_deadline():
            pass
        elif not latest_submission:
            welcome_message += "    Last submitted: (No submission found)\n"
        else:
            ts = utc_datetime_to_local_tz(latest_submission.submission_ts)
            since_in_str = arrow.get(ts).humanize()
            ts = ts.strftime("%A, %B %dth @ %H:%M")
            welcome_message += f"    Last submitted: {ts} ({since_in_str})\n"
    else:
        ts = utc_datetime_to_local_tz(instance.submission.submission_ts)
        since_in_str = arrow.get(ts).humanize()
        ts = ts.strftime("%A, %B %dth @ %H:%M")
        user_name = instance.user.full_name
        welcome_message += f"    This is a submission from {ts} ({since_in_str})\n"
        welcome_message += f"    User     : {user_name}\n"
        welcome_message += f"    Exercise : {exercise.short_name}\n"
        welcome_message += f"    Version  : {exercise.version}\n"
        if instance.is_modified():
            welcome_message += ansi.red(
                "    This submission was modified!\n    Use `task reset` to restore the initially submitted state.\n"
            )

    if exercise.has_deadline():
        ts = utc_datetime_to_local_tz(exercise.submission_deadline_end)
        since_in_str = arrow.get(ts).humanize()
        deadline = ts.strftime("%A, %B %dth @ %H:%M")
        if exercise.deadine_passed():
            msg = f"    Deadline: Passed on {deadline} ({since_in_str})\n"
            welcome_message += ansi.red(msg)
        else:
            welcome_message += f"    Deadline: {deadline} ({since_in_str})\n"

    welcome_message = welcome_message.rstrip()

    resp = {
        "ip": ip,
        "cmd": instance.exercise.entry_service.cmd,
        "welcome_message": welcome_message,
        "as_root": requests_root_access and requesting_user.is_admin,
    }
    log.info(f"Instance was started! resp={resp}")

    return ok_response(resp)


def handle_instance_introspection_request(
    query, pubkey, requests_root_access: bool
) -> tuple[Flask.response_class, Instance]:
    """Route ``instance-<ID>`` queries to an admin/grading-assistant view.

    Lets an admin connect to an arbitrary instance by using
    ``instance-<INSTANCE_ID>`` as the exercise name during SSH auth.
    Grading assistants can only inspect submissions whose deadlines have
    passed when ``SUBMISSION_HIDE_ONGOING`` is set.
    """
    instance_id = re.findall(r"^instance-([0-9]+)", query)
    try:
        instance_id = int(instance_id[0])
    except Exception:
        log.warning(f"Invalid instance ID {instance_id}")
        raise ApiRequestError(error_response("Invalid instance ID."))

    instance: Instance = Instance.query.filter(Instance.id == instance_id).one_or_none()
    user: User = User.query.filter(User.pub_key == pubkey).one_or_none()

    if not user:
        log.warning("User not found.")
        raise ApiRequestError(error_response("Unknown user."))

    if not SystemSettingsManager.INSTANCE_SSH_INTROSPECTION.value:
        log.warning("Instance SSH introspection is disabled!")
        raise ApiRequestError(error_response("Introspection is disabled."))

    if not user.is_admin and not user.is_grading_assistant:
        log.warning(
            "Only administrators and grading assistants are allowed to request access to specific instances."
        )
        raise ApiRequestError(error_response("Insufficient permissions"))

    if not instance:
        log.warning(f"Invalid instance_id={instance_id}")
        raise ApiRequestError(error_response("Invalid instance ID"))

    if user.is_grading_assistant:
        if not instance.is_submission():
            raise ApiRequestError(error_response("Insufficient permissions."))
        exercise = instance.exercise
        hide_ongoing = SystemSettingsManager.SUBMISSION_HIDE_ONGOING.value
        if exercise.has_deadline() and not exercise.deadine_passed() and hide_ongoing:
            raise ApiRequestError(
                error_response("Deadline has not passed yet, permission denied.")
            )

    return start_and_return_instance(instance, user, requests_root_access), instance


def process_instance_request(query: str, pubkey: str) -> tuple:
    """Resolve an SSH-auth query into a running instance for ``pubkey``.

    Supported ``query`` forms:

    - ``<short_name>``              — default version of an exercise.
    - ``<short_name>@<version>``    — admin-only pinned version (needs
      ``INSTANCE_NON_DEFAULT_PROVISIONING``).
    - ``instance-<id>``             — admin/grading-assistant introspection.
    - ``root@<short_name>``         — request root access (admin-only,
      gated on ``ALLOW_ROOT_LOGINS_FOR_ADMINS``).

    Raises ``ApiRequestError`` for any rejected request. Returns
    ``(flask_response, instance)`` on success.
    """
    name = query

    user: User = User.query.filter(User.pub_key == pubkey).one_or_none()
    if not user:
        log.warning("Unable to find user with provided publickey")
        raise ApiRequestError(error_response("Unknown public key"))

    if (SystemSettingsManager.MAINTENANCE_ENABLED.value) and not user.is_admin:
        log.info(
            "Rejecting connection since maintenance mode is enabled and user is not an administrator"
        )
        raise ApiRequestError(
            error_response(
                "\n-------------------\nSorry, maintenance mode is enabled.\nPlease try again later.\n-------------------\n"
            )
        )

    requests_root_access = False
    if name.startswith("root@"):
        name = name.removeprefix("root@")
        requests_root_access = True

    # FIXME: Make this also work for instance-* requests.
    if (
        requests_root_access
        and not SystemSettingsManager.ALLOW_ROOT_LOGINS_FOR_ADMINS.value
    ):
        log.info("Rejecting root access, since its is disable!")
        raise ApiRequestError(error_response("Requested task not found"))

    if name.startswith("instance-"):
        response, instance = handle_instance_introspection_request(
            name, pubkey, requests_root_access
        )
        db.session.commit()
        return response, instance

    exercise_version = None
    if "@" in name:
        if not SystemSettingsManager.INSTANCE_NON_DEFAULT_PROVISIONING.value:
            raise ApiRequestError(
                error_response("Settings: Non-default provisioning is not allowed")
            )
        if not user.is_admin:
            raise ApiRequestError(
                error_response(
                    "Insufficient permissions: Non-default provisioning is only allowed for admins"
                )
            )
        name = name.split("@")
        exercise_version = name[1]
        name = name[0]

    if exercise_version is not None:
        requested_exercise = Exercise.get_exercise(
            name, exercise_version, for_update=True
        )
    else:
        requested_exercise = Exercise.get_default_exercise(name, for_update=True)
    log.info(f"Requested exercise is {requested_exercise}")
    if not requested_exercise:
        raise ApiRequestError(error_response("Requested task not found"))

    user_instances = list(
        filter(
            lambda e: e.exercise.short_name == requested_exercise.short_name,
            user.exercise_instances,
        )
    )
    user_instances = list(filter(lambda e: not e.submission, user_instances))

    if exercise_version is not None:
        user_instances = list(
            filter(lambda e: e.exercise.version == exercise_version, user_instances)
        )

    user_instances = sorted(
        user_instances, key=lambda e: e.exercise.version, reverse=True
    )
    user_instance = None

    if user_instances:
        log.info(f"User has instance {user_instances} of requested exercise")
        user_instance = user_instances[0]
        assert not user_instance.submission
        if (
            exercise_version is None
            and user_instance.exercise.version < requested_exercise.version
        ):
            old_instance = user_instance
            log.info(
                f"Found an upgradeable instance. Upgrading {old_instance} to new version {requested_exercise}"
            )
            mgr = InstanceManager(old_instance)
            user_instance = mgr.update_instance(requested_exercise)
            mgr.bequeath_submissions_to(user_instance)

            try:
                db.session.begin_nested()
                mgr.remove()
            except Exception as e:
                db.session.rollback()
                db.session.commit()
                raise InconsistentStateError(
                    "Failed to remove old instance after upgrading."
                ) from e
            else:
                db.session.commit()
    else:
        user_instance = InstanceManager.create_instance(user, requested_exercise)

    response = start_and_return_instance(user_instance, user, requests_root_access)

    db.session.commit()
    return response, user_instance


@refbp.route("/api/ssh-authenticated", methods=("GET", "POST"))
@limiter.exempt
def api_ssh_authenticated():
    """Post-auth hook called by the SSH reverse proxy.

    Fired once the proxy has validated a pubkey against ``/api/getkeys``.
    Prepares the instance the subsequent ``/api/provision`` call will
    hand out so port forwarding etc. can be wired up beforehand.

    Body: ``{"name": str, "pubkey": str}``.
    """
    import traceback

    log.info("[API] api_ssh_authenticated called")
    print("[API] api_ssh_authenticated called", flush=True)

    content = request.get_json(force=True, silent=True)
    if not content:
        log.warning("Received provision request without JSON body")
        return error_response("Request is missing JSON body")

    # FIXME: Check authenticity !!!

    if not isinstance(content, dict):
        log.warning(f"Unexpected data type {type(content)}")
        return error_response("Invalid request")

    pubkey = content.get("pubkey", None)
    if not pubkey:
        log.warning("Missing pubkey")
        return error_response("Invalid request")

    pubkey = pubkey.strip()
    log.info(f"[API] pubkey (first 60 chars): {pubkey[:60]}...")
    print(f"[API] pubkey (first 60 chars): {pubkey[:60]}...", flush=True)

    name = content.get("name", None)
    if not name:
        log.warning("Missing name")
        return error_response("Invalid request")

    log.info(f"[API] name={name}")
    print(f"[API] name={name}", flush=True)

    # name is user provided — make sure it is valid UTF-8 before touching SQLA.
    try:
        name.encode()
    except Exception as e:
        log.error(f"Invalid exercise name {str(e)}")
        return error_response("Requested task not found")

    log.info(f"Got request from pubkey={pubkey:32}, name={name}")

    try:
        log.info("[API] Calling process_instance_request...")
        print("[API] Calling process_instance_request...", flush=True)
        _, instance = process_instance_request(name, pubkey)
        log.info(f"[API] process_instance_request returned instance={instance}")
        print(
            f"[API] process_instance_request returned instance={instance}", flush=True
        )
    except ApiRequestError as e:
        log.warning("[API] ApiRequestError: returning error response")
        print("[API] ApiRequestError: returning error response", flush=True)
        return e.response
    except Exception as e:
        log.error(f"[API] Unexpected exception in api_ssh_authenticated: {e}")
        print(f"[API] Unexpected exception in api_ssh_authenticated: {e}", flush=True)
        traceback.print_exc()
        raise

    ret = {
        "instance_id": instance.id,
        "is_admin": int(instance.user.is_admin),
        "is_grading_assistent": int(instance.user.is_grading_assistant),
        "tcp_forwarding_allowed": int(
            instance.user.is_admin
            or SystemSettingsManager.ALLOW_TCP_PORT_FORWARDING.value
        ),
    }

    log.info(f"ret={ret}")

    return ok_response(ret)


@refbp.route("/api/provision", methods=("GET", "POST"))
@limiter.exempt
def api_provision():
    """Final provisioning step called by the SSH reverse proxy.

    Called after the proxy has wired up whatever transport state
    ``/api/ssh-authenticated`` asked for. May run concurrently with
    itself across connections.

    Body: signed ``{"exercise_name": str, "pubkey": str}``.
    """
    content, err = _verify_signed_body(request)
    if err is not None:
        return err

    pubkey = content.get("pubkey", None)
    if not pubkey:
        log.warning("Missing pubkey")
        return error_response("Invalid request")

    exercise_name = content.get("exercise_name", None)
    if not exercise_name:
        log.warning("Missing exercise_name")
        return error_response("Invalid request")

    try:
        exercise_name.encode()
    except Exception as e:
        log.error(f"Invalid exercise name {str(e)}")
        return error_response("Requested task not found")

    log.info(f"Got request from pubkey={pubkey:32}, exercise_name={exercise_name}")

    try:
        response, _ = process_instance_request(exercise_name, pubkey)
    except ApiRequestError as e:
        return e.response

    return response


@refbp.route("/api/getkeys", methods=("GET", "POST"))
@limiter.exempt
def api_getkeys():
    """Return every registered pubkey, for the SSH proxy's authorized_keys.

    Body: signed ``{"username": str}``. ``username`` is currently only
    validated to be non-empty — we always return the full key set.
    """
    content, err = _verify_signed_body(request)
    if err is not None:
        return err

    username = content.get("username")
    if not username:
        log.warning("Missing username attribute")
        return error_response("Invalid request")

    students = User.all()
    keys = [s.pub_key for s in students]
    return ok_response({"keys": keys})


@refbp.route("/api/getuserinfo", methods=("GET", "POST"))
@limiter.exempt
def api_getuserinfo():
    """Resolve a pubkey to its owning user's display info."""
    content, err = _verify_signed_body(request)
    if err is not None:
        return err

    pubkey = content.get("pubkey")
    if not pubkey:
        log.warning("Got request without pubkey attribute")
        return error_response("Invalid request")

    log.info(f"Got request for pubkey={pubkey[:32]}")
    user = db.get(User, pub_key=pubkey)

    if user:
        log.info(f"Found matching user: {user}")
        return ok_response(
            {"name": user.first_name + " " + user.surname, "mat_num": user.mat_num}
        )
    log.info("User not found")
    return error_response("Failed to find user associated to given pubkey")


@refbp.route("/api/header", methods=("GET", "POST"))
@limiter.exempt
def api_get_header():
    """Return the SSH welcome header + optional message-of-the-day."""
    resp = SystemSettingsManager.SSH_WELCOME_MSG.value
    msg_of_the_day = SystemSettingsManager.SSH_MESSAGE_OF_THE_DAY.value
    if msg_of_the_day:
        resp += f"\n{ansi.green(msg_of_the_day)}"
    return ok_response(resp)
