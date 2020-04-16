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
from ref.model import ConfigParsingError, Exercise, User
from ref.model.enums import ExerciseBuildStatus, UserAuthorizationGroups
from wtforms import Form, IntegerField, SubmitField, validators

log = LocalProxy(lambda: current_app.logger)

@refbp.route('/admin/grading/')
@grading_assistant_required
def grading_view_all():
    exercises = Exercise.all()
    exercises_by_category = defaultdict(list)
    for exercise in exercises:
        exercises_by_category[exercise.category] += [exercise]

    return render_template('grading_view_all.html', exercises_by_category=exercises_by_category)
