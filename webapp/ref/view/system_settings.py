import datetime
import re

from Crypto.PublicKey import RSA
from flask import (Blueprint, Flask, Response, current_app, redirect,
                   render_template, request, url_for)
from itsdangerous import URLSafeTimedSerializer
from werkzeug.local import LocalProxy
from wtforms import (BooleanField, Form, IntegerField, PasswordField,
                     RadioField, SelectField, StringField, SubmitField,
                     TextField, validators)
from flask import copy_current_request_context

import pytz
from ref import db, refbp
from ref.core import admin_required, flash, InstanceManager
from ref.core.util import redirect_to_next
from ref.model import SystemSettingsManager, UserGroup, Instance

import concurrent.futures as cf
from functools import partial

log = LocalProxy(lambda: current_app.logger)


def field_to_str(_, field):
    return str(field.data)


class GeneralSettings(Form):
    submit = SubmitField('Save')
    course_name = TextField('Course Name')
    allow_submission_deletion = BooleanField(
        'Allow admins to delete submissions')
    maintenance_enabled = BooleanField(
        'Enable maintenance mode: Disallow any new access by non admin users. Beware: Already established connections are not closed.'
        )
    disable_submission = BooleanField('Disable submission for instances.')
    timezone = SelectField(
        'Timezone that is used for datetime representation in case no timezone information is provided by the client.',
        choices=[(e, e) for e in pytz.all_timezones]
        )


class GroupSettings(Form):
    group_size = IntegerField('Max. group size', validators=[validators.NumberRange(1)])
    groups_enable = BooleanField('Groups enabled')
    submit = SubmitField('Save')


class SshSettings(Form):
    ssh_hostname = TextField('SSH Host')
    ssh_port = TextField('SSH port', validators=[])
    welcome_header = TextField('SSH Welcome Header')
    allow_none_default_provisioning = BooleanField(
        'Allow admins to provision non default container'
        )
    ssh_instance_introspection = BooleanField(
        'Allow admins and grading assistance to access arbitrary instances using instance-{ID} as username'
        )
    message_of_the_day = TextField('Message of the day')
    submit = SubmitField('Save')

@refbp.route('/admin/system/settings/', methods=('GET', 'POST'))
@admin_required
def view_system_settings():

    # General settings
    general_settings = GeneralSettings(request.form, prefix='general_settings')
    if general_settings.submit.data and general_settings.validate():
        SystemSettingsManager.COURSE_NAME.value = general_settings.course_name.data
        SystemSettingsManager.SUBMISSION_ALLOW_DELETE.value = general_settings.allow_submission_deletion.data
        SystemSettingsManager.SUBMISSION_DISABLED.value = general_settings.disable_submission.data
        SystemSettingsManager.TIMEZONE.value = general_settings.timezone.data
        SystemSettingsManager.MAINTENANCE_ENABLED.value = general_settings.maintenance_enabled.data

    else:
        general_settings.course_name.data = SystemSettingsManager.COURSE_NAME.value
        general_settings.allow_submission_deletion.data = SystemSettingsManager.SUBMISSION_ALLOW_DELETE.value
        general_settings.maintenance_enabled.data = SystemSettingsManager.MAINTENANCE_ENABLED.value
        general_settings.disable_submission.data = SystemSettingsManager.SUBMISSION_DISABLED.value
        general_settings.timezone.data = SystemSettingsManager.TIMEZONE.value

    # Group settings belong here
    group_settings = GroupSettings(request.form, prefix='group_settings')
    if group_settings.submit.data and group_settings.validate():
        SystemSettingsManager.GROUP_SIZE.value = group_settings.group_size.data
        SystemSettingsManager.GROUPS_ENABLED.value = group_settings.groups_enable.data
    else:
        group_settings.group_size.data = SystemSettingsManager.GROUP_SIZE.value
        group_settings.groups_enable.data = SystemSettingsManager.GROUPS_ENABLED.value

    # SSH settings
    ssh_settings = SshSettings(request.form, prefix='ssh_settings')
    if ssh_settings.submit.data and ssh_settings.validate():
        SystemSettingsManager.SSH_HOSTNAME.value = ssh_settings.ssh_hostname.data
        SystemSettingsManager.SSH_PORT.value = ssh_settings.ssh_port.data
        SystemSettingsManager.SSH_WELCOME_MSG.value = ssh_settings.welcome_header.data
        SystemSettingsManager.INSTANCE_SSH_INTROSPECTION.value = ssh_settings.ssh_instance_introspection.data
        SystemSettingsManager.INSTANCE_NON_DEFAULT_PROVISIONING.value = ssh_settings.allow_none_default_provisioning.data
        SystemSettingsManager.SSH_MESSAGE_OF_THE_DAY.value = ssh_settings.message_of_the_day.data
    else:
        ssh_settings.ssh_hostname.data = SystemSettingsManager.SSH_HOSTNAME.value
        ssh_settings.ssh_port.data = SystemSettingsManager.SSH_PORT.value
        ssh_settings.welcome_header.data = SystemSettingsManager.SSH_WELCOME_MSG.value
        ssh_settings.ssh_instance_introspection.data = SystemSettingsManager.INSTANCE_SSH_INTROSPECTION.value
        ssh_settings.allow_none_default_provisioning.data = SystemSettingsManager.INSTANCE_NON_DEFAULT_PROVISIONING.value
        ssh_settings.message_of_the_day.data = SystemSettingsManager.SSH_MESSAGE_OF_THE_DAY.value

    current_app.db.session.commit()

    return render_template(
        'system_settings.html',
        group_settings=group_settings,
        ssh_settings=ssh_settings,
        general_settings=general_settings
        )
