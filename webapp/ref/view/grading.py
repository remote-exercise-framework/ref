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
from sqlalchemy import and_, or_
from werkzeug.local import LocalProxy
from wtforms import Form, IntegerField, StringField, SubmitField, validators

from flask_login import current_user, login_required
from ref import db, refbp
from ref.core import (ExerciseConfigError, ExerciseImageManager,
                      ExerciseManager, flash)
from ref.core.security import (admin_required, grading_assistant_required,
                               sanitize_path_is_subdir)
from ref.core.util import redirect_to_next
from ref.model import ConfigParsingError, Exercise, Grading, Submission, User
from ref.model.enums import ExerciseBuildStatus, UserAuthorizationGroups

log = LocalProxy(lambda: current_app.logger)

class GradingForm(Form):
    points = IntegerField('Points', validators=[validators.NumberRange(min=0)])
    notes = StringField('Notes')
    save = SubmitField('Save')
    reset = SubmitField('Reset')


@refbp.route('/admin/grading/')
@grading_assistant_required
def grading_view_all():
    exercises: typing.List[Exercise] = Exercise.all()
    exercises_by_category = defaultdict(list)
    for exercise in exercises:
        if not exercise.has_deadline() or not exercise.has_submissions():
            continue
        exercises_by_category[exercise.category] += [exercise]

    return render_template('grading_view_all.html', exercises_by_category=exercises_by_category)

@refbp.route('/admin/grading/<int:exercise_id>')
@grading_assistant_required
def grading_view_exercise(exercise_id):
    exercise = Exercise.get(exercise_id)
    if not exercise:
        flash.error(f'Unknown exercise ID {exercise_id}')
        return redirect_to_next()

    submissions = exercise.submission_heads()

    return render_template('grading_view_exercise.html', exercise=exercise, submissions=submissions)

@refbp.route('/admin/grading/grade/<int:submission_id>',  methods=('GET', 'POST'))
@grading_assistant_required
def grading_view_submission(submission_id):
    submission = Submission.get(submission_id)
    if not submission:
        flash.error(f'Unknown submission ID {submission_id}')
        return redirect_to_next()

    if submission.successors():
        flash.error('There is a more recent submission of the origin instance.')
        return redirect_to_next()

    grading: Grading = submission.grading
    exercise: Exercise = submission.submitted_instance.exercise    
    form = GradingForm(request.form)

    is_new_grading = False
    if not grading:
        grading = Grading()
        is_new_grading = True

    render = lambda: render_template(
        'grading_grade.html',
        exercise=exercise,
        submission=submission,
        form=form,
        file_browser_path=submission.submitted_instance.entry_service.overlay_merged
        )

    if form.save.data and form.validate():
        if not exercise.deadine_passed():
            flash.error(f'Unable to grade submission before deadline is passed!')
            return render()

        if form.points.data > exercise.max_grading_points:
            form.points.errors = [f'Points are greater than the maximum of {exercise.max_grading_points}']
        grading.points_reached = form.points.data
        grading.private_note = form.notes.data
        grading.last_edited_by = current_user
        grading.update_ts = datetime.datetime.utcnow()

        if is_new_grading:
            grading.submission = submission
            grading.created_by = current_user
            grading.created_ts = datetime.datetime.utcnow()
            current_app.db.session.add(grading)

        current_app.db.session.add(grading)
        current_app.db.session.commit()
    else:
        form.points.data = '' if grading.points_reached is None else grading.points_reached
        form.notes.data = '' if grading.private_note is None else grading.private_note

    return render()
