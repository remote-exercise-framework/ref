import datetime
import os
import shutil
import tempfile
import typing
from collections import namedtuple
from pathlib import Path

import docker
import redis
import rq
import yaml
from flask import (Blueprint, Flask, abort, current_app, redirect,
                   render_template, request, url_for)
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

@refbp.route('/exercise/view')
@admin_required
def exercise_view_all():
    #Exercises already added to the DB
    exercises = []
    render = lambda: render_template('exercise_view_all.html', exercises=exercises)

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

    #Check if there are new/updated exercises and import them.
    for exercise in import_candidates:
        old_exercise = Exercise.query.filter(Exercise.short_name == exercise.short_name).all()
        if old_exercise:
            old_exercise = max(old_exercise, key=lambda e: e.version)

        if not old_exercise:
            #New exercise
            ExerciseManager.create(exercise)
            db.session.add_all([exercise.entry_service, exercise])
            db.session.commit()
        elif old_exercise.version < exercise.version:
            #Update
            ExerciseManager.create(exercise)
            db.session.add_all([exercise.entry_service, exercise])
            db.session.commit()

    exercises = Exercise.query.all()

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
