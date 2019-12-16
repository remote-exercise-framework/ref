import datetime
import difflib
import os
import shutil
import subprocess
import tempfile
import typing
import urllib
from collections import defaultdict, namedtuple
from pathlib import Path

import docker
import redis
import rq
import yaml
from flask import (Blueprint, Flask, abort, current_app, jsonify, redirect,
                   render_template, request, url_for)
from flask_login import login_required
from sqlalchemy import and_, or_
from werkzeug.local import LocalProxy
from wtforms import Form, IntegerField, SubmitField, validators

from ref import db, refbp
from ref.core import (ExerciseConfigError, ExerciseImageManager,
                      ExerciseManager, admin_required, flash)
from ref.core.security import sanitize_path_is_subdir
from ref.core.util import redirect_to_next
from ref.model import ConfigParsingError, Exercise, User
from ref.model.enums import ExerciseBuildStatus

log = LocalProxy(lambda: current_app.logger)

@refbp.route('/admin/exercise/build/<int:exercise_id>')
@admin_required
def exercise_build(exercise_id):
    """
    Request to build exercise with ID exercise_id.
    """
    exercise: Exercise = db.get(Exercise, id=exercise_id)
    if not exercise:
        log.info(f'Unknown exercise ID {exercise_id}')
        flash.warning(f"Unknown exercise ID {exercise_id}")
        return render_template('400.html'), 400

    if exercise.build_job_status in [ ExerciseBuildStatus.BUILDING,  ExerciseBuildStatus.FINISHED]:
        log.warning(f'Unable to start build for exercise {exercise} in state {exercise.build_job_status}')
        flash.error("Already build!")
        return render_template('400.html'), 400

    mgr = ExerciseImageManager(exercise)
    if mgr.is_build():
        log.info(f'Build for already build exercise {exercise} was requested.')
        flash.success('Container already build')
        return redirect_to_next()
    else:
        #Start new build
        current_app.logger.info(f"Starting build for exercise {exercise}. Setting state to  {ExerciseBuildStatus.BUILDING}")
        exercise.build_job_status = ExerciseBuildStatus.BUILDING
        exercise.build_job_result = None
        db.session.add(exercise)
        db.session.commit()
        flash.info("Build started...")
        mgr.build()
        return redirect_to_next()


@refbp.route('/admin/exercise/diff')
@admin_required
def exercise_diff():
    """
    Returns a modal that shows a diff of the exercise configs provided
    via query args path_a, path_b. If path_b is not set, the path_a config
    is compared with the most recent version of the same exercise.
    """
    path_a = request.args.get('path_a')
    path_b = request.args.get('path_b')

    if not path_a:
        flash.error("path_a is required")
        return render_template('400.html'), 400

    exercises_path = current_app.config['EXERCISES_PATH']
    if not sanitize_path_is_subdir(exercises_path, path_a):
        flash.error("path_a is invalid")
        log.info(f'Failed to sanitize path {path_a}')
        return render_template('400.html'), 400

    exercise_a = ExerciseManager.from_template(path_a)
    exercise_b = None

    #If path_b is not provided, we compare exercise path_a with the most recent version
    #of the same exercise.
    if not path_b:
        #We can trust the paths retrived from DB
        exercise_b = exercise_a.predecessor()
    else:
        if not sanitize_path_is_subdir(exercises_path, path_b):
            flash.error("path_b is invalid")
            log.info(f'Failed to sanitize path {path_b}')
            return render_template('400.html'), 400

    if not exercise_b:
        log.info('Unable find any exercise to compare with')
        flash.error("Nothing to compare with")
        return render_template('400.html'), 400

    log.info(f'Comparing {exercise_a} with{exercise_b}')

    #template_path is only set if the exercise was already imported
    if exercise_a.template_path:
        path_a = exercise_a.template_path
    else:
        path_a = exercise_a.template_import_path

    if exercise_b.template_path:
        path_b = exercise_b.template_path
    else:
        path_b = exercise_b.template_import_path

    #Dockerfile-entry is generated during build, thus we ignore it
    cmd = f'diff -N -r -u --exclude=Dockerfile-entry -U 5 {path_b} {path_a}'
    log.info(f'Running cmd: {cmd}')
    p = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode == 2:
        log.error(f'Failed to run. {p.stderr.decode()}')
        return render_template('500.html'), 500
    diff = p.stdout.decode()

    title = f'{exercise_a.short_name} - v{exercise_b.version} vs. v{exercise_a.version}'
    return render_template('exercise_config_diff.html', title=title, diff=diff)

def _check_import(importable: Exercise):
    """
    This function must only be called with an importable that has no successors,
    since importing an older version is not supported.
    """
    warnings = []
    errors = []
    predecessors = importable.predecessors()
    successors = importable.successors()

    assert len(successors) == 0

    for e in predecessors:
        is_readonly = False
        if bool(e.entry_service.readonly) != bool(importable.entry_service.readonly):
            warnings += [f'{importable.template_import_path}: Changeing the readonly flag between versions cause loss of data during instance upgrade']
            is_readonly = True

        if not is_readonly and importable.entry_service.persistance_container_path != e.entry_service.persistance_container_path:
            errors += [f'{importable.template_import_path}: Persistance path changes are not allowed between versions']

    return warnings, errors


