import datetime
import re

from Crypto.PublicKey import RSA
from flask import (Blueprint, Flask, Response, abort, current_app, redirect,
                   render_template, request, url_for)
from itsdangerous import URLSafeTimedSerializer
from psycopg2.errors import DeadlockDetected
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import joinedload, raiseload
from werkzeug.local import LocalProxy
from wtforms import (BooleanField, Form, IntegerField, PasswordField,
                     RadioField, SelectField, SelectMultipleField, StringField,
                     SubmitField, TextField, ValidationError, validators)

from ref import db, limiter, refbp
from ref.core import admin_required, flash
from ref.core.util import (is_deadlock_error, lock_db, on_integrity_error,
                           redirect_to_next,
                           set_transaction_deferable_readonly)
from ref.model import SystemSettingsManager, User, UserGroup
from ref.model.enums import CourseOfStudies, UserAuthorizationGroups

#mat_regex = r"^1080[0-2][0-9][1-2][0-9]{5}$"
mat_regex = r"^[0-9]+$"
group_regex = r"^[a-zA-Z0-9-_]+$"

log = LocalProxy(lambda: current_app.logger)

# class SelectOrStringField(StringField):

#     def __init__(self, *args, **kwargs):
#         if 'choices' in kwargs:
#             self.choices = kwargs['choices']
#             del kwargs['choices']
#         super().__init__(self, *args, **kwargs)
#         self.label = args[0]

def field_to_str(form, field):
    return str(field.data)

def validate_password(form, field):
    password = field.data

    MIN_LEN = 8

    if len(password) < MIN_LEN:
        raise ValidationError(f'Password must be at least {MIN_LEN} characters long.')

    digit = re.search(r"\d", password) is not None
    upper = re.search(r"[A-Z]", password) is not None
    lower = re.search(r"[a-z]", password) is not None
    special = re.search(r"[ !#$%&'()*+,-./[\\\]^_`{|}~"+r'"]', password) is not None

    if sum([digit, upper, lower, special]) < 3:
        raise ValidationError(f'Password not strong enough. Try to use a mix of digits, upper- and lowercase letters.')

def validate_matriculation_number(form, field):
    """
    Checksums matriculation number. Raises ValidationError if not a valid matriculation number.
    """
    if not field.data.startswith("1080"):
        log.info(f"Not a valid RUB matriculation number {field.data}")
        return
    if len(field.data) != 12:
        log.info(f"Matriculation number has less than 12 characters.")
        raise ValidationError('Matriculation number must have 12 characters')
    checksum = 0
    for i in range(10 + 1):
        tmp = int(field.data[i]) + 1
        tmp *= ((i + 1) % 3) + 1
        tmp -= 1 if tmp > 10 else 0
        tmp -= 1 if tmp > 20 else 0
        checksum += tmp
    checksum_str = str(checksum % 10)
    if field.data[-1] != checksum_str:
        log.info(f"Invalid matriculation number {field.data} - checksum is {checksum_str}")
        raise ValidationError('Invalid matriculation number: checksum failure')

def validate_pubkey(form, field):
    if field.data is None or field.data == '':
        return
    try:
        RSA.importKey(field.data)
    except:
        raise ValidationError('Invalid Public-Key.')

class EditUserForm(Form):
    id = IntegerField('ID')
    mat_num = StringField('Matriculation Number', validators=[
        validators.DataRequired(),
        validators.Regexp(mat_regex),
        validate_matriculation_number,
        field_to_str
        ])
    course = RadioField('Course of Study', choices=[(e.value, e.value) for e in CourseOfStudies])
    firstname = StringField('Firstname', validators=[validators.DataRequired()])
    surname = StringField('Surname', validators=[validators.DataRequired()])
    nickname = StringField('Nickname', validators=[validators.DataRequired()])
    group_name = StringField('Group', validators=[validators.Optional(), validators.Regexp(group_regex)])

    auth_group = SelectMultipleField('Authorization Groups', choices=[(e.value, e.value) for e in UserAuthorizationGroups])

    password = PasswordField('Password')
    password_rep = PasswordField('Password (Repeat)')
    is_admin = BooleanField('Is Admin?')


    submit = SubmitField('Update')

class GetKeyForm(Form):
    mat_num = StringField('Matriculation Number', validators=[
        validators.DataRequired(),
        validators.Regexp(mat_regex),
        validate_matriculation_number,
        field_to_str
        ])
    course = RadioField('Course of Study', choices=[(e.value, e.value) for e in CourseOfStudies])
    firstname = StringField('Firstname', validators=[validators.DataRequired()])
    surname = StringField('Surname', validators=[validators.DataRequired()])
    nickname = StringField('Nickname', validators=[validators.DataRequired()])
    group_name = StringField('Group', validators=[validators.Optional(), validators.Regexp(group_regex)])

    password = PasswordField('Password', validators=[validators.DataRequired(), validate_password])
    password_rep = PasswordField('Password (Repeat)', validators=[validators.DataRequired(), validate_password])

    pubkey = StringField('Public-Key (if empty, a key-pair is generated for you)', validators=[validate_pubkey])

    submit = SubmitField('Get Key')

