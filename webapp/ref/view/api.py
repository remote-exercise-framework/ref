import datetime
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import typing
from collections import namedtuple
from pathlib import Path

import arrow
import docker
import redis
import rq
import yaml
from flask import (Blueprint, Flask, abort, current_app, jsonify,
                   make_response, redirect, render_template, request, url_for)
from itsdangerous import Serializer, TimedSerializer
from werkzeug.local import Local, LocalProxy
from wtforms import Form, IntegerField, SubmitField, validators

from ref import db, limiter, refbp
from ref.core import AnsiColorUtil as ansi
from ref.core import (ExerciseImageManager, ExerciseManager,
                      InconsistentStateError, InstanceManager,
                      datetime_to_local_tz, datetime_to_string, flash,
                      retry_on_deadlock)
from ref.core.util import lock_db
from ref.model import (ConfigParsingError, Exercise, Instance, SystemSetting,
                       SystemSettingsManager, User)
from ref.model.enums import ExerciseBuildStatus

log = LocalProxy(lambda: current_app.logger)

def error_response(msg, code=400):
    msg = jsonify({'error': msg})
    return msg, code

def ok_response(msg):
    msg = jsonify(msg)
    return msg, 200

def start_and_return_instance(instance: Instance):
    """
    Returns the ip and default command (that should be executed on connect) of the given instance.
    In case the instance is not running, it is started.
    In case some operation fails, the function returns a description of the error
    using error_response().
    """
    log.info(f'Start of instance {instance} was requested.')

    #Check if the instances exercise image is build
    if not ExerciseImageManager(instance.exercise).is_build():
        log.error(f'User {instance.user} has an instance ({instance}) of an exercise that is not built. Possibly someone deleted the docker image?')
        return error_response('Inconsistent build state! Please notify the system administrator immediately')

    instance_manager = InstanceManager(instance)
    if not instance_manager.is_running():
        log.info(f'Instance ({instance}) is not running. Starting..')
        instance_manager.start()

    try:
        ip = instance_manager.get_entry_ip()
    except:
        log.error('Failed to get IP of instance. Stopping instance..', exc_info=True)
        instance_manager.stop()
        raise

    exercise: Exercise = instance.exercise

    #Message that is printed before the user is dropped into the container shell.
    welcome_message = ''

    if not instance.is_submission():
        latest_submission = instance.get_latest_submission()
        if not exercise.has_deadline():
            pass
        elif not latest_submission:
            welcome_message += (
                '    Last submitted: (No submission found)\n'
            )
        else:
            ts = datetime_to_local_tz(latest_submission.submission_ts)
            since_in_str = arrow.get(ts).humanize()
            ts = ts.strftime('%A, %B %dth @ %H:%M')
            welcome_message += (
                f'    Last submitted: {ts} ({since_in_str})\n'
            )
    else:
        ts = datetime_to_local_tz(instance.submission.submission_ts)
        since_in_str = arrow.get(ts).humanize()
        ts = ts.strftime('%A, %B %dth @ %H:%M')
        user_name = instance.user.full_name
        welcome_message += f'    This is a submission from {ts} ({since_in_str})\n'
        welcome_message += f'    User     : {user_name}\n'
        welcome_message += f'    Exercise : {exercise.short_name}\n'
        welcome_message += f'    Version  : {exercise.version}\n'
        if instance.is_modified():
            welcome_message += ansi.red('    This submission was modified!\n    Use `task reset` to restore the initially submitted state.\n')

    if exercise.has_deadline():
        ts = datetime_to_local_tz(exercise.submission_deadline_end)
        since_in_str = arrow.get(ts).humanize()
        deadline = ts.strftime('%A, %B %dth @ %H:%M')
        if exercise.deadine_passed():
            msg = f'    Deadline: Passed on {deadline} ({since_in_str})\n'
            welcome_message += ansi.red(msg)
        else:
            welcome_message += f'    Deadline: {deadline} ({since_in_str})\n'

    #trim trailing newline
    welcome_message = welcome_message.rstrip()
    log.info(f'IP of user instance is {ip}')

    resp = {
        'ip': ip,
        'cmd': instance.exercise.entry_service.cmd,
        'welcome_message': welcome_message
    }

    return ok_response(resp)

