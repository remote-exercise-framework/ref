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

from ref import db, refbp
from ref.core import (ExerciseConfigError, ExerciseImageManager,
                      ExerciseManager, InstanceManager, admin_required, flash)
from ref.core.util import redirect_to_next
from ref.model import (ConfigParsingError, Exercise, ExerciseEntryService,
                       Instance, SystemSettingsManager, User)
from ref.model.enums import ExerciseBuildStatus
from wtforms import Form, IntegerField, SubmitField, validators

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
    #Lock the instance
    instance: Instance =  Instance.query.filter(Instance.id == instance_id).with_for_update().first()
    if not instance:
        flash.error(f'Unknown instance ID {instance_id}')
        return render_template('400.html'), 400

    new_exercise: Exercise = get_newest_exercise_version(instance.exercise)
    #Lock the exercise
    if new_exercise:
        new_exercise = new_exercise.refresh(lock=True)
    if not new_exercise:
        flash.error(f'There is no new version for this exercise')
        return render_template('400.html'), 400

    mgr = InstanceManager(instance)
    try:
        new_instance = mgr.update_instance(new_exercise)
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
        return render_template('400.html'), 400

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
        return render_template('400.html'), 400

    instances = Instance.get_by_user(user_id)
    instances = list(filter(lambda e: not e.is_submission, instances))

    title=f'Instances of user {user.full_name} (#{user.id})'
    return _instances_render_view(instances, title=title)


@refbp.route('/admin/instances/view/by-exercise/<string:exercise_name>')
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
    instances = list(filter(lambda e: not e.is_submission, instances))

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
        return render_template('400.html'), 400
    
    return _instances_render_view(instance.submissions, title=f'Submissions of instance {instance.id}')

@refbp.route('/admin/instances/view')
@admin_required
def instances_view_all():
    instances = Instance.query.all()
    instances = list(filter(lambda e: not e.is_submission, instances))

    return _instances_render_view(instances)

@refbp.route('/admin/instances/stop/<int:instance_id>')
@admin_required
def instance_stop(instance_id):
    instance = Instance.query.filter(Instance.id == instance_id).with_for_update().one_or_none()
    if not instance:
        flash.error(f'Unknown instance ID {instance_id}')
        return render_template('400.html'), 400

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
        return render_template('400.html'), 400

    if not SystemSettingsManager.SUBMISSION_ALLOW_DELETE.value:
        if instance.submissions:
            flash.error(f'Unable to delete instance {instance_id}, since it has associated submissions.')
            return redirect_to_next()
        elif instance.is_submission:
            flash.error(f'Unable to delete instance {instance_id}, since submission deletion is disabled.')
            return redirect_to_next()

    #FIXME: We should move this logic into the core.
    try:
        mgr = InstanceManager(instance)
        mgr.remove()
    finally:
        db.session.commit()

    return redirect_to_next()

def _get_file_list(dir_path, base_dir_path):
    files = []

    # Append previous folder if dir_path is not the base_dir_path
    if dir_path.strip('/') != base_dir_path.strip('/'):
        relative_path = str(os.path.join(dir_path, '..')).replace(base_dir_path, '')
        files.append({
            'path': relative_path,
            'is_file': False
        })

    # Iterate over all files and folders in the current dir_path
    for path in Path(dir_path).glob('*'):
        is_file = path.is_file()
        relative_path = str(path).replace(base_dir_path, '')
        files.append({
            'path': relative_path,
            'is_file': is_file
        })

    return files

@refbp.route('/admin/instances/<int:instance_id>/review', methods = ['GET'])
@admin_required
def instance_review(instance_id):
    instance = Instance.query.filter(Instance.id == instance_id).one_or_none()
    if instance is None:
        return Response('Instance not existing', status=400)

    instance_directory = instance.entry_service.overlay_merged

    files = _get_file_list(instance_directory, instance_directory)

    title = f'Review Instance ({instance_id})'
    file_load_url = url_for('ref.instance_review_load_file', instance_id=instance_id)
    save_url = url_for('ref.instance_review_save_file', instance_id=instance_id)

    return render_template('instances_review.html', title=title, files=files, file_load_url=file_load_url, save_url=save_url)

@refbp.route('/admin/instances/<int:instance_id>/review/load-file', methods = ['POST'])
@admin_required
def instance_review_load_file(instance_id):
    instance = Instance.query.filter(Instance.id == instance_id).one_or_none()
    if instance is None:
        return Response('Instance not existing', status=400)

    instance_directory = instance.entry_service.overlay_merged

    # Determine filename from payload
    payload = request.values
    filename = payload.get('filename', None)

    if filename is None:
        return Response('', status=400)

    # .resolve
    file_path_parts = filename.split('/')
    if file_path_parts[-1] == '..':
        filename = '/'.join(file_path_parts[:-2])

    absolute_filename_path = os.path.join(instance_directory, filename.strip('/'))

    # Make sure that the absolute path is not outside of the instance directory TODO: make secure
    if not instance_directory in absolute_filename_path:
        return Response('', status=400)

    response = None
    if Path(absolute_filename_path).is_file():
        # If the current path belongs to a file, return the file content.
        content = None
        try:
            with open(absolute_filename_path, 'r') as f:
                content = f.read()
        except:
            return Response('Error while reading file', status=400)

        # Determine file extension.
        filename, file_extension = os.path.splitext(absolute_filename_path)

        response = {
            'type': 'file',
            'content': content,
            'extension': file_extension
        }

    elif Path(absolute_filename_path).is_dir():
        # If the current path belongs to a directory, determine all files in it
        files = _get_file_list(absolute_filename_path, instance_directory)
        file_load_url = url_for('ref.instance_review_load_file', instance_id=instance_id)

        response = {
            'type': 'dir',
            'content': render_template('components/file_tree.html', files=files, file_load_url=file_load_url)
        }

    else:
        return Response('', status=400)

    return Response(json.dumps(response), mimetype='application/json')

@refbp.route('/admin/instances/<int:instance_id>/review/save-file', methods = ['POST'])
@admin_required
def instance_review_save_file(instance_id):
    instance = Instance.query.filter(Instance.id == instance_id).one_or_none()
    if instance is None:
        return Response('Instance not existing', status=400)

    instance_directory = instance.entry_service.overlay_merged

    # Get filename and content from payload
    payload = request.values
    filename = payload.get('filename', None)
    content = payload.get('content', None)

    # If filename or content is missing, return 400 (Bad request)
    if content is None or filename is None:
        return Response('Missing arguments', status=400)

    absolute_filename_path = os.path.join(instance_directory, filename.strip('/'))

    if Path(absolute_filename_path).is_file():
        try:
            # Write content to file if file exists
            with open(absolute_filename_path, 'w') as f:
                f.write(content)
        except Exception as e:
            log.warning('Failed to save file', exc_info=True)
            rendered_alert = render_template('components/alert.html', error_message=str(e))
            return Response(rendered_alert, status=500)

    else:
        return Response('', status=400)

    return Response(content, mimetype='text/plain')
