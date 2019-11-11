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

from ref import db, refbp
from ref.core import flash, ExerciseImageManager, ExerciseInstanceManager, ExerciseManager
from ref.model import ConfigParsingError, Exercise, Instance, User
from ref.model.enums import ExerciseBuildStatus

lerr = lambda msg: current_app.logger.error(msg)
linfo = lambda msg: current_app.logger.info(msg)
lwarn = lambda msg: current_app.logger.warning(msg)

def error_response(msg, code=400):
    msg = jsonify({'error': msg})
    return make_response(msg, code)

def ok_response(msg):
    msg = jsonify(msg)
    return make_response(msg, 200)

def start_and_return_instance(instance: Instance):
    #Check if the instances exercise image is build
    if not ExerciseImageManager(instance.exercise).is_build():
        lerr(f'User {instance.user} has an instance ({instance}) of an exercise that is not build. Possibly someone delete the docker image?')
        return error_response('Inconsistent build state, please notify the system administrator')

    instance_manager = ExerciseInstanceManager(instance)
    #Check if the instance is running
    running = instance_manager.is_running()
    if not running:
        linfo('Instance is not running, starting...')
        instance_manager.stop()
        instance_manager.start()

    ip = instance_manager.get_entry_ip()

    resp = {
        'ip': ip,
        'bind_executable': instance.exercise.entry_service.bind_executable
    }

    return ok_response(resp)

@refbp.route('/api/provision', methods=('GET', 'POST'))
def api_provision():
    """
    This API endpoint is used by the local ssh-server the students connect to.
    The request should contain the public-key used for authentication and the
    """
    if request.method == 'POST':
        #content = request.json
        #Params: username, public key
        content = request.get_json(force=True, silent=True)
        if not content:
            return error_response('Request is missing JSON body')

        exercise_name = content['username']
        pubkey = content['pubkey']

        linfo(f'exercise_name={exercise_name}')
        linfo(f'pubkey={pubkey[:32]}')

        user: User = db.get(User, pub_key_ssh=pubkey)
        if not user:
            lerr('Unknown user!')
            return error_response('Unknown public-key')

        linfo(f'User found {user}')

        if len(Exercise.query.filter(Exercise.short_name == exercise_name).all()) == 0:
            return error_response('No such task')

        #Get the default exercise for the requested exercise name
        default_exercise = Exercise.query.filter(Exercise.short_name == exercise_name).filter(Exercise.is_default == True).first()
        linfo(f'Default exercise for {exercise_name} is {default_exercise}')

        #Get the user instance of requested exercise name (if any)
        user_instances = user.exercise_instances
        user_instances = [i for i in user_instances if i.exercise.short_name == exercise_name]
        if len(user_instances) > 1:
            lerr(f'User {user} has more then one instance of the same exercise')
            return error_response('Internal error, please notify the system administrator')

        user_instance = None
        if len(user_instances):
            user_instance = user_instances[0]

        #If the user has an instance and there is no default for the requested exercise or
        #the instance is an "instance" of the default exercise, return it.
        if user_instance and (not default_exercise or user_instance.exercise == default_exercise or user_instance.exercise.version > default_exercise.version):
            linfo(f'User has an instance of the requested exercise ({user_instance})')
            return start_and_return_instance(user_instance)

        #If we are here, the user has no instance of the requested exercise.
        if not default_exercise:
            return error_response('There is no active default for the requested exercise')

        #The exercise that is the current default.
        #If an exercise is marked as default, it is guaranteed that there are no instances
        #of a more recent version of the exercise. Hence, if the user has another instance
        #of the requested exercise, it must be older.

        if not ExerciseImageManager(default_exercise).is_build():
            lerr(f'Exercise {default_exercise} is marked as default, but is not build! Possibly someone deleted the docker image?')
            return error_response('Internal error, please notify the system administrator')

        #Now we need to check if the user has an older version of the requested exercise that we need
        #to update.
        user_instances = user.exercise_instances
        user_instances = [i for i in user_instances if i.exercise.short_name == default_exercise.short_name]
        if len(user_instances) > 1:
            lerr(f'User {user} has more than 1 instance of exercise {default_exercise.short_name}')
            return error_response('Internal error, please notify the system administrator')

        new_instance = None
        if len(user_instances):
            #The user has an older version of the exercise, upgrade it!
            old_instance = user_instances[0]
            linfo(f'Found an upgradeable instance ({old_instance})')
            mgr = ExerciseInstanceManager(old_instance)
            new_instance = mgr.update_instance(default_exercise)
            db.session.commit()
        else:
            #The user has no older version of the exercise, create a new one
            linfo(f'User has no instance of exercise {default_exercise}, creating one...')
            new_instance = ExerciseInstanceManager.create_instance(user, default_exercise)
            db.session.add(new_instance)
            db.session.commit()

        return start_and_return_instance(new_instance)

    return error_response('POST expected')

@refbp.route('/api/getkeys', methods=('GET', 'POST'))
def api_getkeys():
    """
    Returns all public-keys that are allowed to login into the SSH server.
    """
    if request.method == 'POST':
        content = request.json
        students = User.query.all()
        keys = []
        for s in students:
            keys.append(s.pub_key_ssh)
        resp = {
            'keys': keys
        }
        linfo(f'Returning {len(keys)} public-keys in total.')
        return ok_response(resp)

    return error_response('POST expected')

@refbp.route('/api/getuserinfo', methods=('GET', 'POST'))
def api_getuserinfo():
    """
    Returns userinfo based on a provided public-key.
    """
    if request.method == 'POST':
        content = request.json
        pubkey = content['pubkey']
        linfo(f'pubkey={pubkey[:32]}')
        student = db.get(User, pub_key_ssh=pubkey)
        if student:
            resp = {
                'name': student.first_name + " " + student.surname,
                'mat_num': student.mat_num
            }
            return ok_response(resp)
        else:
            return error_response("Failed to find student with given pubkey")

        return ok_response(resp)

    return error_response('POST expected')


def api_request_restart():
    pass