import datetime
import uuid
from enum import Enum

from flask import current_app
from functools import lru_cache
from sqlalchemy.orm import backref

from flask_bcrypt import check_password_hash, generate_password_hash
from flask_login import UserMixin
from ref import db
from ref.model.enums import CourseOfStudies

from .util import CommonDbOpsMixin, ModelToStringMixin

class SystemSetting(CommonDbOpsMixin, ModelToStringMixin, db.Model):

    __to_str_fields__ = ['id', 'name']
    __tablename__ = 'system_setting'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text(), nullable=False, unique=True)
    value = db.Column(db.PickleType(), nullable=True)

    @staticmethod
    def get_setting(name):
        res = SystemSetting.query.filter(SystemSetting.name == name).one_or_none()
        return res

class Setting():

    def __init__(self, key, type_, default_value):
        self.key = key
        self.type_ = type_
        self.default_value = default_value

    def _get_value(self):
        entry = SystemSetting.query.filter(SystemSetting.name == self.key).one_or_none()
        if entry:
            return entry.value
        else:
            return self.default_value

    def _set_value(self, val):
        assert isinstance(val, self.type_), f'isinstance({type(val)}, {self.type_}) failed'
        entry = SystemSetting.query.filter(SystemSetting.name == self.key).one_or_none()
        if entry is None:
            entry = SystemSetting()
            entry.name = self.key
        entry.value = val
        current_app.db.session.add(entry)

    value = property(_get_value, _set_value)


default_ssh_welcome_msg = """
 ____  ____  ____                 _ __
/ __ \/ __/ / __/__ ______ ______(_) /___ __
/ /_/ /\ \  _\ \/ -_) __/ // / __/ / __/ // /
\____/___/ /___/\__/\__/\_,_/_/ /_/\__/\_, /
                                    /___/"""

class SystemSettingsManager():
    REGESTRATION_ENABLED = Setting('REGESTRATION_ENABLED', bool, True)
    MAINTENANCE_ENABLED = Setting('MAINTENANCE_ENABLED', bool, False)
    SUBMISSION_DISABLED = Setting('SUBMISSION_DISABLED', bool, False)

    COURSE_NAME = Setting('COURSE_NAME', str, 'OS-Security')
    COURSE_OF_STUDY = Setting('COURSE_OF_STUDY', list, ['A'])

    SSH_HOSTNAME = Setting('SSH_HOSTNAME', str, "127.0.0.1")
    SSH_PORT = Setting('SSH_PORT', str, "22")

    SUBMISSION_ALLOW_DELETE = Setting('SUBMISSION_ALLOW_DELETE', bool, False)

    INSTANCE_SSH_INTROSPECTION = Setting('INSTANCE_SSH_INTROSPECTION', bool, True)
    INSTANCE_NON_DEFAULT_PROVISIONING = Setting('INSTANCE_NON_DEFAULT_PROVISIONING', bool, False)

    GROUPS_ENABLED = Setting('GROUPS_ENABLED', bool, False)
    GROUP_SIZE = Setting('GROUP_SIZE', int, 2)
    SSH_WELCOME_MSG = Setting('SSH_WELCOME_MSG', str, default_ssh_welcome_msg)
    SSH_MESSAGE_OF_THE_DAY = Setting('SSH_MESSAGE_OF_THE_DAY', str, None)

    TIMEZONE = Setting('TIMEZONE', str, 'Europe/Berlin')
