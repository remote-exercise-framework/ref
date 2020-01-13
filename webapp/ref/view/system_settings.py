import datetime
import re

from flask import (Blueprint, Flask, Response, current_app, redirect,
                   render_template, request, url_for)
from itsdangerous import URLSafeTimedSerializer

from werkzeug.local import LocalProxy
from Crypto.PublicKey import RSA
from ref import db, refbp
from ref.core import admin_required, flash
from ref.core.util import redirect_to_next
from ref.model import User, UserGroup, SystemSetting
from ref.model.enums import CourseOfStudies
from wtforms import (BooleanField, Form, IntegerField, PasswordField,
                     RadioField, StringField, SubmitField, TextField,
                     validators, SelectField)

log = LocalProxy(lambda: current_app.logger)

class GroupSettings(Form):
    group_size = IntegerField('Max. group size')
    groups_enable = BooleanField('Groups enabled')
    submit = SubmitField('Save')

class SshSettings(Form):
    welcome_header = TextField('SSH Welcome Header')
    allow_none_default_provisioning = BooleanField('Allow admins to provision non default container')
    submit = SubmitField('Save')

@refbp.route('/admin/system/settings/', methods=('GET', 'POST'))
@admin_required
def view_system_settings():

    #Group settings belong here
    group_settings = GroupSettings(request.form, prefix='group_settings')
    if group_settings.submit.data and group_settings.validate():
        SystemSetting.set_user_groups_size_limit(group_settings.group_size.data)
        SystemSetting.set_user_groups_enabled(group_settings.groups_enable.data)
    else:
        group_settings.group_size.data = SystemSetting.get_user_groups_size_limit()
        group_settings.groups_enable.data = SystemSetting.get_user_groups_enabled()

    ssh_settings = SshSettings(request.form, prefix='ssh_settings')
    if ssh_settings.submit.data and ssh_settings.validate():
        SystemSetting.set_ssh_welcome_header(ssh_settings.welcome_header.data)
    else:
        ssh_settings.welcome_header.data = SystemSetting.get_ssh_welcome_header()

    return render_template('system_settings.html', group_settings=group_settings, ssh_settings=ssh_settings)