class RestoreKeyForm(Form):
    mat_num = StringField('Matriculation Number', validators=[
        validators.DataRequired(),
        validators.Regexp(mat_regex),
        validate_matriculation_number,
        field_to_str
        ])
    password = PasswordField('Password (The password used during first retrieval)', validators=[validators.DataRequired()])
    submit = SubmitField('Restore')

@refbp.route('/student/download/pubkey/<string:signed_mat>')
def student_download_pubkey(signed_mat):
    """
    Returns the public key of the given matriculation number as
    text/plain.
    """
    signer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='dl-keys')
    try:
        mat_num = signer.loads(signed_mat, max_age=60*10)
    except Exception :
        log.warning('Invalid signature', exc_info=True)
        abort(400)

    student = User.query.filter(User.mat_num == mat_num).one_or_none()
    if student:
        return Response(
            student.pub_key,
            mimetype="text/plain",
            headers={"Content-disposition":
                    "attachment; filename=id_rsa.pub"})
    else:
        flash.error('Unknown student')
        abort(400)

@refbp.route('/student/download/privkey/<string:signed_mat>')
def student_download_privkey(signed_mat):
    """
    Returns the private key of the given matriculation number as
    text/plain.
    """
    signer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='dl-keys')
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
    else:
        flash.error('Unknown student')
        abort(400)

