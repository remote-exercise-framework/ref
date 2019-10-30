from flask import Flask, render_template, Blueprint, redirect, url_for, request, Response, current_app
from wtforms import Form, IntegerField, validators, SubmitField, RadioField, TextField, PasswordField, StringField
from ref import refbp, db
from ref.model import User
import datetime
from Crypto.PublicKey import RSA
from itsdangerous import URLSafeTimedSerializer
from ref.core import flash
from flask_login import current_user, login_user, logout_user


class LoginForm(Form):
    username = StringField('Username', validators=[validators.Required()])
    password = PasswordField('Password', validators=[validators.Required()])
    submit = SubmitField('Login')


@refbp.route('/logout', methods=('GET', 'POST'))
def logout():
    logout_user()
    return redirect(url_for('ref.login'))

@refbp.route('/login', methods=('GET', 'POST'))
def login():
    """
    This endpoint allows a user to restore its key using its matriculation number
    and password that was initially used to create the account.
    """
    if current_user.is_authenticated:
        return redirect(url_for('ref.exercise_view_all'))

    form = LoginForm(request.form)
    if form.submit.data and form.validate():
        user = User.query.filter_by(login_name=form.username.data).first()
        if user is None:
            user = User.query.filter_by(mat_num=form.username.data).first()

        if user is None or not user.check_password(form.password.data):
            flash.error('Invalid username or password')
            return render_template('login.html', form=form)
        login_user(user)
        return redirect(url_for('ref.login'))

    return render_template('login.html', form=form)