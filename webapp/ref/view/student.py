from flask import Flask, render_template, Blueprint, redirect, url_for, request, Response, current_app
from wtforms import Form, IntegerField, validators, SubmitField, RadioField, TextField, PasswordField
from ref import refbp, db
from ref.model import User
from ref.model.enums import CourseOfStudies
import datetime
from Crypto.PublicKey import RSA
from itsdangerous import URLSafeTimedSerializer
from ref.core import flash, admin_required

"""
View the students can interact with (public).
"""

#(In case you lost your key, this password is required)
class GetKeyForm(Form):
    mat_num = IntegerField('Matriculation Number', validators=[validators.Required()])
    course = RadioField('Course of Study', choices=[(e, e.value) for e in CourseOfStudies])
    firstname = TextField('Firstname', validators=[validators.Required()])
    surname = TextField('Surname', validators=[validators.Required()])
    password = PasswordField('Password', validators=[validators.Required()])
    password_rep = PasswordField('Password (Repeat)', validators=[validators.Required()])
    submit = SubmitField('Get Key')

class RestoreKeyForm(Form):
    mat_num = IntegerField('Matriculation Number', validators=[validators.Required()])
    password = PasswordField('Password (The password used during first retrieval)', validators=[validators.Required()])
    submit = SubmitField('Restore')

@refbp.route('/student/download/pubkey/<string:signed_mat>')
def student_download_pubkey(signed_mat):
    """
    Returns the public key of the given matriculation number as
    text/plain.
    """
    signer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
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
    signer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
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
    pubkey = None
    privkey = None
    signed_mat = None
    student = None
    render = lambda: render_template('student_getkey.html', form=form, student=student, pubkey=pubkey, privkey=privkey, signed_mat=signed_mat)

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
            key = RSA.generate(2048)
            pubkey = key.export_key(format='OpenSSH').decode()
            privkey = key.export_key().decode()
            student = User()
            student.mat_num = form.mat_num.data
            student.first_name = form.firstname.data
            student.surname = form.surname.data
            student.set_password(form.password.data)
            student.pub_key = pubkey
            student.pub_key_ssh = pubkey
            student.priv_key = privkey
            student.registered_date = datetime.datetime.utcnow()
            student.course_of_studies = form.course.data
            student.is_admin = False
            db.session.add(student)
            db.session.commit()

            signer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
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
    render = lambda: render_template('student_restorekey.html', form=form, pubkey=pubkey, privkey=privkey, signed_mat=signed_mat)

    signer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])

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


@refbp.route('/student/view', methods=('GET', 'POST'))
@admin_required
def student_view_all():
    """
    List all students currently registered.
    """
    students = User.query.all()
    return render_template('student_view_all.html', students=students)

@refbp.route('/student/view/<int:user_id>')
@admin_required
def student_view_single(user_id):
    """
    Shows details for the user that belongs to the given user_id.
    """
    user =  User.query.filter(User.id == user_id).first()
    if not user:
        flash.error(f'Unknown exercise ID {user_id}')
        return render_template('400.html'), 400

    return render_template('student_view_single.html', user=user)
