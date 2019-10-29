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
from ref.core import (ExerciseConfigError, admin_required,
                      ExerciseImageManager, ExerciseManager, flash, ExerciseInstanceManager)
from ref.model import ConfigParsingError, Exercise, User, ExerciseInstance
from ref.model.enums import ExerciseBuildStatus

lerr = lambda msg: current_app.logger.error(msg)
linfo = lambda msg: current_app.logger.info(msg)
lwarn = lambda msg: current_app.logger.warning(msg)



@refbp.route('/instances/view')
@admin_required
def instances_view_all():
    instances = ExerciseInstance.query.all()
    for i in instances:
        running = ExerciseInstanceManager(i).is_running()
        setattr(i, 'running', running)

    return render_template('instances_view_list.html', instances=instances)


@refbp.route('/instances/view/<int:exercise_id>')
@admin_required
def instances_view_by_exercise(exercise_id):
    exercise =  Exercise.query.filter(Exercise.id == exercise_id).first()
    if not exercise:
        flash.error(f'Unknown exercise ID {exercise_id}')
        return render_template('400.html'), 400

    return render_template('exercise_view_single.html', exercise=exercise)

@refbp.route('/instances/stop/<int:instance_id>')
@admin_required
def instance_stop(instance_id):
    instance =  ExerciseInstance.query.filter(ExerciseInstance.id == instance_id).first()
    if not instance:
        flash.error(f'Unknown instance ID {instance_id}')
        return render_template('400.html'), 400

    mgr = ExerciseInstanceManager(instance)
    mgr.stop()

    return redirect(url_for('ref.instances_view_all'))

@refbp.route('/instances/delete/<int:instance_id>')
@admin_required
def instance_delete(instance_id):
    instance =  ExerciseInstance.query.filter(ExerciseInstance.id == instance_id).first()
    if not instance:
        flash.error(f'Unknown instance ID {instance_id}')
        return render_template('400.html'), 400

    mgr = ExerciseInstanceManager(instance)
    mgr.remove()

    return redirect(url_for('ref.instances_view_all'))



