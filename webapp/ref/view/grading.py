import datetime
import difflib
import os
import shutil
import subprocess
import tempfile
import typing
import urllib
from fuzzywuzzy import fuzz
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
    next = SubmitField('Next')
    save = SubmitField('Save')
    save_and_next = SubmitField('Save and Next')
    next_user_task = SubmitField('Next by User')
    save_next_user_task = SubmitField('Save and Next by User')
    reset = SubmitField('Reset')

class SearchForm(Form):
    query = StringField('Query')
    submit = SubmitField('Search')

@refbp.route('/admin/grading/')
@grading_assistant_required
def grading_view_all():
    exercises: typing.List[Exercise] = Exercise.all()
    exercises_by_category = defaultdict(lambda: defaultdict(list))

    for exercise in sorted(exercises, key=lambda e: (e.category, e.short_name, e.version)):
        if not exercise.has_deadline() or not exercise.submission_heads_global():
            continue
        exercises_by_category[exercise.category][exercise.short_name] += [exercise]

    return render_template('grading_view_all.html', exercises_by_category=exercises_by_category)

@refbp.route('/admin/grading/<int:exercise_id>')
@grading_assistant_required
def grading_view_exercise(exercise_id):
    exercise = Exercise.get(exercise_id)
    if not exercise:
        flash.error(f'Unknown exercise ID {exercise_id}')
        return redirect_to_next()

    submissions = exercise.submission_heads_global()

    return render_template('grading_view_exercise.html', exercise=exercise, submissions=submissions)


def _get_next_ungraded_submission(exercise: Exercise, current: Submission):
    ungraded_submissions = exercise.ungraded_submissions()
    ungraded_submissions = sorted(ungraded_submissions, key=lambda e: e.submission_ts, reverse=True)
    current_ts = current.submission_ts
    newer_submissions = [e for e in ungraded_submissions if e.submission_ts < current_ts]
    if newer_submissions:
        return newer_submissions[0]
    elif ungraded_submissions:
        return ungraded_submissions[0]

    return None

def _get_next_by_user(submission: Submission):
    user = submission.submitted_instance.user
    instances = user.submissions
    submissions = [i.submission for i in instances if not i.submission.successors() and i.exercise.has_deadline()]
    submissions = sorted(submissions, key=lambda e: e.id)
    current_idx = submissions.index(submission)
    return submissions[(current_idx+1)%len(submissions)]

@refbp.route('/admin/grading/grade/<int:submission_id>',  methods=('GET', 'POST'))
@grading_assistant_required
def grading_view_submission(submission_id):
    submission: Submission = Submission.get(submission_id)
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

    if form.next_user_task.data:
        n = _get_next_by_user(submission)
        return redirect(url_for('ref.grading_view_submission', submission_id=n.id))

    if form.next.data:
            next_submission = _get_next_ungraded_submission(exercise, submission)
            if not next_submission:
                flash.warning('There is no submission left for grading.')
                return render()
            return redirect(url_for('ref.grading_view_submission', submission_id=next_submission.id))

    if (form.save.data or form.save_and_next.data or form.save_next_user_task.data):
        if not form.validate():
            flash.error('Invalid form values!')
            return render()

        if not exercise.deadine_passed():
            flash.error(f'Unable to grade submission before deadline is passed!')
            return render()

        if form.points.data > exercise.max_grading_points:
            form.points.errors = [f'Points are greater than the maximum of {exercise.max_grading_points}']
            return render()
        grading.points_reached = form.points.data
        grading.private_note = form.notes.data
        grading.last_edited_by = current_user
        grading.update_ts = datetime.datetime.utcnow()

        if is_new_grading:
            grading.submission = submission
            grading.created_by = current_user
            grading.created_ts = datetime.datetime.utcnow()
            current_app.db.session.add(grading)


        flash.success(f'Successfully graded submission {submission.id}.')
        if form.save_and_next.data:
            next_submission = _get_next_ungraded_submission(exercise, submission)
            if next_submission:
                current_app.db.session.add(grading)
                current_app.db.session.commit()
                return redirect(url_for('ref.grading_view_submission', submission_id=next_submission.id))
            flash.warning('There is no submission left for gradeing')
        elif form.save_next_user_task.data:
            next_submission = _get_next_by_user(submission)
            current_app.db.session.add(grading)
            current_app.db.session.commit()
            return redirect(url_for('ref.grading_view_submission', submission_id=next_submission.id))


        current_app.db.session.add(grading)
        current_app.db.session.commit()
        return render()
    else:
        form.points.data = '' if grading.points_reached is None else grading.points_reached
        form.notes.data = '' if grading.private_note is None else grading.private_note
        return render()

@refbp.route('/admin/grading/search/query', methods=('GET', 'POST'))
@grading_assistant_required
def grading_search_execute_query():
    user_assignment_submissions = defaultdict(lambda: defaultdict(list))
    query = request.values.get('query', None)
    if not query:
        return render_template('grading_search_result.html', user_assignment_submissions=user_assignment_submissions)

    users = User.all()

    if query.isdigit():
        #Assume mat. num.
        score_to_user = [(fuzz.partial_ratio(user.mat_num, query), user) for user in users]
    else:
        #Assume first and/or last name
        score_to_user = [(fuzz.ratio(user.full_name.lower(), query.lower()), user) for user in users]

    score_to_user = sorted(score_to_user, key=lambda e: e[0], reverse=True)
    score_to_user = score_to_user[:5]

    for _, user in score_to_user:
        for instance in user.submissions:
            if instance.submission.successors():
                continue
            user_assignment_submissions[user][instance.exercise.category] += [instance.submission]
        if not user_assignment_submissions[user]:
            user_assignment_submissions[user] = None

    return render_template('grading_search_result.html', user_assignment_submissions=user_assignment_submissions)


@refbp.route('/admin/grading/search', methods=('GET', 'POST'))
@grading_assistant_required
def grading_search():
    form = SearchForm(request.form)
    return render_template('grading_search.html', form=form)
