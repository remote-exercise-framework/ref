import datetime
import hashlib
import os
import re
import shutil
import tempfile
import typing
from collections import namedtuple
from pathlib import Path

import docker
import redis
import rq
import yaml
from flask import (Blueprint, Flask, current_app, jsonify, make_response,
                   redirect, render_template, request, url_for)
from itsdangerous import Serializer, TimedSerializer
from werkzeug.local import Local, LocalProxy

from ref import db, refbp
from ref.core import (ExerciseImageManager, ExerciseManager, InstanceManager,
                      flash, retry_on_deadlock)
from ref.model import (ConfigParsingError, Exercise, Instance, SystemSetting,
                       SystemSettingsManager, User)
from ref.model.enums import ExerciseBuildStatus
from wtforms import Form, IntegerField, SubmitField, validators

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
    log.info('Start for instance {instance} was requested.')

    #Check if the instances exercise image is build
    if not ExerciseImageManager(instance.exercise).is_build():
        log.error(f'User {instance.user} has an instance ({instance}) of an exercise that is not build. Possibly someone deleted the docker image?')
        return error_response('Inconsistent build state, please notify the system administrator')

    instance_manager = InstanceManager(instance)
    if not instance_manager.is_running():
        log.info(f'Instance ({instance}) is not running, starting...')
        instance_manager.start()

    try:
        ip = instance_manager.get_entry_ip()
    except:
        log.error('Failed to get IP of container, stopping instance')
        instance_manager.stop()
        raise

    log.info(f'IP of user container is {ip}')

    resp = {
        'ip': ip,
        'cmd': instance.exercise.entry_service.cmd
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

    #Make sure nobody messes with the instance or requesting user.
    with retry_on_deadlock():
        instance = Instance.query.filter(Instance.id == instance_id).with_for_update().one_or_none()
        user: User = User.query.filter(User.pub_key_ssh==pubkey).with_for_update().one_or_none()

    if not user:
        log.warning(f'Unknown with pubkey={pubkey}')
        raise Exception('Invalid user')

    if not SystemSettingsManager.INSTANCE_SSH_INTROSPECTION.value:
        m = f'Instance SSH introspection is disabled!'
        log.warning(m)
        raise Exception(m)

    if not user.is_admin:
        log.warning(f'Only admins are allowed to request specific instances')
        raise Exception('Insufficient permissions')

    if not instance:
        log.warning(f'Invalid instance_id={instance_id}')
        raise Exception('Invalid instance ID')

    return start_and_return_instance(instance)

@refbp.route('/api/provision', methods=('GET', 'POST'))
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
        log.warning('Got provision request without JSON body')
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
    pubkey = content.get('pubkey')
    if not pubkey:
        log.warning('Missing pubkey')
        return error_response('Invalid request')

    #The user name used for authentication
    exercise_name = content.get('username')
    if not exercise_name:
        log.warning('Missing username')
        return error_response('Invalid request')

    log.info(f'Got request from pubkey={pubkey:32}, exercise_name={exercise_name}')

    #Check whether a admin requested access to a specififc instance
    if exercise_name.startswith('instance-'):
        try:
            ret = handle_instance_introspection_request(exercise_name, pubkey)
            db.session.commit()
            return ret
        except Exception as e:
            return error_response(str(e))

    #Check if a specififc version was requested (admin only)
    exercise_version = re.findall(r"(.*)-v([0-9]+)", exercise_name)

    #Do we have a match?
    if exercise_version and len(exercise_version[0]) == 2:
        exercise_name = exercise_version[0][0]
        try:
            exercise_version = int(exercise_version[0][1])
        except ValueError:
            log.warning(f'Invalid version number', exc_info=True)
            return error_response('Invalid request')
    else:
        exercise_version = None
    log.info(f'Request for exercise {exercise_name} version {exercise_version} for user {pubkey:32} was requested')

    if exercise_version is not None and not SystemSettingsManager.INSTANCE_NON_DEFAULT_PROVISIONING.value:
        log.warning('None default provisioning is disabled')
        return error_response('None default provisioning is disabled')

    #Try to lock all DB rows we are going to work with
    with retry_on_deadlock():
        #Get the user account
        user: User = User.query.filter(User.pub_key_ssh==pubkey).with_for_update().one_or_none()
        if not user:
            log.warning('Unable to find user with provided publickey')
            return error_response('Unknown public-key')

        log.info(f'Found matching user: {user}')

        #If we are in maintenance, reject connections from normal users.
        if current_app.config['MAINTENANCE_ENABLED'] and not user.is_admin:
            log.info('Rejecting connection since maintenance mode is enabled and user is no admin')
            return error_response('-------------------\nSorry, maintenance mode is enabled.\nPlease try again later.\n-------------------')

        if not Exercise.query.filter(Exercise.short_name == exercise_name).all():
            log.info('Failed to find exercise with requested name')
            return error_response('No such task')

        if exercise_version is not None and user.is_admin:
            #Admin users are allowed to request instances of exercises that are not set as default
            requested_exercise = Exercise.get_exercise(exercise_name, exercise_version, for_update=True)
            if not requested_exercise:
                return error_response('Requested exercise does not exist!')
        elif exercise_version is not None:
            return error_response('Only admins are allowed to request a specific version')
        else:
            #Get the default exercise for the requested exercise name
            requested_exercise = Exercise.get_default_exercise(exercise_name, for_update=True)
            log.info(f'Default exercise for {exercise_name} is {requested_exercise}')
            if not requested_exercise:
                return error_response('There is no active default for the requested exercise')

        #Get the user instance of requested exercise_name (if any). This might have a different version then the
        #default.
        user_instances = list(filter(lambda instance: instance.exercise.short_name == exercise_name and not instance.is_submission, user.exercise_instances))
        for i in range(0, len(user_instances)):
            user_instances[i] = user_instances[i].refresh(lock=True)

    #user_instances contains all instance of the requested exercise_name (if any)

    #Do not provision submitted instances
    #FIXME: Implement
    #user_instances = list(filter(lambda instance: not instance.is_submission, user_instances))

    """
    If the user has an instance of the default version of the exercise or one that is more recent
    (i.e., has an high version number than the default) we return it. In case the instance has
    a lower version than the default, it will be updated below.
    If the user has no instance we continue and create one.
    """

    user_instance = None
    if exercise_version is not None:
        #The user requested a specific version
        user_instances = list(filter(lambda i: i.exercise.version == exercise_version, user_instances))
    else:
        #Get instance with same version or newer than the default
        user_instances = list(filter(lambda e: e.exercise == requested_exercise or e.exercise.version > requested_exercise.version, user_instances))

    if user_instances:
        user_instance = user_instances[0]

    if user_instance and (exercise_version is not None or (user_instance.exercise.version >= requested_exercise.version)):
        #We let instance with lower version number fallthrough, thus they get updated down below
        log.info(f'User has an instance of the requested exercise: {user_instance}')
        try:
            ret = start_and_return_instance(user_instance)
            db.session.commit()
            return ret
        except:
            raise

    """
    If we are here, one of the following statements is true:
        1. The user has no instance of the requested exercise (user_instance is None)
        2. The user has an instance, but it is older then the current default version.
    """

    if not ExerciseImageManager(requested_exercise).is_build():
        log.error(f'Exercise {requested_exercise} is marked as default, but is not build! Possibly someone deleted the docker image?')
        return error_response('Internal error, please notify the system administrator')

    new_instance = None
    if user_instance:
        #The user has an older version of the exercise, upgrade it.
        old_instance = user_instance
        log.info(f'Found an upgradeable instance. Upgrading {old_instance} to new version {requested_exercise}')
        mgr = InstanceManager(old_instance)
        try:
            new_instance = mgr.update_instance(requested_exercise)
        except:
            raise
    else:
        #The user has no instance of the exercise, create a new one.
        log.info(f'User has no instance of exercise {requested_exercise}, creating one...')
        try:
            new_instance = InstanceManager.create_instance(user, requested_exercise)
        except:
            raise

    try:
        ret = start_and_return_instance(new_instance)
    except:
        raise

    #Release locks and commit
    db.session.commit()

    log.info(f'returning {ret}')
    return ret


@refbp.route('/api/getkeys', methods=('GET', 'POST'))
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
        return error_response("Failed to find user with given pubkey")

@refbp.route('/api/header', methods=('GET', 'POST'))
def api_get_header():
    """
    Returns the header that is display when a user connects.
    """
    return ok_response(SystemSettingsManager.SSH_WELCOME_MSG.value)


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
        raise ('Request is missing JSON body')

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

    instance = Instance.query.filter(Instance.id == instance_id).with_for_update().one_or_none()
    if not instance:
        log.warning(f'Failed to find instance with ID {instance_id}')
        raise Exception("Unable to find given instance")

    instance_key = instance.get_key()

    s = TimedSerializer(instance_key, salt='from-container-to-web')
    try:
        signed_content = s.loads(content, max_age=60)
    except Exception as e:
        log.warning(f'Invalid request', exc_info=True)
        raise Exception('Invalid request')

    return signed_content


@refbp.route('/api/instance/reset', methods=('GET', 'POST'))
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

    log.info(f'Got reset request for instance_id={instance_id}')

    #Lock the instance and the user
    with retry_on_deadlock():
        instance = Instance.query.filter(Instance.id == instance_id).with_for_update().one_or_none()
        if not instance:
            log.warning(f'Invalid instance id {instance_id}')
            return error_response('Invalid request')

        user = User.query.filter(User.id == instance.user.id).with_for_update().one_or_none()
        if not user:
            log.warning(f'Invalid user ID {instance.user.id}')
            return error_response('Invalid request')

    mgr = InstanceManager(instance)
    mgr.reset()
    current_app.db.session.commit()

    return ok_response('OK')


@refbp.route('/api/instance/submit', methods=('GET', 'POST'))
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
        return error_response('Invalid instance ID')

    log.info(f'Got submit request for instance_id={instance_id}')

    #Lock the instance and the user
    with retry_on_deadlock():
        instance = Instance.query.filter(Instance.id == instance_id).with_for_update().one_or_none()
        if not instance:
            log.warning(f'Invalid instance id {instance_id}')
            return error_response('Invalid request')

        user = User.query.filter(User.id == instance.user.id).with_for_update().one_or_none()
        if not user:
            log.warning(f'Invalid user ID {instance.user.id}')
            return error_response('Invalid request')

    if instance.submission:
        log.warning(f'User tried to submit already submitted instance {instance}')
        return error_response('Unable to submit a submitted instance :-/')

    mgr = InstanceManager(instance)
    mgr.stop()
    new_instance = mgr.create_submission()
    log.info(f'Created submission: {new_instance.submission}')
    current_app.db.session.commit()

    return ok_response('OK')
