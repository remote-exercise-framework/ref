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
from sqlalchemy import and_, or_
from wtforms import Form, IntegerField, SubmitField, validators

log = LocalProxy(lambda: current_app.logger)

@refbp.route('/admin/grading/')
@grading_assistant_required
def grading_view_all():
    # exercise =  Exercise.query.filter(Exercise.id == exercise_id).one_or_none()
    # if not exercise:
    #     flash.error(f'Unknown exercise ID {exercise_id}')
    #     return render_template('400.html'), 400

    return render_template('grading_view_all.html')