@refbp.route('/student/getkey', methods=('GET', 'POST'))
@limiter.limit('16 per minute;1024 per day')
def student_getkey():
    """
    Endpoint used to genereate a public/private key pair used by the students
    for authentication to get access to the exercises.
    """

    form = GetKeyForm(request.form)

    #Get valid group names
    groups = UserGroup.all()
    form.group_name.choices = [e.name for e in groups]

    pubkey = None
    privkey = None
    signed_mat = None
    student = None

    groups_enabled = SystemSettingsManager.GROUPS_ENABLED.value
    render = lambda: render_template('student_getkey.html', route_name='get_key', form=form, student=student, pubkey=pubkey, privkey=privkey, signed_mat=signed_mat, groups_enabled=groups_enabled)

    if form.submit.data and form.validate():
        student = User.query.filter(User.mat_num == form.mat_num.data).one_or_none()
        if not student:
            if form.password.data != form.password_rep.data:
                err = ['Passwords do not match!']
                form.password.errors += err
                form.password_rep.errors += err
                form.password.data = ""
                form.password_rep.data = ""
                return render()

            if form.pubkey.data:
                key = RSA.importKey(form.pubkey.data)
                pubkey = key.export_key(format='OpenSSH').decode()
                privkey = None
            else:
                key = RSA.generate(2048)
                pubkey = key.export_key(format='OpenSSH').decode()
                privkey = key.export_key().decode()
            student = User()
            student.invalidate_session()
            student.mat_num = form.mat_num.data
            student.first_name = form.firstname.data
            student.surname = form.surname.data
            student.nickname = form.nickname.data

            if User.query.filter(User.nickname == student.nickname).one_or_none():
                form.nickname.errors += ['Nickname already taken']
                pubkey = None
                privkey = None
                student = None
                return render()

            if groups_enabled:
                try:
                    group = UserGroup.query.filter(UserGroup.name == form.group_name.data).with_for_update().one_or_none()
                except OperationalError as e:
                    if is_deadlock_error(e):
                        flash.warning('Please retry.')
                        pubkey = None
                        privkey = None
                        student = None
                        return render()
                    raise

                if not group and form.group_name.data:
                    group = UserGroup()
                    group.name = form.group_name.data
                else:
                    group_mcnt = SystemSettingsManager.GROUP_SIZE.value
                    if len(group.users) >= group_mcnt:
                        form.group_name.errors += [f'Groups already reached the maximum of {group_mcnt} members']
                        pubkey = None
                        privkey = None
                        student = None
                        return render()
            else:
                group = None
            student.group = group

            student.set_password(form.password.data)
            student.pub_key = pubkey
            student.pub_key_ssh = pubkey
            student.priv_key = privkey
            student.registered_date = datetime.datetime.utcnow()
            student.course_of_studies = CourseOfStudies(form.course.data)
            student.auth_groups = [UserAuthorizationGroups.STUDENT]

            try:
                db.session.add(student)
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                on_integrity_error()
                pubkey = None
                privkey = None
                student = None
                return render()

            signer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='dl-keys')
            signed_mat = signer.dumps(str(student.mat_num))

            return render()
        else:
            form.mat_num.errors += ['Already registered, please use your password to restore key.']


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
    render = lambda: render_template('student_restorekey.html', route_name='restore_key', form=form, pubkey=pubkey, privkey=privkey, signed_mat=signed_mat)

    signer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='dl-keys')

    if form.submit.data and form.validate():
        student = User.query.filter(User.mat_num == form.mat_num.data).one_or_none()
        if student:
            if student.check_password(form.password.data):
                signed_mat = signer.dumps(str(student.mat_num))
                pubkey = student.pub_key
                privkey = student.priv_key
                return render()
            else:
                form.password.errors += ['Wrong password or matriculation number unknown.']
                return render()
        else:
            form.password.errors += ['Wrong password or matriculation number unknown.']
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
    user =  User.query.filter(User.id == user_id).one_or_none()
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

    #Get valid group names
    groups = UserGroup.all()
    form.group_name.choices = [e.name for e in groups]

    user: User = User.query.filter(User.id == user_id).with_for_update().one_or_none()
    if not user:
        flash.error(f'Unknown user ID {user_id}')
        abort(400)

    if form.submit.data and form.validate():
        #Form was submitted

        if form.password.data != '':
            if form.password.data != form.password_rep.data:
                form.password.errors += ['Passwords do not match']
                return render_template('user_edit.html', form=form)
            else:
                user.set_password(form.password.data)
                user.invalidate_session()

        if User.query.filter(User.mat_num == form.mat_num.data).one_or_none() not in [None, user]:
            form.mat_num.errors += ['Already taken']
            return render_template('user_edit.html', form=form)
        else:
            #Uniqueness enforced by DB constraint
            user.mat_num = form.mat_num.data

        user.course_of_studies = CourseOfStudies(form.course.data)
        user.first_name = form.firstname.data
        user.surname = form.surname.data

        if User.query.filter(User.nickname == form.nickname.data).one_or_none() not in [None, user]:
            form.nickname.errors += ['Nickname already taken']
            return render_template('user_edit.html', form=form)
        else:
            #Uniqueness enforced by DB constraint
            user.nickname = form.nickname.data

        #Lock the group to make sure we do not exceed the group size limit
        try:
            group = UserGroup.query.filter(UserGroup.name == form.group_name.data).with_for_update().one_or_none()
        except OperationalError as e:
            if is_deadlock_error(e):
                flash.warning('Concurrent access, please retry.')
                return render_template('user_edit.html', form=form)
            raise

        #Only create a group if the name was set
        if not group and form.group_name.data:
            #Multiple groups with same name might be created concurrently, but ony one will
            #win the DB unique constraint on commit.
            group = UserGroup()
            group.name = form.group_name.data
        user.group = group

        #Make sure there are not to many members in the group
        max_grp_size = SystemSettingsManager.GROUP_SIZE.value
        if group and len(group.users) > max_grp_size:
            form.group_name.errors += [f'Groups already reached the maximum of {max_grp_size} members']
            return render_template('user_edit.html', form=form)

        #Invalidate login if the authentication group changed
        new_auth_groups = set()
        for auth_group in form.auth_group.data:
            new_auth_groups.add(UserAuthorizationGroups(auth_group))
        if new_auth_groups != set(user.auth_groups):
            user.invalidate_session()
        user.auth_groups = list(new_auth_groups)

        try:
            current_app.db.session.add(user)
            current_app.db.session.commit()
            flash.success('Updated!')
        except IntegrityError:
            on_integrity_error()
        
        return render_template('user_edit.html', form=form)
    else:
        #Form was not submitted: Set initial values
        form.id.data = user.id
        form.mat_num.data = user.mat_num
        form.course.data = user.course_of_studies.value
        form.firstname.data = user.first_name
        form.surname.data = user.surname
        form.nickname.data = user.nickname
        if user.group:
            form.group_name.data = user.group.name
        form.auth_group.data = [e.value for e in user.auth_groups]
        #Leave password empty
        form.password.data = ''
        form.password_rep.data = ''


    return render_template('user_edit.html', form=form)


@refbp.route('/admin/student/delete/<int:user_id>')
@admin_required
def student_delete(user_id):
    """
    Deletes the given user.
    """
    user: User = User.query.filter(User.id == user_id).with_for_update().one_or_none()
    if not user:
        flash.warning(f'Unknown user ID {user_id}')
        return redirect_to_next()

    if user.is_admin:
        flash.warning('Admin users can not be deleted')
        return redirect_to_next()

    if len(user.exercise_instances) > 0:
        flash.error('User has active instances, please delete them first!')
        return redirect_to_next()

    try:
        current_app.db.session.delete(user)
        current_app.db.session.commit()
        flash.success(f'User {user.id} deleted')
    except IntegrityError:
        on_integrity_error()

    return redirect_to_next()

@refbp.route('/student', methods=('GET', 'POST'))
@refbp.route('/', methods=('GET', 'POST'))
def student_default_routes():
    """
    Redirect some urls to the key retrival form.
    """
    return redirect(url_for('ref.student_getkey'))
