import datetime
import re
from functools import partial

from Crypto.PublicKey import RSA, DSA, ECC
from flask import (Blueprint, Flask, Response, abort, current_app, redirect,
                   render_template, request, url_for)
from itsdangerous import URLSafeTimedSerializer
from sqlalchemy.exc import IntegrityError, OperationalError
from werkzeug.local import LocalProxy
from wtforms import (BooleanField, Form, IntegerField, PasswordField,
                     RadioField, SelectMultipleField, StringField, SubmitField,
                     ValidationError, validators)

from ref import db, limiter, refbp
from ref.core import admin_required, flash
from ref.core.util import (is_deadlock_error, lock_db, on_integrity_error,
                           redirect_to_next,
                           set_transaction_deferable_readonly)
from ref.model import SystemSettingsManager, User, UserGroup
from ref.model.enums import UserAuthorizationGroups

PASSWORD_MIN_LEN = 8
PASSWORD_SECURITY_LEVEL = 3

# Salt used to sign download links returned to the user.
DOWNLOAD_LINK_SIGN_SALT = 'dl-keys'

MAT_REGEX = r"^[0-9]+$"
GROUP_REGEX = r"^[a-zA-Z0-9-_]+$"

log = LocalProxy(lambda: current_app.logger)


class StringFieldDefaultEmpty(StringField):

    def __init__(self, *args, **kwargs):
        if 'default' not in kwargs:
            kwargs['default'] = ''
        super().__init__(*args, **kwargs)


def field_to_str(form, field):
    del form
    return str(field.data)


def validate_password(form, field):
    """
    Implements a simple password policy.
    Raises:
        ValidationError: If the password does not fullfill the policy.
    """
    del form
    password = field.data

    if len(password) < PASSWORD_MIN_LEN:
        raise ValidationError(
            f'Password must be at least {PASSWORD_MIN_LEN} characters long.')

    digit = re.search(r"\d", password) is not None
    upper = re.search(r"[A-Z]", password) is not None
    lower = re.search(r"[a-z]", password) is not None
    special = re.search(
        r"[ !#$%&'()*+,-./[\\\]^_`{|}~"+r'"]', password) is not None

    if sum([digit, upper, lower, special]) < PASSWORD_SECURITY_LEVEL:
        raise ValidationError(
            'Password not strong enough. Try to use a mix of digits, upper- and lowercase letters.')

def validate_pubkey(form, field):
    """
    Validates an SSH key in the OpenSSH format. If the passed field was left empty,
    validation is also successfull since in this case we generte a public/private
    key pair.
    Raises:
         ValidationError: If the key could not be parsed.
    """
    del form
    if field.data is None or field.data == '':
        return

    for fn in [RSA.import_key]:
        try:
            # Replace the key with the parsed one, thus we use everywhere exactly
            # the same string to represent a specific key.
            key = fn(field.data).export_key(format='OpenSSH').decode()
            field.data = key
            return key
        except:
            pass
        else:
            return

    log.info(f'Invalid public-key {field.data}.')
    raise ValidationError('Invalid Public-Key.')


class EditUserForm(Form):
    id = IntegerField('ID')
    mat_num = StringFieldDefaultEmpty('Matriculation Number', validators=[
        validators.DataRequired(),
        validators.Regexp(MAT_REGEX),
        # FIXME: Field is implemented as number field in the view.
        field_to_str
    ])
    firstname = StringFieldDefaultEmpty('Firstname', validators=[
                            validators.DataRequired()])
    surname = StringFieldDefaultEmpty('Surname', validators=[validators.DataRequired()])
    auth_group = SelectMultipleField('Authorization Groups',
                                     choices=[
                                         (e.value, e.value) for e in UserAuthorizationGroups
                                     ]
                                     )
    password = PasswordField('Password', default='')
    password_rep = PasswordField('Password (Repeat)', default='')
    is_admin = BooleanField('Is Admin?')
    pubkey = StringFieldDefaultEmpty('Pubkey', validators=[
        validators.DataRequired(),
        validate_pubkey
        ]
    )

    submit = SubmitField('Update')


class GetKeyForm(Form):
    mat_num = StringFieldDefaultEmpty('Matriculation Number', validators=[
        validators.DataRequired(),
        validators.Regexp(MAT_REGEX),
        field_to_str
    ])
    firstname = StringFieldDefaultEmpty('Firstname', validators=[
                            validators.DataRequired()], default='')
    surname = StringFieldDefaultEmpty('Surname', validators=[validators.DataRequired()])
    password = PasswordField('Password',
                             validators=[
                                 validators.DataRequired(), validate_password
                             ], default=''
                             )
    password_rep = PasswordField('Password (Repeat)',
                                 validators=[
                                     validators.DataRequired(), validate_password
                                 ], default=''
                                 )
    pubkey = StringFieldDefaultEmpty('Public RSA Key (if empty, a key-pair is generated for you)',
                         validators=[
                             validate_pubkey
                         ]
                         )
    submit = SubmitField('Get Key')


