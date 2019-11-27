import datetime
import uuid
from ref.model.enums import CourseOfStudies
from flask_bcrypt import generate_password_hash, check_password_hash
from ref import db
from flask_login import UserMixin
from .util import CommonDbOpsMixin, ModelToStringMixin

class User(CommonDbOpsMixin, ModelToStringMixin, UserMixin, db.Model):
    __to_str_fields__ = ['id', 'is_admin', 'first_name', 'surname']

    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    login_token = db.Column(db.Text(), nullable=True)

    first_name = db.Column(db.Text(), nullable=False)
    surname = db.Column(db.Text(), nullable=False)
    password = db.Column(db.Binary(), nullable=False)
    mat_num = db.Column(db.BigInteger, nullable=False, unique=True)
    registered_date = db.Column(db.DateTime(), nullable=False)
    pub_key = db.Column(db.Text(), nullable=False)
    pub_key_ssh = db.Column(db.Text(), nullable=False)
    priv_key = db.Column(db.Text(), nullable=False)
    course_of_studies = db.Column(db.Enum(CourseOfStudies), nullable=True)

    is_admin = db.Column(db.Boolean(), nullable=False)


    #Exercise instances associated to the student
    exercise_instances = db.relationship('Instance', backref='user', lazy=True)

    def set_password(self, password):
        """
        sets the password
        """
        self.password = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password, password)

    def invalidate_session(self):
        """
        Change the login token, thus all current sessions are invalidated.
        """
        self.login_token = str(uuid.uuid4())

    def get_id(self):
        """
        ID that is signed and handedt to the user in case of a
        successfull login.
        """
        return  f'{self.id}:{self.login_token}'

    @property
    def full_name(self):
        return f'{self.first_name} {self.surname}'
