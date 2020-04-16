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

from flask_login import login_required
from ref import db, refbp
from ref.core import (ExerciseConfigError, ExerciseImageManager,
                      ExerciseManager, flash)
from ref.core.security import (admin_required, grading_assistant_required,
                               sanitize_path_is_subdir)
from ref.core.util import redirect_to_next
from ref.model import ConfigParsingError, Exercise, Submission, User
from ref.model.enums import ExerciseBuildStatus, UserAuthorizationGroups
from wtforms import Form, IntegerField, SubmitField, validators

log = LocalProxy(lambda: current_app.logger)

@refbp.route('/admin/grading/')
@grading_assistant_required
def grading_view_all():
    exercises = Exercise.all()
    exercises_by_category = defaultdict(list)
    for exercise in exercises:
        if not exercise.has_deadline():
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

@refbp.route('/admin/grading/grade/<int:submission_id>')
@grading_assistant_required
def grading_view_submission(submission_id):
    submission = Submission.get(submission_id)
    if not submission:
        flash.error(f'Unknown submission ID {submission_id}')
        return redirect_to_next()

    

    return render_template('grading_grade.html', submission=submission)
