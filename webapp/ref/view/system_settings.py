import datetime
import re

from Crypto.PublicKey import RSA
from flask import (Blueprint, Flask, Response, current_app, redirect,
                   render_template, request, url_for)
from itsdangerous import URLSafeTimedSerializer
from werkzeug.local import LocalProxy
from wtforms import (BooleanField, Form, IntegerField, PasswordField,
                     RadioField, SelectField, StringField, SubmitField,
                      validators)
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
    regestration_enabled = BooleanField(
        'Allow users to register.')
    submit = SubmitField('Save')
    course_name = StringField('Course Name')
    allow_submission_deletion = BooleanField(
        'Allow admins to delete submissions')
    maintenance_enabled = BooleanField(
        'Enable maintenance mode: Disallow any new access by non admin users. Beware: Already established connections are not closed.'
        )
    disable_submission = BooleanField('Disable submission for instances.')
    hide_ongoing_exercises_for_grading_assistant = BooleanField(
        'Hide submission that belong to ongoing exercises for the Grading Assistant.'
    )
    timezone = SelectField(
        'Timezone that is used for datetime representation in case no timezone information is provided by the client.',
        choices=[(e, e) for e in pytz.all_timezones]
        )

    telegram_logger_token = StringField('Telegram Logger Token')
    telegram_logger_channel_id = StringField("Telegram Logger Channel ID")

class GroupSettings(Form):
    group_size = IntegerField('Max. group size', validators=[validators.NumberRange(1)])
    groups_enable = BooleanField('Groups enabled')
    submit = SubmitField('Save')


class SshSettings(Form):
    ssh_hostname = StringField('SSH Host')
    ssh_port = StringField('SSH port', validators=[])
    welcome_header = StringField('SSH Welcome Header')
    allow_none_default_provisioning = BooleanField(
        'Allow admins to provision non default container.'
        )
    ssh_instance_introspection = BooleanField(
        'Allow admins to access arbitrary instances using instance-{ID} as username and grading assistance arbitrary submissions.'
        )
    ssh_allow_tcp_forwarding = BooleanField(
        'Allow users to forward TCP ports from there machine to services running on their instance.'
        )
    ssh_allow_root_logins_for_admin = BooleanField(
        'Allow admins to login as root by prefixing the SSH username with "root@".'
        )
    message_of_the_day = StringField('Message of the day')
    submit = SubmitField('Save')

@refbp.route('/admin/system/settings/', methods=('GET', 'POST'))
@admin_required
def view_system_settings():

    def process_setting_form(form, mapping):
        if form.submit.data and form.validate():
            for setting, form_field in mapping:
                setting.value = form_field.data
        else:
            for setting, form_field in mapping:
                form_field.data = setting.value

    # General settings
    general_settings_form = GeneralSettings(request.form, prefix='general_settings_form')
    general_settings_mapping = [
        (SystemSettingsManager.REGESTRATION_ENABLED, general_settings_form.regestration_enabled),
        (SystemSettingsManager.COURSE_NAME, general_settings_form.course_name),
        (SystemSettingsManager.SUBMISSION_ALLOW_DELETE, general_settings_form.allow_submission_deletion),
        (SystemSettingsManager.SUBMISSION_DISABLED, general_settings_form.disable_submission),
        (SystemSettingsManager.SUBMISSION_HIDE_ONGOING, general_settings_form.hide_ongoing_exercises_for_grading_assistant),
        (SystemSettingsManager.TIMEZONE, general_settings_form.timezone),
        (SystemSettingsManager.MAINTENANCE_ENABLED, general_settings_form.maintenance_enabled),
        (SystemSettingsManager.TELEGRAM_LOGGER_TOKEN, general_settings_form.telegram_logger_token),
        (SystemSettingsManager.TELEGRAM_LOGGER_CHANNEL_ID, general_settings_form.telegram_logger_channel_id),
    ]
    process_setting_form(general_settings_form, general_settings_mapping)

    # SSH settings
    ssh_settings_form = SshSettings(request.form, prefix='ssh_settings_form')
    ssh_settings_mapping = [
        (SystemSettingsManager.SSH_HOSTNAME, ssh_settings_form.ssh_hostname),
        (SystemSettingsManager.SSH_PORT, ssh_settings_form.ssh_port),
        (SystemSettingsManager.SSH_WELCOME_MSG, ssh_settings_form.welcome_header),
        (SystemSettingsManager.INSTANCE_SSH_INTROSPECTION, ssh_settings_form.ssh_instance_introspection),
        (SystemSettingsManager.INSTANCE_NON_DEFAULT_PROVISIONING, ssh_settings_form.allow_none_default_provisioning),
        (SystemSettingsManager.ALLOW_TCP_PORT_FORWARDING, ssh_settings_form.ssh_allow_tcp_forwarding),
        (SystemSettingsManager.ALLOW_ROOT_LOGINS_FOR_ADMINS, ssh_settings_form.ssh_allow_root_logins_for_admin),
        (SystemSettingsManager.SSH_MESSAGE_OF_THE_DAY, ssh_settings_form.message_of_the_day),
    ]
    process_setting_form(ssh_settings_form, ssh_settings_mapping)

    current_app.db.session.commit()

    return render_template(
        'system_settings.html',
        ssh_settings_form=ssh_settings_form,
        general_settings_form=general_settings_form
        )
