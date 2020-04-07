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
                      ExerciseManager, InstanceManager, admin_required, flash,
                      retry_on_deadlock)
from ref.core.util import redirect_to_next
from ref.model import (ConfigParsingError, Exercise, ExerciseEntryService,
                       Instance, Submission, SystemSettingsManager, User)
from ref.model.enums import ExerciseBuildStatus
from sqlalchemy.orm import joinedload, raiseload
from wtforms import Form, IntegerField, SubmitField, validators

log = LocalProxy(lambda: current_app.logger)

@refbp.route('/admin/submissions')
@admin_required
def submissions_view_all():
    submissions = Submission.all()
    submissions = sorted(submissions, key=lambda e: e.submission_ts, reverse=True)
    return render_template('submissions_view_all.html', title='', submissions=submissions)

@refbp.route('/admin/submissions/delete/<int:submission_id>')
@admin_required
def submission_delete(submission_id):
    submission = Submission.query.filter(Submission.id == submission_id).with_for_update().one_or_none()
    if not submission:
        flash.error(f'Unknown submission ID {submission_id}')
        return render_template('400.html'), 400

    if not SystemSettingsManager.SUBMISSION_ALLOW_DELETE.value:
        flash.error('It is not allowed to delete submissions')
        return redirect_to_next()

    with retry_on_deadlock():
        submission = Submission.query.filter(Submission.id == submission_id).with_for_update().one_or_none()
        instance = Instance.query.filter(Instance.id == submission.submitted_instance_id).with_for_update().one_or_none()

    current_app.db.session.delete(submission)
    instance_mgr = InstanceManager(instance)
    instance_mgr.remove()

    current_app.db.session.commit()
    return redirect_to_next()

@refbp.route('/admin/submissions/by-instance/<int:instance_id>')
@admin_required
def submissions_by_instance(instance_id):
    submissions = Submission.query.filter(Submission.origin_instance_id == instance_id).all()
    submissions = sorted(submissions, key=lambda e: e.submission_ts, reverse=True)

    return render_template('submissions_view_all.html', title=f'Submissions of instance {instance_id}', submissions=submissions)
