import datetime
import re

from flask import (Blueprint, Flask, Response, current_app, redirect,
                   render_template, request, url_for)
from itsdangerous import URLSafeTimedSerializer

from Crypto.PublicKey import RSA
from ref import db, refbp
from ref.core import admin_required, flash
from ref.core.util import redirect_to_next
from ref.model import SystemSettingsManager
from ref.model import User, UserGroup
from ref.model.enums import CourseOfStudies
from wtforms import (BooleanField, Form, IntegerField, PasswordField,
                     RadioField, StringField, SubmitField, TextField,
                     validators, SelectField)


@refbp.route('/admin/group/view/', methods=('GET', 'POST'))
@admin_required
def group_view_all():
    groups = UserGroup.query.order_by(UserGroup.id).all()
    return render_template('group_view_all.html', groups=groups, max_group_size=SystemSettingsManager.GROUP_SIZE.value)

@refbp.route('/admin/group/delete/<int:group_id>', methods=('GET', 'POST'))
@admin_required
def group_delete(group_id):
    group = UserGroup.query.filter(UserGroup.id == group_id).one_or_none()
    if not group:
        flash.error(f'Unknown group ID {group_id}')
        return render_template('400.html'), 400

    if len(group.users) > 0:
        flash.error(f'Unable to delete non-empty group')
        return redirect_to_next()

    current_app.db.session.delete(group)
    current_app.db.session.commit()

    flash.info(f'Group {group.name} successfully deleted')
    return redirect_to_next()

@refbp.route('/admin/group/view/<int:group_id>/users', methods=('GET', 'POST'))
@admin_required
def group_view_users(group_id):
    group = UserGroup.query.filter(UserGroup.id == group_id).one_or_none()
    if not group:
        flash.error(f'Unknown group ID {group_id}')
        return render_template('400.html'), 400

    students = User.query.order_by(User.id).all()
    students = [s for s in students if s.group and s.group.id == group_id]
    return render_template('student_view_all.html', students=students)

#@refbp.route('/admin/group/view/<int:user_id>', methods=('GET', 'POST'))