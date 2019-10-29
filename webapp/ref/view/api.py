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
from ref.model import ConfigParsingError, Exercise, ExerciseInstance, User
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

@refbp.route('/api/provision', methods=('GET', 'POST'))
def api_provision():
    """
    This API endpoint is used by the local ssh-server the students connect to.
    The request should contain the public-key used for authentication and the
    """
    if request.method == 'POST':
        #content = request.json
        #Params: username, public key
        content = request.json
        exercise_name = content['username']
        pubkey = content['pubkey']

        linfo(f'exercise_name={exercise_name}')
        linfo(f'pubkey={pubkey[:32]}')

        user = db.get(User, pub_key_ssh=pubkey)
        if not user:
            return error_response('Unknown public-key')

        exercises = Exercise.query.filter(Exercise.short_name == exercise_name).all()
        if len(exercises) == 0:
            return error_response('No such task')

        exercises = list(filter(lambda e: e.is_default, exercises))
        if len(exercises) != 1:
            return error_response('There is no active default for the given exercise')
        exercise = exercises[0]

        if exercise.build_job_status != ExerciseBuildStatus.FINISHED:
            return error_response('The given task was not build, please notify the system administrator')

        if not ExerciseImageManager(exercise).is_build():
            return error_response('Inconsistent build state, please notify the system administrator')

        #Check if there is an instance for the user that is requesting an instance
        instances = ExerciseManager(exercise).get_instances()
        instance = None
        for i in instances:
            if i.user == user:
                instance = i

        if instance:
            linfo('User already has an instance')
            #return error_response('There is an instance')
        else:
            linfo('Creating a new instance')
            instance = ExerciseInstanceManager.create_instance(user, exercise)
            exercise.instances.append(instance)
            db.session.add(exercise)
            db.session.commit()

        instance_manager = ExerciseInstanceManager(instance)
        #Check if the instance is running
        running = instance_manager.is_running()
        if not running:
            linfo('Instance is not running, starting...')
            instance_manager.stop()
            instance_manager.start()

        ip = instance_manager.get_entry_ip()

        resp = {
            'ip': ip
        }

        return ok_response(resp)

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