def handle_instance_introspection_request(exercise_name, pubkey):
    """
    Handeles deploy request that are targeting a specific instances.
    This feature allows, e.g., admin users to connect to an arbitrary
    instance using 'instance-<INSTANCE_ID>' as exercise name during
    authentication.
    On error an 'Exception' is raised containing a string that can be provided
    to the requesting user as error message.
    """
    #The ID of the requested instance
    instance_id = re.findall(r"^instance-([0-9]+)", exercise_name)
    try:
        instance_id = int(instance_id[0])
    except:
        log.warning(f'Invalid instance ID {instance_id}', exc_info=True)
        raise Exception('Invalid request')

    instance: Instance = Instance.query.filter(Instance.id == instance_id).one_or_none()
    user: User = User.query.filter(User.pub_key_ssh==pubkey).one_or_none()

    if not user:
        log.warning('User not found.')
        return error_response('Unknown user.')

    if not SystemSettingsManager.INSTANCE_SSH_INTROSPECTION.value:
        m = f'Instance SSH introspection is disabled!'
        log.warning(m)
        return error_response('Introspection is disabled.')

    if not user.is_admin and not user.is_grading_assistant:
        log.warning(f'Only administrators and grading assistants are allowed to request access to specific instances.')
        return error_response('Insufficient permissions')

    if not instance:
        log.warning(f'Invalid instance_id={instance_id}')
        return error_response('Invalid instance ID')

    if not instance.is_submission() and not user.is_admin:
        return error_response('Insufficient permissions.')

    return start_and_return_instance(instance)

@refbp.route('/api/provision', methods=('GET', 'POST'))
@limiter.exempt
def api_provision():
    """
    Request a instance of a specific exercise for a certain user.
    This endpoint is called by the SSH entry server and is used to
    decide how an incoming connection should be handeled. This means basically
    to decide whether it is necessary to create a new instance for the user,
    or if he already has one to which the connection just needs to be forwarded.
    This function might be called concurrently.
    """
    content = request.get_json(force=True, silent=True)
    if not content:
        log.warning('Received provision request without JSON body')
        return error_response('Request is missing JSON body')

    #Check for valid signature and valid request type
    s = Serializer(current_app.config['SSH_TO_WEB_KEY'])
    try:
        content = s.loads(content)
    except Exception as e:
        log.warning(f'Invalid request {e}')
        return error_response('Invalid request')

    if not isinstance(content, dict):
        log.warning(f'Unexpected data type {type(content)}')
        return error_response('Invalid request')

    #Parse request args

    #The public key the user used to authenticate
    pubkey = content.get('pubkey', None)
    if not pubkey:
        log.warning('Missing pubkey')
        return error_response('Invalid request')

    #The user name used for authentication
    exercise_name = content.get('exercise_name', None)
    if not exercise_name:
        log.warning('Missing exercise_name')
        return error_response('Invalid request')

    #exercise_name is user provided, make sure it is valid UTF8.
    #If its not, sqlalchemy will raise an unicode error.
    try:
        exercise_name.encode()
    except Exception as e:
        log.error(f'Invalid exercise name {str(e)}')
        return error_response('Requested task not found')

    #Now it is safe to use exercise_name
    log.info(f'Got request from pubkey={pubkey:32}, exercise_name={exercise_name}')

    #Get the user account
    with retry_on_deadlock():
        user: User = User.query.filter(User.pub_key_ssh==pubkey).one_or_none()
        if not user:
            log.warning('Unable to find user with provided publickey')
            return error_response('Unknown public key')

    #If we are in maintenance, reject connections from normal users.
    if (SystemSettingsManager.MAINTENANCE_ENABLED.value) and not user.is_admin:
        log.info('Rejecting connection since maintenance mode is enabled and user is not an administrator')
        return error_response('-------------------\nSorry, maintenance mode is enabled.\nPlease try again later.\n-------------------')

    #Check whether a admin requested access to a specififc instance
    if exercise_name.startswith('instance-'):
        try:
            ret = handle_instance_introspection_request(exercise_name, pubkey)
            db.session.commit()
            return ret
        except:
            raise

    exercise_version = None
    if '@' in exercise_name:
        if not SystemSettingsManager.INSTANCE_NON_DEFAULT_PROVISIONING.value:
            return error_response('Settings: Non-default provisioning is not allowed')
        if not user.is_admin:
            return error_response('Insufficient permissions: Non-default provisioning is only allowed for admins')
        exercise_name = exercise_name.split('@')
        exercise_version = exercise_name[1]
        exercise_name = exercise_name[0]

    with retry_on_deadlock():
        user: User = User.query.filter(User.pub_key_ssh==pubkey).one_or_none()
        if not user:
            log.warning('Unable to find user with provided publickey')
            return error_response('Unknown public key')

        if exercise_version is not None:
            requested_exercise = Exercise.get_exercise(exercise_name, exercise_version, for_update=True)
        else:
            requested_exercise = Exercise.get_default_exercise(exercise_name, for_update=True)
        log.info(f'Requested exercise is {requested_exercise}')
        if not requested_exercise:
            return error_response('Requested task not found')

    user_instances = list(filter(lambda e: e.exercise.short_name == requested_exercise.short_name, user.exercise_instances))
    #Filter submissions
    user_instances = list(filter(lambda e: not e.submission, user_instances))

    #If we requested a version, remove all instances that do not match
    if exercise_version is not None:
        user_instances = list(filter(lambda e: e.exercise.version == exercise_version, user_instances))

    #Highest version comes first
    user_instances = sorted(user_instances, key=lambda e: e.exercise.version, reverse=True)
    user_instance = None

    if user_instances:
        log.info(f'User has instance {user_instances} of requested exercise')
        user_instance = user_instances[0]
        #Make sure we are not dealing with a submission here!
        assert not user_instance.submission
        if exercise_version is None and user_instance.exercise.version < requested_exercise.version:
            old_instance = user_instance
            log.info(f'Found an upgradeable instance. Upgrading {old_instance} to new version {requested_exercise}')
            mgr = InstanceManager(old_instance)
            user_instance = mgr.update_instance(requested_exercise)
            mgr.bequeath_submissions_to(user_instance)

            try:
                db.session.begin_nested()
                mgr.remove()
            except Exception as e:
                #Remove failed, do not commit the changes to the DB.
                db.session.rollback()
                #Commit the new instance to the DB.
                db.session.commit()
                raise InconsistentStateError('Failed to remove old instance after upgrading.') from e
            else:
                db.session.commit()
    else:
        user_instance = InstanceManager.create_instance(user, requested_exercise)

    ret = start_and_return_instance(user_instance)

    db.session.commit()
    return ret

