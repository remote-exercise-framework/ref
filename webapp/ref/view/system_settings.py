import datetime
import re

from Crypto.PublicKey import RSA
from flask import (Blueprint, Flask, Response, current_app, redirect,
                   render_template, request, url_for)
from itsdangerous import URLSafeTimedSerializer
from werkzeug.local import LocalProxy

from ref import db, refbp
from ref.core import admin_required, flash
from ref.core.util import redirect_to_next
from ref.model import SystemSettingsManager, User, UserGroup
from ref.model.enums import CourseOfStudies
from wtforms import (BooleanField, Form, IntegerField, PasswordField,
                     RadioField, SelectField, StringField, SubmitField,
                     TextField, validators)

log = LocalProxy(lambda: current_app.logger)

class GeneralSettings(Form):
    submit = SubmitField('Save')
    allow_submission_deletion = BooleanField('Allow admins to delete submissions')

class GroupSettings(Form):
    group_size = IntegerField('Max. group size')
    groups_enable = BooleanField('Groups enabled')
    submit = SubmitField('Save')

class SshSettings(Form):
    welcome_header = TextField('SSH Welcome Header')
    allow_none_default_provisioning = BooleanField('Allow admins to provision non default container')
    ssh_instance_introspection = BooleanField('Allow admins to access arbitrary instances using instance-{ID} as username')
    submit = SubmitField('Save')

@refbp.route('/admin/system/settings/', methods=('GET', 'POST'))
@admin_required
def view_system_settings():

    general_settings = GeneralSettings(request.form, prefix='general_settings')
    if general_settings.submit.data and general_settings.validate():
         SystemSettingsManager.SUBMISSION_ALLOW_DELETE.value = general_settings.allow_submission_deletion.data
    else:
        general_settings.allow_submission_deletion.data = SystemSettingsManager.SUBMISSION_ALLOW_DELETE.value

    #Group settings belong here
    group_settings = GroupSettings(request.form, prefix='group_settings')
    if group_settings.submit.data and group_settings.validate():
        SystemSettingsManager.GROUP_SIZE.value = group_settings.group_size.data
        SystemSettingsManager.GROUPS_ENABLED.value = group_settings.groups_enable.data
    else:
        group_settings.group_size.data = SystemSettingsManager.GROUP_SIZE.value
        group_settings.groups_enable.data = SystemSettingsManager.GROUPS_ENABLED.value

    ssh_settings = SshSettings(request.form, prefix='ssh_settings')
    if ssh_settings.submit.data and ssh_settings.validate():
        SystemSettingsManager.SSH_WELCOME_MSG.value = ssh_settings.welcome_header.data
        SystemSettingsManager.INSTANCE_SSH_INTROSPECTION.value = ssh_settings.ssh_instance_introspection.data
    else:
        ssh_settings.welcome_header.data = SystemSettingsManager.SSH_WELCOME_MSG.value
        ssh_settings.ssh_instance_introspection.data = SystemSettingsManager.INSTANCE_SSH_INTROSPECTION.value

    return render_template('system_settings.html', group_settings=group_settings, ssh_settings=ssh_settings, general_settings=general_settings)
