import datetime
import os
import shutil
import tempfile
import typing
from collections import namedtuple
from pathlib import Path


from ref.core.util import redirect_to_next
import docker
import urllib
import redis
from werkzeug.urls import url_parse
import rq
import yaml
from flask import (Blueprint, Flask, abort, current_app, redirect,
                   render_template, request, url_for)
from wtforms import Form, IntegerField, SubmitField, validators

from ref import db, refbp
from ref.core import (ExerciseConfigError, admin_required,
                      ExerciseImageManager, ExerciseManager, flash, ExerciseInstanceManager)
from ref.model import ConfigParsingError, Exercise, User, Instance, ExerciseEntryService
from ref.model.enums import ExerciseBuildStatus

lerr = lambda msg: current_app.logger.error(msg)
linfo = lambda msg: current_app.logger.info(msg)
lwarn = lambda msg: current_app.logger.warning(msg)

def get_newest_exercise_version(exercise: Exercise):
    exercises = Exercise.query.filter(Exercise.short_name == exercise.short_name).all()
    new_exercise = list(filter(lambda e: e.version > exercise.version, exercises))
    if len(new_exercise):
        return max(new_exercise, key=lambda e: e.version)
    else:
        return None

@refbp.route('/instances/update/<int:instance_id>')
@admin_required
def instance_update(instance_id):
    instance: Instance =  Instance.query.filter(Instance.id == instance_id).first()
    if not instance:
        flash.error(f'Unknown instance ID {instance_id}')
        return render_template('400.html'), 400

    new_exercise: Exercise = get_newest_exercise_version(instance.exercise)
    if not new_exercise:
        flash.error(f'There is no new version for this exercise')
        return render_template('400.html'), 400

    mgr = ExerciseInstanceManager(instance)
    new_instance = mgr.update_instance(new_exercise)

    current_app.db.session.commit()
    return redirect_to_next()

@refbp.route('/instances/view/<int:instance_id>')
@admin_required
def instances_view_details(instance_id):
    instance =  Instance.query.filter(Instance.id == instance_id).first()
    if not instance:
        flash.error(f'Unknown instance ID {instance_id}')
        return render_template('400.html'), 400

    return render_template('instance_view_details.html', instance=instance)

def _instances_render_view(instances, title=None):

    #Set attributes used by the UI.
    for i in instances:
        running = ExerciseInstanceManager(i).is_running()
        setattr(i, 'running', running)

        new_exercise = get_newest_exercise_version(i.exercise)
        setattr(i, 'new_exercise', new_exercise)

    return render_template('instances_view_list.html', title=title, instances=instances)

@refbp.route('/instances/view/by-user/<int:user_id>')
@admin_required
def instances_by_user_id(user_id):
    user = User.get(user_id)
    if not user:
        flash.error(f'Invalid user id')
        return render_template('400.html'), 400

    instances = Instance.get_by_user(user_id)

    title=f'Instances of user {user.full_name} (#{user.id})'
    return _instances_render_view(instances, title=title)


@refbp.route('/instances/view/by-exercise/<string:exercise_name>')
@admin_required
def instances_view_by_exercise(exercise_name):
    try:
        exercise_name = urllib.parse.unquote_plus(exercise_name)
    except Exception as e:
        flash.error(f'Invalid exercise name')
        return render_template('400.html'), 400

    exercise_version = request.args.get('exercise_version')
    if exercise_version:
        try:
            exercise_version = int(exercise_version)
        except (ValueError, TypeError):
            flash.error(f'Invalid exercise version')
            return render_template('400.html'), 400

    instances = Instance.get_instances_by_exercise(exercise_name, exercise_version)

    title=f'Instances of exercise {exercise_name}'
    if exercise_version:
        title += f" v{exercise_version}"

    return _instances_render_view(instances, title=title)

@refbp.route('/instances/view')
@admin_required
def instances_view_all():
    instances = Instance.query.all()
    return _instances_render_view(instances)

@refbp.route('/instances/stop/<int:instance_id>')
@admin_required
def instance_stop(instance_id):
    instance =  Instance.query.filter(Instance.id == instance_id).first()
    if not instance:
        flash.error(f'Unknown instance ID {instance_id}')
        return render_template('400.html'), 400

    mgr = ExerciseInstanceManager(instance)
    mgr.stop()

    db.session.commit()

    return redirect_to_next()

@refbp.route('/instances/delete/<int:instance_id>')
@admin_required
def instance_delete(instance_id):
    instance =  Instance.query.filter(Instance.id == instance_id).first()
    if not instance:
        flash.error(f'Unknown instance ID {instance_id}')
        return render_template('400.html'), 400

    mgr = ExerciseInstanceManager(instance)
    mgr.remove()

    return redirect_to_next()



