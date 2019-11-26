from flask import Flask, render_template, Blueprint, redirect, url_for, request, Response, current_app
from wtforms import Form, IntegerField, validators, SubmitField, RadioField, TextField, PasswordField, StringField
from ref import refbp, db
from ref.model import User
import datetime
from Crypto.PublicKey import RSA
from itsdangerous import URLSafeTimedSerializer
from ref.core import flash
from flask_login import current_user, login_user, logout_user
from ref.core.util import redirect_to_next
from werkzeug.local import LocalProxy

log = LocalProxy(lambda: current_app.logger)

class LoginForm(Form):
    username = StringField('Matriculation Number', validators=[validators.Required(), validators.Regexp(r'[0-9]+')], default='')
    password = PasswordField('Password', validators=[validators.Required()])
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
    if current_user.is_authenticated and current_user.is_admin:
        #Only redirect admins, since non admin users are going to be redirected
        #back to this page...
        return redirect(url_for('ref.exercise_view_all'))

    form = LoginForm(request.form)
    if form.submit.data and form.validate():
        log.info(f'Got login request for user {form.username.data}')
        #Right now we allow the mat. num. and the login_name as login
        user = User.query.filter_by(mat_num=form.username.data).first()

        if user is None or not user.check_password(form.password.data) or not user.is_admin:
            flash.error('Invalid username or password')
            return render_template('login.html', form=form)
        login_user(user)
        return redirect_to_next()

    return render_template('login.html', form=form)