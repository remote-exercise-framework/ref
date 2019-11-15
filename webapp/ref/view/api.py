import datetime
import os
import shutil
import tempfile
import typing
from collections import namedtuple
from pathlib import Path
import hashlib
import docker
import redis
import rq
import yaml
from flask import (Blueprint, Flask, current_app, jsonify, make_response,
                   redirect, render_template, request, url_for)
from wtforms import Form, IntegerField, SubmitField, validators

from werkzeug.local import LocalProxy, Local

from ref import db, refbp
from ref.core import flash, ExerciseImageManager, ExerciseInstanceManager, ExerciseManager
from ref.model import ConfigParsingError, Exercise, Instance, User
from ref.model.enums import ExerciseBuildStatus

from itsdangerous import Serializer

log = LocalProxy(lambda: current_app.logger)

def error_response(msg, code=400):
    msg = jsonify({'error': msg})
    return make_response(msg, code)

def ok_response(msg):
    msg = jsonify(msg)
    return make_response(msg, 200)

def start_and_return_instance(instance: Instance):
    #Check if the instances exercise image is build
    if not ExerciseImageManager(instance.exercise).is_build():
        log.error(f'User {instance.user} has an instance ({instance}) of an exercise that is not build. Possibly someone deleted the docker image?')
        return error_response('Inconsistent build state, please notify the system administrator')

    instance_manager = ExerciseInstanceManager(instance)
    #Check if the instance is running
    running = instance_manager.is_running()
    if not running:
        log.info(f'Instance ({instance}) is not running, starting...')
        instance_manager.stop()
        instance_manager.start()

    ip = instance_manager.get_entry_ip()
    log.info(f'IP of user container is {ip}')

    resp = {
        'ip': ip,
        'bind_executable': instance.exercise.entry_service.bind_executable
    }

    return ok_response(resp)

@refbp.route('/api/provision', methods=('GET', 'POST'))
def api_provision():
    """
    Request a instance of a specific exercise for a certain user.
    This endpoint is called by the SSH entry server and is used to
    decide how an incoming connection should be redirected, .i.e.,
    getting the IP address of the container the belongs to the requesting
    user.
    """
    content = request.get_json(force=True, silent=True)
    if not content:
        log.warning('Got provision request without JSON body')
        return error_response('Request is missing JSON body')

    #Check for valid signature
    s = Serializer(current_app.config['SECRET_KEY'])

    #These are the arguments send by the SSH entry server

    #The user name used for authentication
    exercise_name = content['username']

    #The public key the user used to authenticate
    pubkey = content['pubkey']

    log.info(f'Request for exercise {exercise_name} for user {pubkey:32} was requested')

    user: User = db.get(User, pub_key_ssh=pubkey)
    if not user:
        log.warning('Unable to find user with provided publickey')
        return error_response('Unknown public-key')

    log.info(f'Found matching user: {user}')

    #If we are in maintenance, reject connections from normal users.
    if current_app.config['MAINTENANCE_ENABLED'] and not user.is_admin:
        log.info('Rejecting connection since maintenance mode is enabled and user is no admin')
        return error_response('-------------------\nSorry, maintenance mode is enabled.\nPlease try again later.\n-------------------')

    if len(Exercise.query.filter(Exercise.short_name == exercise_name).all()) == 0:
        log.info('Failed to find exercise with requested name')
        return error_response('No such task')

    #Get the default exercise for the requested exercise name
    default_exercise = Exercise.get_default_exercise(exercise_name)
    log.info(f'Default exercise for {exercise_name} is {default_exercise}')

    #Consistency check
    #Get the user instance of requested exercise name (if any). This might have a different version then the
    #default.
    user_instances = list(filter(lambda instance: instance.exercise.short_name == exercise_name, user.exercise_instances))
    if len(user_instances) > 1:
        log.error(f'User {user} has more then one instance of the same exercise')
        return error_response('Internal error, please notify the system administrator')

    user_instance = None
    if len(user_instances):
        user_instance = user_instances[0]

    """
    If the user has an instance of the default verison of the exercise or one that is more recent
    (i.e., has an high version number than the default) we return it. In case the instance has
    a lower version than the default, we fall through, since it needs to be updated. Furthermore,
    if the user has no instance, we also continue to create one.
    """
    if user_instance and (not default_exercise or user_instance.exercise == default_exercise or user_instance.exercise.version > default_exercise.version):
        log.info(f'User has an instance of the requested exercise: {user_instance}')
        return start_and_return_instance(user_instance)

    '''
    If we are here, one of the following statements is true:
        1. The user has no instance of the requested exercise.
        2. The user has an instance, but is is older then the current default version.
    '''

    if not default_exercise:
        return error_response('There is no active default for the requested exercise')

    if not ExerciseImageManager(default_exercise).is_build():
        log.error(f'Exercise {default_exercise} is marked as default, but is not build! Possibly someone deleted the docker image?')
        return error_response('Internal error, please notify the system administrator')

    new_instance = None
    if user_instance:
        #The user has an older version of the exercise, upgrade it.
        old_instance = user_instance
        log.info(f'Found an upgradeable instance. Upgrading {old_instance} to new version {default_exercise}')
        mgr = ExerciseInstanceManager(old_instance)
        new_instance = mgr.update_instance(default_exercise)
        db.session.commit()
    else:
        #The user has no instance of the exercise, create a new one.
        log.info(f'User has no instance of exercise {default_exercise}, creating one...')
        new_instance = ExerciseInstanceManager.create_instance(user, default_exercise)
        db.session.add(new_instance)
        db.session.commit()

    return start_and_return_instance(new_instance)



@refbp.route('/api/getkeys', methods=('GET', 'POST'))
def api_getkeys():
    """
    Returns all public-keys that are allowed to login into the SSH entry server.
    """
    content = request.get_json(force=True, silent=True)
    if not content:
        return error_response('Missing JSON body in request')

    #Check for valid signature
    s = Serializer(current_app.config['SECRET_KEY'])

    if 'username' not in content:
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
    # s = Serializer(current_app.config['SECRET_KEY'])
    # try:
    #     content = s.loads(content)
    # except Exception as e:
    #     log.warning(f'Invalid request {e}')
    #     return error_response('Invalid request')

    if not 'pubkey' in content:
        log.warning('Got request without pubkey attribute')
        return error_response('Invalid request')

    pubkey = content['pubkey']
    log.info(f'Got request for pubkey={pubkey[:32]}')
    user = db.get(User, pub_key_ssh=pubkey)

    if user:
        log.info('Found matching user: {user}')
        resp = {
            'name': user.first_name + " " + user.surname,
            'mat_num': user.mat_num
        }
        return ok_response(resp)
    else:
        log.info('User not found')
        return error_response("Failed to find user with given pubkey")

def api_request_restart():
    pass