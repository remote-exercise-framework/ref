import datetime
import uuid

from sqlalchemy.orm import backref

from flask_bcrypt import check_password_hash, generate_password_hash
from flask_login import UserMixin
from ref import db
from ref.model.enums import CourseOfStudies, UserAuthorizationGroups

from .util import CommonDbOpsMixin, ModelToStringMixin


class UserGroup(CommonDbOpsMixin, ModelToStringMixin, db.Model):
    __to_str_fields__ = ['id', 'name']
    __tablename__ = 'user_group'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text(), nullable=False, unique=True)

    users = db.relationship('User', back_populates='group', lazy=True,  passive_deletes='all')

class User(CommonDbOpsMixin, ModelToStringMixin, UserMixin, db.Model):
    __to_str_fields__ = ['id', 'is_admin', 'first_name', 'surname', 'nickname']

    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    login_token = db.Column(db.Text(), nullable=True)

    first_name = db.Column(db.Text(), nullable=False)
    surname = db.Column(db.Text(), nullable=False)
    nickname = db.Column(db.Text(), nullable=False, unique=True)

    #backref is group
    group_id = db.Column(db.Integer, db.ForeignKey('user_group.id'), nullable=True)
    group: 'UserGroup' = db.relationship('UserGroup', foreign_keys=[group_id], back_populates="users")

    password = db.Column(db.LargeBinary(), nullable=False)
    mat_num = db.Column(db.Text(), nullable=False, unique=True)

    registered_date = db.Column(db.DateTime(), nullable=False)
    pub_key = db.Column(db.Text(), nullable=False)
    pub_key_ssh = db.Column(db.Text(), nullable=False)
    priv_key = db.Column(db.Text(), nullable=True)
    course_of_studies = db.Column(db.Enum(CourseOfStudies), nullable=True)

    auth_groups = db.Column(db.PickleType(), nullable=False)

    #Exercise instances associated to the student
    exercise_instances = db.relationship('Instance', back_populates='user', lazy=True,  passive_deletes='all')

    @property
    def is_admin(self):
        return UserAuthorizationGroups.ADMIN in self.auth_groups

    @property
    def is_grading_assistant(self):
        return UserAuthorizationGroups.GRADING_ASSISTANT in self.auth_groups

    @property
    def is_student(self):
        return UserAuthorizationGroups.STUDENT in self.auth_groups

    def is_auth_group_member(self, group: UserAuthorizationGroups):
        return group in self.auth_groups

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

    @property
    def instances(self):
        return [i for i in self.exercise_instances if not i.submission]

    @property
    def submissions(self):
        return [i for i in self.exercise_instances if i.submission]
