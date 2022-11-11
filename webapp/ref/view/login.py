import datetime
import uuid

from Crypto.PublicKey import RSA
from flask import (Blueprint, Flask, Response, current_app, redirect,
                   render_template, request, url_for)
from itsdangerous import URLSafeTimedSerializer
from werkzeug.local import LocalProxy
from wtforms import (Form, IntegerField, PasswordField, RadioField,
                     StringField, SubmitField, validators)

from flask_login import current_user, login_user, logout_user
from ref import db, refbp
from ref.core import flash
from ref.core.util import redirect_to_next
from ref.model import User

log = LocalProxy(lambda: current_app.logger)

class LoginForm(Form):
    username = StringField('Matriculation Number', validators=[validators.DataRequired(), validators.Regexp(r'[0-9]+')], default='')
    password = PasswordField('Password', validators=[validators.DataRequired()])
    submit = SubmitField('Login')


@refbp.route('/logout', methods=('GET', 'POST'))
def logout():
    logout_user()
    return redirect(url_for('ref.login'))

@refbp.route('/login', methods=('GET', 'POST'))
def login():
    """
    This endpoint allows a user to login.
    """
    if current_user.is_authenticated:
        if  current_user.is_admin:
            #Only redirect admins, since non admin users are going to be redirected
            #back to this page...
            return redirect(url_for('ref.exercise_view_all'))
        elif current_user.is_grading_assistant:
            return redirect(url_for('ref.grading_view_all'))

    form = LoginForm(request.form)
    if form.submit.data and form.validate():
        log.info(f'Got login request for user {form.username.data}')
        #Right now we allow the mat. num. and the login_name as login
        user: User = User.query.filter_by(mat_num=form.username.data).one_or_none()
        if not user:
            form.password.errors += ['Invalid username or password']
            form.password.errors += ['Please note that this login is not supposed to be used by students.']
            return render_template('login.html', form=form)

        log.info(f'User found {user} {form.password.data}')

        if user is None or not user.check_password(form.password.data) or (not user.is_admin and not user.is_grading_assistant):
            form.password.errors += ['Invalid username or password']
            form.password.errors += ['Please note that this login is not supposed to be used by students.']
            return render_template('login.html', form=form)

        if user.login_token is None:
            user.login_token = str(uuid.uuid4())
            current_app.db.session.add(user)
            current_app.db.session.commit()
        login_user(user)
        return redirect_to_next()

    return render_template('login.html', form=form)
