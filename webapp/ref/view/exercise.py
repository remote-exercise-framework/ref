import datetime
import os
import shutil
import tempfile
import urllib
import typing
import subprocess
import difflib
from collections import namedtuple
from pathlib import Path

from sqlalchemy import and_, or_

from collections import defaultdict
from ref.core.util import redirect_to_next
import docker
import redis
import rq
import yaml
from flask import (Blueprint, Flask, abort, current_app, redirect,
                   render_template, request, url_for, jsonify)
from wtforms import Form, IntegerField, SubmitField, validators

from ref import db, refbp
from ref.core import (ExerciseConfigError,
                      ExerciseImageManager, ExerciseManager, flash, admin_required)
from ref.model import ConfigParsingError, Exercise, User
from ref.model.enums import ExerciseBuildStatus

from flask_login import login_required

lerr = lambda msg: current_app.logger.error(msg)
linfo = lambda msg: current_app.logger.info(msg)
lwarn = lambda msg: current_app.logger.warning(msg)

class ImportableExercise():
    """
    Represents a possible import candidate.
    Passed to the rendered view.
    """
    def __init__(self, old_exercise: Exercise, new_exercise: Exercise):
        assert new_exercise
        self.old = old_exercise
        self.new = new_exercise

    def is_update(self):
        return self.old and self.new and (self.old.version < self.new.version)

    def is_new(self):
        return not self.old and self.new

    @property
    def exercise(self):
        return self.new

@refbp.route('/exercises/<int:exercise_id>/build_status', methods=('GET',))
@admin_required
def testx(exercise_id):
    exercise: Exercise = db.get(Exercise, id=exercise_id)
    if exercise:
        return jsonify({'build_status': exercise.build_job_status.value}), 200
    else:
        return jsonify({'error': 'Unknown exercise ID'}), 400

@refbp.route('/exercises/<int:exercise_id>/build', methods=('PUT',))
@admin_required
def exercise_build_rest(exercise_id):
    exercise: Exercise = db.get(Exercise, id=exercise_id)
    if not exercise:
        flash.error(f"Unknown exercise ID {exercise_id}")
        return render_template('500.html'), 400

    if exercise.build_job_status in [ ExerciseBuildStatus.BUILDING,  ExerciseBuildStatus.FINISHED]:
        flash.error("Already build!")
        return render_template('500.html'), 400

    mgr = ExerciseImageManager(exercise)
    if mgr.is_build():
        linfo(f'Build for already build exercise {exercise} was requested.')
        flash.success('Container already build')
        return redirect(url_for('ref.exercise_view_all'))
    else:
        #Start new build
        flash.info("Build started...")
        current_app.logger.info(f"Starting build for exercise {exercise}. Setting state to  {ExerciseBuildStatus.BUILDING}")
        exercise.build_job_status = ExerciseBuildStatus.BUILDING
        exercise.build_job_result = None
        db.session.add(exercise)
        db.session.commit()
        mgr.build()
        return redirect(url_for('ref.exercise_view_all'))


@refbp.route('/exercise/build/<int:exercise_id>')
@admin_required
def exercise_build(exercise_id):
    exercise: Exercise = db.get(Exercise, id=exercise_id)
    if not exercise:
        flash.error(f"Unknown exercise ID {exercise_id}")
        return render_template('500.html'), 400

    if exercise.build_job_status in [ ExerciseBuildStatus.BUILDING,  ExerciseBuildStatus.FINISHED]:
        flash.error("Already build!")
        return render_template('500.html'), 400

    mgr = ExerciseImageManager(exercise)
    if mgr.is_build():
        linfo(f'Build for already build exercise {exercise} was requested.')
        flash.success('Container already build')
        return redirect(url_for('ref.exercise_view_all'))
    else:
        #Start new build
        flash.info("Build started...")
        current_app.logger.info(f"Starting build for exercise {exercise}. Setting state to  {ExerciseBuildStatus.BUILDING}")
        exercise.build_job_status = ExerciseBuildStatus.BUILDING
        exercise.build_job_result = None
        db.session.add(exercise)
        db.session.commit()
        mgr.build()
        return redirect(url_for('ref.exercise_view_all'))


@refbp.route('/exercise/diff')
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

    exercise_a = ExerciseManager.from_template(path_a)
    exercise_b = None

    #If path_b is not provided, we compare exercise path_a with the most recent version
    #of the same exercise.
    if not path_b:
        exercise_b = exercise_a.predecessor()

    if not exercise_b:
        flash.error("Nothing to compare with")
        return render_template('400.html'), 400

    linfo(f'Comparing {exercise_a.short_name} version {exercise_a.version} vs. {exercise_b.version}')

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
    p = subprocess.run(f'diff -N -r -u --exclude=Dockerfile-entry -U 5 {path_b} {path_a}', shell=True, stdout=subprocess.PIPE)
    if p.returncode == 2:
        return render_template('400.html'), 400
    diff = p.stdout.decode()

    title = f'{exercise_a.short_name} - v{exercise_b.version} vs. v{exercise_a.version}'

    return render_template('exercise_config_diff.html', title=title, diff=diff)