@refbp.route('/api/getkeys', methods=('GET', 'POST'))
@limiter.exempt
def api_getkeys():
    """
    Returns all public-keys that are allowed to login into the SSH entry server.
    """
    content = request.get_json(force=True, silent=True)
    if not content:
        return error_response('Missing JSON body in request')

    #Check for valid signature and unpack
    s = Serializer(current_app.config['SSH_TO_WEB_KEY'])
    try:
        content = s.loads(content)
    except Exception as e:
        log.warning(f'Invalid request {e}')
        return error_response('Invalid request')

    if not isinstance(content, dict):
        log.warning(f'Unexpected data type {type(content)}')
        return error_response('Invalid request')

    username = content.get('username')
    if not username:
        log.warning('Missing username attribute')
        return error_response('Invalid request')

    students = User.all()
    keys = []
    for s in students:
        keys.append(s.pub_key_ssh)

    resp = {
        'keys': keys
    }
    log.info(f'Returning {len(keys)} public-keys in total.')
    return ok_response(resp)


@refbp.route('/api/getuserinfo', methods=('GET', 'POST'))
@limiter.exempt
def api_getuserinfo():
    """
    Returns info of the user that is associated with the provided public-key.
    """
    content = request.get_json(force=True, silent=True)
    if not content:
        log.warning('Missing JSON body')
        return error_response('Missing JSON body in request')

    #Check for valid signature and unpack
    s = Serializer(current_app.config['SSH_TO_WEB_KEY'])
    try:
        content = s.loads(content)
    except Exception as e:
        log.warning(f'Invalid request {e}')
        return error_response('Invalid request')

    if not isinstance(content, dict):
        log.warning(f'Unexpected data type {type(content)}')
        return error_response('Invalid request')

    pubkey = content.get('pubkey')
    if not pubkey:
        log.warning('Got request without pubkey attribute')
        return error_response('Invalid request')

    log.info(f'Got request for pubkey={pubkey[:32]}')
    user = db.get(User, pub_key_ssh=pubkey)

    if user:
        log.info(f'Found matching user: {user}')
        resp = {
            'name': user.first_name + " " + user.surname,
            'mat_num': user.mat_num
        }
        return ok_response(resp)
    else:
        log.info('User not found')
        return error_response("Failed to find user associated to given pubkey")

@refbp.route('/api/header', methods=('GET', 'POST'))
@limiter.exempt
def api_get_header():
    """
    Returns the header that is display when a user connects.
    """
    resp = SystemSettingsManager.SSH_WELCOME_MSG.value
    msg_of_the_day = SystemSettingsManager.SSH_MESSAGE_OF_THE_DAY.value
    if msg_of_the_day:
        msg_of_the_day = ansi.green(msg_of_the_day)
        resp += f'\n{msg_of_the_day}'
    return ok_response(resp)


