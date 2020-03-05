import datetime
import re

from flask import (Blueprint, Flask, Response, current_app, redirect,
                   render_template, request, url_for)
from itsdangerous import URLSafeTimedSerializer

from Crypto.PublicKey import RSA
from ref import db, refbp
from ref.core import admin_required, flash
from ref.core.util import redirect_to_next
from ref.model import User, UserGroup, SystemSettingsManager
from ref.model.enums import CourseOfStudies
from werkzeug.local import LocalProxy
from wtforms import (BooleanField, Form, IntegerField, PasswordField,
                     RadioField, StringField, SubmitField, TextField,
                     validators, SelectField, ValidationError)

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
    try:
        key = RSA.importKey(field.data)
    except:
        raise ValidationError('Invalid Public-Key.')

class EditUserForm(Form):
    id = IntegerField('ID')
    mat_num = StringField('Matriculation Number', validators=[
        validators.DataRequired(),
        validators.Regexp(mat_regex),
        validate_matriculation_number
        ])
    course = RadioField('Course of Study', choices=[(e.value, e.value) for e in CourseOfStudies])
    firstname = StringField('Firstname', validators=[validators.DataRequired()])
    surname = StringField('Surname', validators=[validators.DataRequired()])
    nickname = StringField('Nickname', validators=[validators.DataRequired()])
    group_name = StringField('Group', validators=[validators.Optional(), validators.Regexp(group_regex)])

    password = PasswordField('Password')
    password_rep = PasswordField('Password (Repeat)')
    is_admin = BooleanField('Is Admin?')


    submit = SubmitField('Update')

class GetKeyForm(Form):
    mat_num = StringField('Matriculation Number', validators=[
        validators.DataRequired(),
        validators.Regexp(mat_regex),
        validate_matriculation_number
        ])
    course = RadioField('Course of Study', choices=[(e.value, e.value) for e in CourseOfStudies])
    firstname = StringField('Firstname', validators=[validators.DataRequired()])
    surname = StringField('Surname', validators=[validators.DataRequired()])
    nickname = StringField('Nickname', validators=[validators.DataRequired()])
    group_name = StringField('Group', validators=[validators.Optional(), validators.Regexp(group_regex)])

    password = PasswordField('Password', validators=[validators.DataRequired()])
    password_rep = PasswordField('Password (Repeat)', validators=[validators.DataRequired()])

    pubkey = StringField('Public-Key (if empty, a key-pair is generated for you)', validators=[validators.Optional(), validate_pubkey])

    submit = SubmitField('Get Key')

class RestoreKeyForm(Form):
    mat_num = StringField('Matriculation Number', validators=[
        validators.DataRequired(),
        validators.Regexp(mat_regex),
        validate_matriculation_number
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
    except Exception as e:
        flash.error('Provided token is invalid')
        return render_template('400.html'), 400

    student = User.query.filter(User.mat_num == mat_num).first()
    if student:
        return Response(
            student.pub_key,
            mimetype="text/plain",
            headers={"Content-disposition":
                    "attachment; filename=id_rsa.pub"})
    else:
        flash.error('Unknown student')
        return render_template('400.html'), 400

@refbp.route('/student/download/privkey/<string:signed_mat>')
def student_download_privkey(signed_mat):
    """
    Returns the private key of the given matriculation number as
    text/plain.
    """
    signer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='dl-keys')
    try:
        mat_num = signer.loads(signed_mat, max_age=60*10)
    except Exception as e:
        flash.error('Provided token is invalid')
        return render_template('400.html'), 400

    student = User.query.filter(User.mat_num == mat_num).first()
    if student:
        return Response(
            student.priv_key,
            mimetype="text/plain",
            headers={"Content-disposition":
                    "attachment; filename=id_rsa"})
    else:
        flash.error('Unknown student')
        return render_template('400.html'), 400

@refbp.route('/student/getkey', methods=('GET', 'POST'))
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
        student = User.query.filter(User.mat_num == form.mat_num.data).first()
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

            if groups_enabled:
                group = UserGroup.query.filter(UserGroup.name == form.group_name.data).one_or_none()
                if not group and form.group_name.data:
                    group = UserGroup()
                    group.name = form.group_name.data
            else:
                group = None
            student.group = group

            student.set_password(form.password.data)
            student.pub_key = pubkey
            student.pub_key_ssh = pubkey
            student.priv_key = privkey
            student.registered_date = datetime.datetime.utcnow()
            student.course_of_studies = CourseOfStudies(form.course.data)
            student.is_admin = False
            db.session.add(student)
            db.session.commit()

            signer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='dl-keys')
            signed_mat = signer.dumps(str(student.mat_num))

            return render()
        else:
            form.mat_num.errors += ['Already registered, please use your password to restore key.']


    return render()

@refbp.route('/student/restoreKey', methods=('GET', 'POST'))
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
        student = User.query.filter(User.mat_num == form.mat_num.data).first()
        if student:
            if student.check_password(form.password.data):
                signed_mat = signer.dumps(str(student.mat_num))
                pubkey = student.pub_key
                privkey = student.priv_key
                return render()
            else:
                form.password.errors += ['Wrong password']
                return render()
        else:
            form.mat_num.errors += ['Unknown matriculation number']
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
    user =  User.query.filter(User.id == user_id).first()
    if not user:
        flash.error(f'Unknown user ID {user_id}')
        return render_template('400.html'), 400

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

    user: User = User.query.filter(User.id == user_id).first()
    if not user:
        flash.error(f'Unknown user ID {user_id}')
        return render_template('400.html'), 400

    if form.submit.data and form.validate():
        if form.password.data != '':
            if form.password.data != form.password_rep.data:
                form.password.errors += ['Passwords do not match']
                return render_template('user_edit.html', form=form)
            else:
                user.set_password(form.password.data)
                user.invalidate_session()
        user.mat_num = form.mat_num.data
        user.course_of_studies = CourseOfStudies(form.course.data)
        user.first_name = form.firstname.data
        user.surname = form.surname.data
        user.nickname = form.nickname.data

        group = UserGroup.query.filter(UserGroup.name == form.group_name.data).one_or_none()
        #Only create a group if the name was set
        if not group and form.group_name.data:
            group = UserGroup()
            group.name = form.group_name.data
        user.group = group

        if form.is_admin.data != user.is_admin:
            user.invalidate_session()
        user.is_admin = form.is_admin.data
        current_app.db.session.add(user)
        current_app.db.session.commit()
        flash.success('Updated!')
        return render_template('user_edit.html', form=form)
    else:
        form.id.data = user.id
        form.mat_num.data = user.mat_num
        form.course.data = user.course_of_studies.value
        form.firstname.data = user.first_name
        form.surname.data = user.surname
        form.nickname.data = user.nickname
        if user.group:
            form.group_name.data = user.group.name
        form.is_admin.data = user.is_admin
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
    user: User =  User.query.filter(User.id == user_id).first()
    if not user:
        flash.error(f'Unknown user ID {user_id}')
        return render_template('400.html'), 400

    if user.is_admin:
        flash.warning('Admin users can not be deleted')
        return redirect_to_next()

    if len(user.exercise_instances) > 0:
        flash.error('User has active instances, please delete them first!')
    else:
        current_app.db.session.delete(user)
        current_app.db.session.commit()
        flash.success(f'User {user.id} deleted')

    return redirect_to_next()

@refbp.route('/student', methods=('GET', 'POST'))
@refbp.route('/', methods=('GET', 'POST'))
def student_default_routes():
    """
    List all students currently registered.
    """
    return redirect(url_for('ref.student_getkey'))
