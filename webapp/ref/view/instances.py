import datetime
import json
import os
import shutil
import tempfile
import typing
import urllib
from collections import namedtuple
from pathlib import Path

import docker
import redis
import rq
import yaml
from flask import (Blueprint, Flask, Response, abort, current_app, redirect,
                   render_template, request, url_for)
from werkzeug.local import LocalProxy
from werkzeug.urls import url_parse
from wtforms import Form, IntegerField, SubmitField, validators

from ref import db, refbp
from ref.core import (ExerciseConfigError, ExerciseImageManager,
                      ExerciseManager, InstanceManager, admin_required, flash)
from ref.core.util import lock_db, redirect_to_next
from ref.model import (ConfigParsingError, Exercise, ExerciseEntryService,
                       Instance, SystemSettingsManager, User)
from ref.model.enums import ExerciseBuildStatus

lerr = lambda msg: current_app.logger.error(msg)
linfo = lambda msg: current_app.logger.info(msg)
lwarn = lambda msg: current_app.logger.warning(msg)

log = LocalProxy(lambda: current_app.logger)

def get_newest_exercise_version(exercise: Exercise):
    exercises = Exercise.query.filter(Exercise.short_name == exercise.short_name).all()
    new_exercise = list(filter(lambda e: e.version > exercise.version and e.build_job_status == ExerciseBuildStatus.FINISHED, exercises))
    return max(new_exercise, key=lambda e: e.version, default=None)

@refbp.route('/admin/instances/update/<int:instance_id>')
@admin_required
def instance_update(instance_id):

    #Get lock

    #Lock the instance
    instance: Instance = Instance.query.filter(Instance.id == instance_id).with_for_update().first()
    if not instance:
        flash.error(f'Unknown instance ID {instance_id}')
        abort(400)

    user = instance.user.refresh(lock=True)

    new_exercise: Exercise = get_newest_exercise_version(instance.exercise)
    #Lock the exercise
    if new_exercise:
        new_exercise = new_exercise.refresh(lock=True)
    if not new_exercise:
        flash.error(f'There is no new version for this exercise')
        abort(400)

    for i in user.exercise_instances:
        if new_exercise == i.exercise:
            flash.error('There can be only one instance with same version')
            return redirect_to_next()

    #release lock (commit)

    #Create new instance (takes long)

    #Get lock

    #Retest assumption. If still valid, update old instance. If not, delete new instance.

    mgr = InstanceManager(instance)
    try:
        mgr.update_instance(new_exercise)
    except:
        raise
    finally:
        current_app.db.session.commit()

    return redirect_to_next()

@refbp.route('/admin/instances/view/<int:instance_id>')
@admin_required
def instances_view_details(instance_id):
    instance =  Instance.query.filter(Instance.id == instance_id).first()
    if not instance:
        flash.error(f'Unknown instance ID {instance_id}')
        abort(400)

    return render_template('instance_view_details.html', instance=instance)

def _instances_render_view(instances, title=None):

    instances = sorted(instances, key=lambda i: i.id)

    #Set attributes used by the UI.
    for i in instances:
        i = i.refresh(lock=True)
        if not i:
            continue
        running = InstanceManager(i).is_running()
        setattr(i, 'running', running)

        new_exercise = get_newest_exercise_version(i.exercise)
        setattr(i, 'new_exercise', new_exercise)

    return render_template('instances_view_list.html', title=title, instances=instances)

@refbp.route('/admin/instances/view/by-user/<int:user_id>')
@admin_required
def instances_by_user_id(user_id):
    user = User.get(user_id)
    if not user:
        flash.error(f'Invalid user id')
        abort(400)

    instances = Instance.get_by_user(user_id)
    instances = list(filter(lambda e: not e.submission, instances))

    title=f'Instances of user {user.full_name} (#{user.id})'
    return _instances_render_view(instances, title=title)


@refbp.route('/admin/instances/view/by-exercise/<string:exercise_name>')
@admin_required
def instances_view_by_exercise(exercise_name):
    try:
        exercise_name = urllib.parse.unquote_plus(exercise_name)
    except Exception as e:
        flash.error(f'Invalid exercise name')
        abort(400)

    exercise_version = request.args.get('exercise_version')
    if exercise_version:
        try:
            exercise_version = int(exercise_version)
        except (ValueError, TypeError):
            flash.error(f'Invalid exercise version')
            abort(400)

    instances = Instance.get_instances_by_exercise(exercise_name, exercise_version)
    instances = list(filter(lambda e: not e.submission, instances))

    title=f'Instances of exercise {exercise_name}'
    if exercise_version:
        title += f" v{exercise_version}"

    return _instances_render_view(instances, title=title)

@refbp.route('/admin/instances/<int:instance_id>')
@admin_required
def instance_view_submissions(instance_id):
    instance =  Instance.query.filter(Instance.id == instance_id).first()
    if not instance:
        flash.error(f'Unknown instance ID {instance_id}')
        abort(400)
    
    instances = []
    for submission in instance.submissions:
        instances.append(submission.submitted_instance)

    return _instances_render_view(instances, title=f'Submissions of instance {instance.id}')

@refbp.route('/admin/instances/view')
@admin_required
def instances_view_all():

    lock_db()

    instances = Instance.query.all()
    instances = list(filter(lambda e: not e.submission, instances))

    return _instances_render_view(instances)

@refbp.route('/admin/instances/stop/<int:instance_id>')
@admin_required
def instance_stop(instance_id):
    instance = Instance.query.filter(Instance.id == instance_id).with_for_update().one_or_none()
    if not instance:
        flash.error(f'Unknown instance ID {instance_id}')
        abort(400)

    mgr = InstanceManager(instance)

    try:
        mgr.stop()
    finally:
        db.session.commit()


    return redirect_to_next()

@refbp.route('/admin/instances/delete/<int:instance_id>')
@admin_required
def instance_delete(instance_id):
    instance =  Instance.query.filter(Instance.id == instance_id).with_for_update().one_or_none()
    if not instance:
        flash.error(f'Unknown instance ID {instance_id}')
        abort(400)

    if not SystemSettingsManager.SUBMISSION_ALLOW_DELETE.value:
        if instance.submissions:
            flash.error(f'Unable to delete instance {instance_id}, since it has associated submissions.')
            return redirect_to_next()
        elif instance.submission:
            flash.error(f'Unable to delete instance {instance_id}, since submission deletion is disabled.')
            return redirect_to_next()

    #FIXME: We should move this logic into the core.
    try:
        mgr = InstanceManager(instance)
        mgr.remove()
    finally:
        db.session.commit()

    return redirect_to_next()

@refbp.route('/admin/instances/<int:instance_id>/review', methods = ['GET'])
@admin_required
def instance_review(instance_id):
    instance = Instance.query.filter(Instance.id == instance_id).one_or_none()
    if instance is None:
        return Response('Instance not existing', status=400)

    instance_directory = instance.entry_service.overlay_merged
    title = f'Review Instance ({instance_id})'


    return render_template('instances_review.html', title=title, file_browser_path=instance_directory)