@refbp.route('/exercise/import/<string:cfg_path>')
@admin_required
def exercise_do_import(cfg_path):
    render = lambda: redirect(url_for('ref.exercise_view_all'))

    try:
        cfg_path = urllib.parse.unquote_plus(cfg_path)
    except:
        flash.error('Invalid config path')
        return render()

    cfg_path = Path(cfg_path).resolve()
    exercise_dir_path = Path(current_app.config['EXERCISES_PATH']).resolve()
    if not cfg_path.as_posix().startswith(exercise_dir_path.as_posix()):
        flash.error('Nope')
        return render()

    linfo(f'Importing {cfg_path}')

    exercise = ExerciseManager.from_template(cfg_path)
    #Check if this is really a new version or a new task

    same_exercises = Exercise.query.filter(Exercise.short_name == exercise.short_name).all()
    if same_exercises:
        newest_exercise = max(same_exercises, key=lambda e: e.version)
        if newest_exercise.version >= exercise.version:
            flash.warning('Unable to import older version of already existing task')
            return render()
        old_path = newest_exercise.entry_service.persistance_container_path
        new_path = exercise.entry_service.persistance_container_path
        #The persistance path is only allowed to change if the new version is
        #readonly, i.e., there is no path to persist.
        if old_path != new_path and not exercise.entry_service.readonly:
            flash.error(f'{exercise.template_import_path}: Persistance path changes are not allowed between versions')
            return render()

    ExerciseManager.create(exercise)
    db.session.add_all([exercise.entry_service, exercise])
    db.session.commit()

    return render()

@refbp.route('/exercise/view')
@admin_required
def exercise_view_all():
    #Exercises already added to the DB
    exercises = []
    categories = {}
    #Exercises that might be imported by a user
    importable = []
    render = lambda: render_template('exercise_view_all.html', exercises=exercises, categories=categories, importable=importable)

    #Parse all available configs
    import_candidates = []
    for path in Path(current_app.config['EXERCISES_PATH']).glob('*'):
        if not path.is_dir():
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
        newest_exercise = None
        exercise.errors = []
        exercise.is_update = False

        same_exercises = Exercise.query.filter(Exercise.short_name == exercise.short_name).all()

        if same_exercises:
            newest_exercise = max(same_exercises, key=lambda e: e.version)
            if newest_exercise.version >= exercise.version:
                #Do not import exercises of same type with version <= the currently imported versions.
                continue

            if newest_exercise:
                exercise.is_update = True

            if bool(newest_exercise.entry_service.readonly) != bool(exercise.entry_service.readonly):
                exercise.errors += [f'{exercise.template_import_path}: Changing the readonly flag between versions cause loss of data during instance upgrade']

        importable.append(exercise)

    exercises = Exercise.query.all()
    #category might be none, since this attribute was introduced in a later release
    exercises = sorted(exercises, key=lambda e: e.category or "None")

    #Check whether our DB and the local docker repo are in sync
    for exercise in exercises:
        mgr = ExerciseManager(exercise)
        is_build = mgr.image_manager().is_build()
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




@refbp.route('/exercise/<int:exercise_id>/delete')
@admin_required
def exercise_delete(exercise_id):
    exercise =  Exercise.query.filter(Exercise.id == exercise_id).first()
    if not exercise:
        flash.error(f'Unknown exercise ID {exercise_id}')
        return render_template('400.html'), 400

    if exercise.is_default:
        flash.error("Exercise marked as default can not be deleted")
        return redirect(url_for('ref.exercise_view_all'))

    if len(exercise.instances) > 0:
        flash.error("Exercise has associated instances, unable to delete!")
        return redirect(url_for('ref.exercise_view_all'))

    if exercise.build_job_status == ExerciseBuildStatus.BUILDING:
        flash.error('Unable to delete exercise during building')
        return redirect(url_for('ref.exercise_view_all'))

    mgr = ExerciseImageManager(exercise)
    mgr.remove()

    db.session.delete(exercise.entry_service)
    db.session.delete(exercise)
    db.session.commit()

    return redirect(url_for('ref.exercise_view_all'))

@refbp.route('/exercise/default/toggle/<int:exercise_id>')
@admin_required
def exercise_toggle_default(exercise_id):
    exercise = db.get(Exercise, id=exercise_id)
    if not exercise:
        flash.error(f'Unknown exercises id={exercise_id}')
        return render_template('400.html'), 400
    if exercise.build_job_status != ExerciseBuildStatus.FINISHED:
        flash.error('Unable to mark exercise that was not build as default')
        return render_template('400.html'), 400

    other_exercises = list(Exercise.query.filter(Exercise.short_name == exercise.short_name))
    if not exercise.is_default:
        #Only allow to set default in case there is no newer version of the exercise with active instances.
        for e in other_exercises:
            if e.version > exercise.version and len(e.instances) > 0:
                flash.error(f'Unable to mark exercise as default as long there is a more recent version with active instances.')
                return redirect(url_for('ref.exercise_view_all'))


    other_exercises.remove(exercise)
    if exercise.is_default:
        exercise.is_default = False
    elif any([e.is_default for e in other_exercises]):
        flash.error(f'At most one exercise of {exercise.short_name} can be set to default')
    else:
        #No other task with same name is default
        exercise.is_default = True

    db.session.add(exercise)
    db.session.commit()

    return redirect(url_for('ref.exercise_view_all'))

@refbp.route('/exercise/view/<int:exercise_id>')
@admin_required
def exercise_view(exercise_id):
    exercise =  Exercise.query.filter(Exercise.id == exercise_id).first()
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


