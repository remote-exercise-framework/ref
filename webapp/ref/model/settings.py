import datetime
import uuid
from ref.model.enums import CourseOfStudies
from flask_bcrypt import generate_password_hash, check_password_hash
from ref import db
from flask_login import UserMixin
from .util import CommonDbOpsMixin, ModelToStringMixin
from sqlalchemy.orm import backref

class SystemSetting(CommonDbOpsMixin, ModelToStringMixin, db.Model):
    __to_str_fields__ = ['id', 'name']
    __tablename__ = 'system_setting'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text(), nullable=False, unique=True)
    value = db.Column(PickleType(), nullable=True)

    @staticmethod
    def user_groups_enabled() -> bool:
        pass

    def user_groups_size_limit() -> int:
        pass