@refbp.route('/admin/exercise/import/<string:cfg_path>')
@admin_required
def exercise_do_import(cfg_path):
    render = lambda: redirect_to_next()

    try:
        cfg_path = urllib.parse.unquote_plus(cfg_path)
    except:
        flash.error('Invalid config path')
        return render()

    if not sanitize_path_is_subdir(current_app.config['EXERCISES_PATH'], cfg_path):
        flash.error('Invalid cfg path')
        return render()

    log.info(f'Importing {cfg_path}')

    try:
        exercise = ExerciseManager.from_template(cfg_path)
    except ExerciseConfigError as err:
        flash.error(f'Template at {cfg_path} contains errors: {err}')
        return render()

    #Check if this is really a new version or a new task
    successor = exercise.successor()
    if successor:
        flash.warning('Unable to import older version of already existing exercise')
        return render()

    _, errors = _check_import(exercise)
    if errors:
        for e in errors:
            flash.error(e)
        return render()

    ExerciseManager.create(exercise)
    db.session.add_all([exercise.entry_service, exercise])
    db.session.commit()

    return render()

@refbp.route('/admin/exercise/view')
@admin_required
def exercise_view_all():
    #Exercises already added to the DB
    exercises = []
    categories = {}
    #Exercises that might be imported by a user. These Exercise instances are not committed to the DB.
    importable = []
    render = lambda: render_template('exercise_view_all.html', exercises=exercises, categories=categories, importable=importable)

    #Parse all available configs
    import_candidates = []
    for path in Path(current_app.config['EXERCISES_PATH']).glob('*'):
        if not path.is_dir() or not path.joinpath('settings.yml').exists():
            continue
        try:
            exercise = ExerciseManager.from_template(path)
            import_candidates.append(exercise)
        except ExerciseConfigError as err:
            flash.error(f'Template at {path} contains errors: {err}')
            exercises = []
            return render()

    #Check if there are new/updated exercises
    for exercise in import_candidates:
        exercise.errors = []
        exercise.warnings = []
        exercise.is_update = False

        predecessors = exercise.predecessors()
        successors = exercise.successors()
        same_version = exercise.get_exercise(exercise.short_name, exercise.version)

        if successors or same_version:
            #Do not import exercises of same type with version <= the already imported versions.
            continue

        #This is an update, check for compatibility
        if predecessors:
            exercise.is_update = True

        exercise.warnings, exercise.errors = _check_import(exercise)
        importable.append(exercise)

    exercises = Exercise.query.with_for_update().all()
    #category might be None, since this attribute was introduced in a later release
    exercises = sorted(exercises, key=lambda e: e.category or "None")

    #Check whether our DB and the local docker repo are in sync
    for exercise in exercises:
        mgr = ExerciseManager(exercise)

        is_build = ExerciseImageManager(exercise).is_build()
        if exercise.build_job_status != ExerciseBuildStatus.FINISHED and is_build:
            #Already build
            exercise.build_job_status = ExerciseBuildStatus.FINISHED
            db.session.add(exercise)
            db.session.commit()
        elif exercise.build_job_status == ExerciseBuildStatus.FINISHED and not is_build:
            #Image got deleted
            exercise.is_default = False
            exercise.build_job_status = ExerciseBuildStatus.NOT_BUILD
            db.session.add(exercise)
            db.session.commit()

    categories = defaultdict(list)
    for e in exercises:
        categories[e.category] += [e]

    for k in categories:
        categories[k] = sorted(categories[k], key=lambda e: e.short_name)

    return render()




@refbp.route('/admin/exercise/<int:exercise_id>/delete')
@admin_required
def exercise_delete(exercise_id):
    exercise =  Exercise.query.filter(Exercise.id == exercise_id).with_for_update().first()
    if not exercise:
        flash.error(f'Unknown exercise ID {exercise_id}')
        return render_template('400.html'), 400

    if exercise.is_default:
        flash.error("Exercise marked as default can not be deleted")
        return redirect_to_next()

    if exercise.instances:
        flash.error("Exercise has associated instances, unable to delete!")
        return redirect_to_next()

    if exercise.build_job_status == ExerciseBuildStatus.BUILDING:
        flash.error('Unable to delete exercise during building')
        return redirect_to_next()

    mgr = ExerciseImageManager(exercise)
    mgr.remove()

    for service in exercise.services:
        db.session.delete(service)

    db.session.delete(exercise.entry_service)
    db.session.delete(exercise)
    db.session.commit()

    return redirect_to_next()

@refbp.route('/admin/exercise/default/toggle/<int:exercise_id>')
@admin_required
def exercise_toggle_default(exercise_id):
    exercise = Exercise.query.filter(Exercise.id == exercise_id).with_for_update().one_or_none()
    if not exercise:
        log.info(f'Tried to toggle unknown exercise id={exercise_id}')
        flash.error(f'Unknown exercises id={exercise_id}')
        return render_template('400.html'), 400
    if exercise.build_job_status != ExerciseBuildStatus.FINISHED:
        log.info(f'Tried to toggle default for exercise {exercise} that is not build')
        flash.error('Unable to mark exercise that was not build as default')
        return render_template('400.html'), 400

    exercises_same_version = Exercise.get_exercises(exercise.short_name)
    exercises_same_version.remove(exercise)

    if exercise.is_default:
        exercise.is_default = False
    elif any([e.is_default for e in exercises_same_version]):
        log.info(f'There is already another version of {exercise} marked as default')
        flash.error(f'At most one exercise of {exercise.short_name} can be set to default')
    else:
        #No other task with same name is default
        exercise.is_default = True

    db.session.add(exercise)
    db.session.commit()

    return redirect_to_next()

@refbp.route('/admin/exercise/view/<int:exercise_id>')
@admin_required
def exercise_view(exercise_id):
    exercise =  Exercise.query.filter(Exercise.id == exercise_id).one_or_none()
    if not exercise:
        flash.error(f'Unknown exercise ID {exercise_id}')
        return render_template('400.html'), 400

    return render_template('exercise_view_single.html', exercise=exercise)

@refbp.route('/admin', methods=('GET', 'POST'))
@admin_required
def admin_default_routes():
    """
    List all students currently registered.
    """
    return redirect(url_for('ref.exercise_view_all'))