class RestoreKeyForm(Form):
    mat_num = StringFieldDefaultEmpty('Matriculation Number', validators=[
        validators.DataRequired(),
        validators.Regexp(MAT_REGEX),
        field_to_str  # FIXME: Field is implemented as number in view.
    ])
    password = PasswordField('Password (The password used during first retrieval)', validators=[
                             validators.DataRequired()], default='')
    submit = SubmitField('Restore')


@refbp.route('/student/download/pubkey/<string:signed_mat>')
@limiter.limit('16 per minute;1024 per day')
def student_download_pubkey(signed_mat: str):
    """
    Returns the public key of the given matriculation number as
    text/plain.
    Args:
        signed_mat: The signed matriculation number.
    """
    signer = URLSafeTimedSerializer(
        current_app.config['SECRET_KEY'], salt=DOWNLOAD_LINK_SIGN_SALT)
    try:
        mat_num = signer.loads(signed_mat, max_age=60*10)
    except:
        log.warning('Invalid signature', exc_info=True)
        abort(400)

    student = User.query.filter(User.mat_num == mat_num).one_or_none()
    if student:
        return Response(
            student.pub_key,
            mimetype="text/plain",
            headers={"Content-disposition":
                     "attachment; filename=id_rsa.pub"})

    flash.error('Unknown student')
    abort(400)


@refbp.route('/student/download/privkey/<string:signed_mat>')
@limiter.limit('16 per minute;1024 per day')
def student_download_privkey(signed_mat: str):
    """
    Returns the private key of the given matriculation number as
    text/plain.
    Args:
        signed_mat: The signed matriculation number.
    """
    signer = URLSafeTimedSerializer(
        current_app.config['SECRET_KEY'], salt=DOWNLOAD_LINK_SIGN_SALT)
    try:
        mat_num = signer.loads(signed_mat, max_age=60*10)
    except Exception:
        log.warning('Invalid signature', exc_info=True)
        abort(400)

    student = User.query.filter(User.mat_num == mat_num).one_or_none()
    if student:
        return Response(
            student.priv_key,
            mimetype="text/plain",
            headers={"Content-disposition":
                     "attachment; filename=id_rsa"})

    flash.error('Unknown student')
    abort(400)


@refbp.route('/student/getkey', methods=('GET', 'POST'))
@limiter.limit('16 per minute;1024 per day')
def student_getkey():
    """
    Endpoint used to genereate a public/private key pair used by the students
    for authentication to get access to the exercises.
    """

    regestration_enabled = SystemSettingsManager.REGESTRATION_ENABLED.value
    if not regestration_enabled:
        flash.warning("Regestration is currently disabled. Please contact the staff if you need to register.")
        # Fallthrough

    form = GetKeyForm(request.form)

    pubkey = None
    privkey = None
    signed_mat = None
    student = None

    def render(): return render_template('student_getkey.html',
                                         route_name='get_key',
                                         form=form,
                                         student=student,
                                         pubkey=pubkey,
                                         privkey=privkey,
                                         signed_mat=signed_mat,
                                         )

    if regestration_enabled and form.submit.data and form.validate():
        # Check if the matriculation number is already registered.
        existing_student = User.query.filter(
            User.mat_num == form.mat_num.data).one_or_none()
        if existing_student:
            form.mat_num.errors += [
                'Already registered, please use your password to restore the key.']
            return render()

        # Check if the pubkey is already regsitered.
        if form.pubkey.data:
            # NOTE: The .data was validated by the form.
            pubkey = form.pubkey.data

            # Check for duplicated key
            existing_student = User.query.filter(
                User.pub_key == pubkey).one_or_none()
            if existing_student:
                form.pubkey.errors += [
                    'Already registered, please use your password to restore the key.']
                return render()

        # Check password fields
        if form.password.data != form.password_rep.data:
            err = ['Passwords do not match!']
            form.password.errors += err
            form.password_rep.errors += err
            form.password.data = ""
            form.password_rep.data = ""
            return render()

        # If a public key was provided use it, if not, generate a key pair.
        if form.pubkey.data:
            pubkey = form.pubkey.data
            privkey = None
        else:
            key = RSA.generate(2048)
            pubkey = key.export_key(format='OpenSSH').decode()
            privkey = key.export_key().decode()

        student = User()
        student.mat_num = form.mat_num.data
        student.first_name = form.firstname.data
        student.surname = form.surname.data

        student.set_password(form.password.data)
        student.pub_key = pubkey
        student.priv_key = privkey
        student.registered_date = datetime.datetime.utcnow()
        student.auth_groups = [UserAuthorizationGroups.STUDENT]

        signer = URLSafeTimedSerializer(
            current_app.config['SECRET_KEY'], salt=DOWNLOAD_LINK_SIGN_SALT)
        signed_mat = signer.dumps(str(student.mat_num))

        db.session.add(student)
        db.session.commit()

        return render()


    return render()