def _sanitize_container_request(request, max_age=60) -> str:
    """
    Requests send by a container must have the following structure:
    {
        'instance_id': int #Used only for lookup to generate the key used for auth.
        'data': { # Data signed using a key that is specific to instance_id
            'instance_id': # Signed version of instance_id !!! MUST BE COMPARED TO THE OUTER instance_id !!!
            ... # Request specific data
        }
    }
    """
    content = request.get_json(force=True, silent=True)
    if not content:
        log.warning('Got request without JSON body')
        raise Exception('Request is missing JSON body')

    if not isinstance(content, str):
        log.warning(f'Invalid type {type(content)}')
        raise Exception('Invalid request')

    s = TimedSerializer(b"", salt='from-container-to-web')
    try:
        _, unsafe_content = s.loads_unsafe(content)
    except:
        log.warning(f'Failed to decode payload', exc_info=True)
        raise Exception('Error during decoding')

    #This instance ID (['instance_id']) is just used to calculate the signature (['data']),
    #thus we do not have to iterate over all instance. After checking the signature,
    #this id must be compared to signed one (['data']['instance_id']).
    instance_id = unsafe_content.get('instance_id')
    if instance_id is None:
        log.warning('Missing instance_id')
        raise Exception('Missing instance_id')

    try:
        instance_id = int(instance_id)
    except:
        log.warning(f'Failed to convert {instance_id} to int', exc_info=True)
        raise Exception('Invalid instance ID')

    instance = Instance.query.filter(Instance.id == instance_id).one_or_none()
    if not instance:
        log.warning(f'Failed to find instance with ID {instance_id}')
        raise Exception("Unable to find given instance")

    instance_key = instance.get_key()

    s = TimedSerializer(instance_key, salt='from-container-to-web')
    try:
        signed_content = s.loads(content, max_age=max_age)
    except Exception as e:
        log.warning(f'Invalid request', exc_info=True)
        raise Exception('Invalid request')

    return signed_content


@refbp.route('/api/instance/reset', methods=('GET', 'POST'))
@limiter.limit('3 per minute; 24 per day')
def api_instance_reset():
    """
    Reset the instance with the given instance ID.
    This function expects the following signed data structure:
    {
        'instance_id': <ID>
    }
    """
    try:
        content = _sanitize_container_request(request)
    except Exception as e:
        return error_response(str(e))

    instance_id = content.get('instance_id')
    try:
        instance_id = int(instance_id)
    except ValueError:
        log.warning(f'Invalid instance id {instance_id}', exc_info=True)
        return error_response('Invalid instance ID')

    log.info(f'Received reset request for instance_id={instance_id}')

    #Lock the instance and the user
    with retry_on_deadlock():
        instance = Instance.query.filter(Instance.id == instance_id).one_or_none()
        if not instance:
            log.warning(f'Invalid instance id {instance_id}')
            return error_response('Invalid request')

        user = User.query.filter(User.id == instance.user.id).one_or_none()
        if not user:
            log.warning(f'Invalid user ID {instance.user.id}')
            return error_response('Invalid request')

    mgr = InstanceManager(instance)
    mgr.reset()
    current_app.db.session.commit()

    return ok_response('OK')


