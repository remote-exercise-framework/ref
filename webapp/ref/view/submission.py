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
                       Instance, Submission, SystemSettingsManager, User)
from ref.model.enums import ExerciseBuildStatus
from wtforms import Form, IntegerField, SubmitField, validators

log = LocalProxy(lambda: current_app.logger)

@refbp.route('/admin/submissions')
@admin_required
def submissions_view_all():
    submissions = Submission.all()  

    return render_template('submissions_view_all.html', title='', submissions=submissions)



@refbp.route('/admin/submissions/by-instance/<int:instance_id>')
@admin_required
def submissions_by_instance(instance_id):
    submissions = Submission.query.filter(Submission.origin_instance_id == instance_id).all()
    return render_template('submissions_view_all.html', title=f'Submissions of instance {instance_id}', submissions=submissions)