@refbp.route('/student/restoreKey', methods=('GET', 'POST'))
@limiter.limit('16 per minute;1024 per day')
def student_restorekey():
    """
    This endpoint allows a user to restore its key using its matriculation number
    and password that was initially used to create the account.
    """
    form = RestoreKeyForm(request.form)
    pubkey = None
    privkey = None
    signed_mat = None

    def render(): return render_template('student_restorekey.html',
                                         route_name='restore_key',
                                         form=form,
                                         pubkey=pubkey,
                                         privkey=privkey,
                                         signed_mat=signed_mat)

    signer = URLSafeTimedSerializer(
        current_app.config['SECRET_KEY'], salt=DOWNLOAD_LINK_SIGN_SALT)

    if form.submit.data and form.validate():
        student = User.query.filter(
            User.mat_num == form.mat_num.data).one_or_none()
        if student:
            if student.check_password(form.password.data):
                signed_mat = signer.dumps(str(student.mat_num))
                pubkey = student.pub_key
                privkey = student.priv_key
                return render()
            else:
                form.password.errors += [
                    'Wrong password or matriculation number unknown.']
                return render()
        else:
            form.password.errors += [
                'Wrong password or matriculation number unknown.']
            return render()

    return render()


@refbp.route('/admin/student/view', methods=('GET', 'POST'))
@admin_required
def student_view_all():
    """
    List all students currently registered.
    """
    students = User.query.order_by(User.id).all()
    return render_template('student_view_all.html', students=students)


@refbp.route('/admin/student/view/<int:user_id>')
@admin_required
def student_view_single(user_id):
    """
    Shows details for the user that belongs to the given user_id.
    """
    user = User.query.filter(User.id == user_id).one_or_none()
    if not user:
        flash.error(f'Unknown user ID {user_id}')
        abort(400)

    return render_template('student_view_single.html', user=user)


@refbp.route('/admin/student/edit/<int:user_id>', methods=('GET', 'POST'))
@admin_required
def student_edit(user_id):
    """
    Edit the user with the id user_id.
    """
    form = EditUserForm(request.form)

    user: User = User.query.filter(
        User.id == user_id).one_or_none()
    if not user:
        flash.error(f'Unknown user ID {user_id}')
        abort(400)

    if form.submit.data and form.validate():
        # Form was submitted

        if form.password.data != '':
            if form.password.data != form.password_rep.data:
                form.password.errors += ['Passwords do not match']
                return render_template('user_edit.html', form=form)
            else:
                user.set_password(form.password.data)
                user.invalidate_session()

        mat_num = form.mat_num.data
        if User.query.filter(User.mat_num == mat_num).one_or_none() not in [None, user]:
            form.mat_num.errors += ['Already taken']
            return render_template('user_edit.html', form=form)

        pubkey = form.pubkey.data
        if User.query.filter(User.pub_key == pubkey).one_or_none():
            form.pubkey.errors += ['Already taken']
            return render_template('user_edit.html', form=form)

        user.mat_num = mat_num
        user.first_name = form.firstname.data
        user.surname = form.surname.data
        user.pub_key = form.pubkey.data

        # Invalidate login if the authentication group changed
        new_auth_groups = set()
        for auth_group in form.auth_group.data:
            new_auth_groups.add(UserAuthorizationGroups(auth_group))
        if new_auth_groups != set(user.auth_groups):
            user.invalidate_session()
        user.auth_groups = list(new_auth_groups)

        current_app.db.session.add(user)
        current_app.db.session.commit()

        flash.success('Updated!')
        return render_template('user_edit.html', form=form)
    else:
        # Form was not submitted: Set initial values
        form.id.data = user.id
        form.mat_num.data = user.mat_num
        form.firstname.data = user.first_name
        form.surname.data = user.surname
        form.pubkey.data = user.pub_key
        form.auth_group.data = [e.value for e in user.auth_groups]
        # Leave password empty
        form.password.data = ''
        form.password_rep.data = ''

    return render_template('user_edit.html', form=form)


@refbp.route('/admin/student/delete/<int:user_id>')
@admin_required
def student_delete(user_id):
    """
    Deletes the given user.
    """
    user: User = User.query.filter(
        User.id == user_id).one_or_none()

    if not user:
        flash.warning(f'Unknown user ID {user_id}')
        return redirect_to_next()

    if user.is_admin:
        flash.warning('Admin users can not be deleted')
        return redirect_to_next()

    if len(user.exercise_instances) > 0:
        flash.error('User has active instances, please delete them first!')
        return redirect_to_next()

    current_app.db.session.delete(user)
    current_app.db.session.commit()
    flash.success(f'User {user.id} deleted')

    return redirect_to_next()


@refbp.route('/student/')
@refbp.route('/student')
@refbp.route('/')
def student_default_routes():
    """
    Redirect some urls to the key retrival form.
    """
    return redirect(url_for('ref.student_getkey'))
