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

def field_to_str(form, field):
    return str(field.data)

class GeneralSettings(Form):
    submit = SubmitField('Save')
    course_name = TextField('Course Name')
    allow_submission_deletion = BooleanField('Allow admins to delete submissions')
    maintenance_enabled = BooleanField('Enable maintenance mode: Disallow any new access by non admin users. Already established connections are not closed')

class GroupSettings(Form):
    group_size = IntegerField('Max. group size')
    groups_enable = BooleanField('Groups enabled')
    submit = SubmitField('Save')

class SshSettings(Form):
    ssh_hostname = TextField('SSH Host')
    ssh_port = TextField('SSH port', validators=[])
    welcome_header = TextField('SSH Welcome Header')
    allow_none_default_provisioning = BooleanField('Allow admins to provision non default container')
    ssh_instance_introspection = BooleanField('Allow admins and grading assistance to access arbitrary instances using instance-{ID} as username')
    submit = SubmitField('Save')

@refbp.route('/admin/system/settings/', methods=('GET', 'POST'))
@admin_required
def view_system_settings():

    general_settings = GeneralSettings(request.form, prefix='general_settings')
    if general_settings.submit.data and general_settings.validate():
        SystemSettingsManager.COURSE_NAME.value = general_settings.course_name.data
        SystemSettingsManager.SUBMISSION_ALLOW_DELETE.value = general_settings.allow_submission_deletion.data
        SystemSettingsManager.MAINTENANCE_ENABLED.value = general_settings.maintenance_enabled.data
    else:
        general_settings.course_name.data = SystemSettingsManager.COURSE_NAME.value
        general_settings.allow_submission_deletion.data = SystemSettingsManager.SUBMISSION_ALLOW_DELETE.value
        general_settings.maintenance_enabled.data = SystemSettingsManager.MAINTENANCE_ENABLED.value

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
        SystemSettingsManager.SSH_HOSTNAME.value = ssh_settings.ssh_hostname.data
        SystemSettingsManager.SSH_PORT.value = ssh_settings.ssh_port.data
        SystemSettingsManager.SSH_WELCOME_MSG.value = ssh_settings.welcome_header.data
        SystemSettingsManager.INSTANCE_SSH_INTROSPECTION.value = ssh_settings.ssh_instance_introspection.data
        SystemSettingsManager.INSTANCE_NON_DEFAULT_PROVISIONING.value = ssh_settings.allow_none_default_provisioning.data
    else:
        ssh_settings.ssh_hostname.data = SystemSettingsManager.SSH_HOSTNAME.value
        ssh_settings.ssh_port.data = SystemSettingsManager.SSH_PORT.value
        ssh_settings.welcome_header.data = SystemSettingsManager.SSH_WELCOME_MSG.value
        ssh_settings.ssh_instance_introspection.data = SystemSettingsManager.INSTANCE_SSH_INTROSPECTION.value
        ssh_settings.allow_none_default_provisioning.data =  SystemSettingsManager.INSTANCE_NON_DEFAULT_PROVISIONING.value

    return render_template('system_settings.html', group_settings=group_settings, ssh_settings=ssh_settings, general_settings=general_settings)