@refbp.route('/api/instance/submit', methods=('GET', 'POST'))
@limiter.limit('3 per minute; 24 per day')
def api_instance_submit():
    """
    Creates a submission of the instance with the given instance ID.
    This function expects the following signed data structure:
    {
        'instance_id': <ID>
    }
    """
    try:
        content = _sanitize_container_request(request)
    except Exception as e:
        return error_response(str(e))

    instance_id = content.get('instance_id')
    try:
        instance_id = int(instance_id)
    except ValueError:
        log.warning(f'Invalid instance id {instance_id}', exc_info=True)
        abort(400)

    log.info(f'Got submit request for instance_id={instance_id}')

    try:
        test_log = content['test_log']
        # Apparently postgres does not like \x00 bytes in strings,
        # hence we replace them by a printable error mark.
        test_log = test_log.replace("\x00", "\uFFFD")
        test_ret = int(content['test_ret'])
    except:
        log.warning('Invalid request', exc_info=True)
        abort(400)

    instance = Instance.query.filter(Instance.id == instance_id).one_or_none()
    if not instance:
        log.warning(f'Invalid instance id {instance_id}')
        return error_response('Invalid request')

    user = User.query.filter(User.id == instance.user.id).one_or_none()
    if not user:
        log.warning(f'Invalid user ID {instance.user.id}')
        return error_response('Invalid request')

    if instance.submission:
        log.warning(f'User tried to submit instance that is already submitted: {instance}')
        return error_response('Unable to submit: Instance is a submission itself.')

    if not instance.exercise.has_deadline():
        log.info(f'User tried to submit instance {instance} without deadline')
        return error_response(f'Unable to submit: This is an un-graded, open-end exercise rather than an graded assignment. Use "task check" to receive feedback.')

    if instance.exercise.deadine_passed():
        log.info(f'User tried to submit instance {instance} after deadline :-O')
        deadline = datetime_to_string(instance.exercise.submission_deadline_end)
        return error_response(f'Unable to submit: The submission deadline already passed (was due before {deadline})')

    if SystemSettingsManager.SUBMISSION_DISABLED.value:
        log.info(f'Rejecting submission request since submission is currently disabled.')
        return error_response(f'Submission is currently disabled, please try again later.')

    mgr = InstanceManager(instance)

    # This will stop the instance the submission was initiated from.
    # If the commit down below fails, the user does not receive any feedback
    # about the error!
    new_instance = mgr.create_submission(test_ret, test_log)

    current_app.db.session.commit()
    log.info(f'Created submission: {new_instance.submission}')

    return ok_response(f'[+] Submission with ID {new_instance.id} successfully created!')

@refbp.route('/api/instance/info', methods=('GET', 'POST'))
@limiter.limit('10 per minute')
def api_instance_info():
    """
    {
        'instance_id': <ID>
    }
    """
    try:
        content = _sanitize_container_request(request)
    except Exception as e:
        return error_response(str(e))

    instance_id = content.get('instance_id')
    try:
        instance_id = int(instance_id)
    except ValueError:
        log.warning(f'Invalid instance id {instance_id}', exc_info=True)
        return error_response('Invalid instance ID')

    log.info(f'Received info request for instance_id={instance_id}')

    instance: Instance = Instance.query.filter(Instance.id == instance_id).one_or_none()
    if not instance:
        log.warning(f'Invalid instance id {instance_id}')
        return error_response('Invalid request')

    user = instance.user
    exercise = instance.exercise

    ret = ''
    type_ = 'Submission' if instance.submission else 'Instance'
    user_name = instance.user.full_name

    ret += f'Type     : {type_}\n'
    ret += f'User     : {user_name}\n'
    ret += f'Exercise : {exercise.short_name}\n'
    ret += f'Version  : {exercise.version}\n'

    ret = ret.rstrip()

    return ok_response(ret)


# @refbp.route('/api/instance/diff', methods=('GET', 'POST'))
# @limiter.limit('6 per minute')
# def api_instance_diff():
#     """
#     Reset the instance with the given instance ID.
#     This function expects the following signed data structure:
#     {
#         'instance_id': <ID>
#     }
#     """
#     try:
#         content = _sanitize_container_request(request)
#     except Exception as e:
#         return error_response(str(e))

#     instance_id = content.get('instance_id')
#     try:
#         instance_id = int(instance_id)
#     except ValueError:
#         log.warning(f'Invalid instance id {instance_id}', exc_info=True)
#         return error_response('Invalid instance ID')

#     log.info(f'Received diff request for instance_id={instance_id}')

#     instance = Instance.get(instance_id)
#     if not instance:
#         log.warning(f'Invalid instance id {instance_id}')
#         return error_response('Invalid request')

#     submission = instance.get_latest_submission()
#     if not submission:
#         log.info('Instance has no submission')
#         return error_response('There is no submission to diff against. Use `task submit` to create a submission.')

#     submitted_state_path = submission.submitted_instance.entry_service.overlay_submitted
#     current_state_path = instance.entry_service.overlay_merged

#     prefix = os.path.commonpath([submitted_state_path, current_state_path])
#     log.info(f'prefix={prefix}')

#     submitted_state_path = submitted_state_path.replace(prefix, '')
#     current_state_path = current_state_path.replace(prefix, '')

#     cmd = f'diff -N -r -u -p --exclude=Dockerfile-entry -U 5 .{submitted_state_path} .{current_state_path}'
#     log.info(f'Running cmd: {cmd}')
#     p = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=prefix)
#     # if p.returncode == 2:
#     #     log.error(f'Failed to run. {p.stderr.decode()}')
#     #     abort(500)
#     diff = p.stdout.decode()

#     return ok_response(diff)
