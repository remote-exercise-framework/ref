import datetime
import uuid
from ref.model.enums import CourseOfStudies
from flask_bcrypt import generate_password_hash, check_password_hash
from ref import db
from flask_login import UserMixin
from .util import CommonDbOpsMixin, ModelToStringMixin
from sqlalchemy.orm import backref
from enum import Enum
from flask import current_app

default_ssh_welcome_msg = """
  ____  ____  ____                 _ __
 / __ \/ __/ / __/__ ______ ______(_) /___ __
/ /_/ /\ \  _\ \/ -_) __/ // / __/ / __/ // /
\____/___/ /___/\__/\__/\_,_/_/ /_/\__/\_, /
                                      /___/"""

class SystemSettingKeys:
    GROUPS_ENABLED = 'GROUPS_ENABLED'
    GROUP_SIZE = 'GROUP_SIZE'
    SSH_WELCOME_MSG = 'SSH_WELCOME_MSG'

class SystemSetting(CommonDbOpsMixin, ModelToStringMixin, db.Model):

    __to_str_fields__ = ['id', 'name']
    __tablename__ = 'system_setting'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text(), nullable=False, unique=True)
    value = db.Column(db.PickleType(), nullable=True)

    @staticmethod
    def get_setting(name: SystemSettingKeys):
        res = SystemSetting.query.filter(SystemSetting.name == name).one_or_none()
        return res

    @staticmethod
    def get_user_groups_enabled() -> bool:
        is_enabled = SystemSetting.get_setting(SystemSettingKeys.GROUPS_ENABLED)
        return is_enabled and is_enabled.value is True

    @staticmethod
    def set_user_groups_enabled(enabled: bool):
        assert isinstance(enabled, bool)
        is_enabled = SystemSetting.get_setting(SystemSettingKeys.GROUPS_ENABLED)
        if is_enabled is None:
            is_enabled = SystemSetting()
            is_enabled.name = SystemSettingKeys.GROUPS_ENABLED
        is_enabled.value = enabled
        current_app.db.session.add(is_enabled)
        current_app.db.session.commit()

    @staticmethod
    def get_user_groups_size_limit() -> int:
        group_size = SystemSetting.get_setting(SystemSettingKeys.GROUP_SIZE)
        if group_size is None:
            return None
        else:
            return group_size.value

    @staticmethod
    def set_user_groups_size_limit(max_size: int):
        assert isinstance(max_size, int)
        group_size = SystemSetting.get_setting(SystemSettingKeys.GROUP_SIZE)
        if group_size is None:
            group_size = SystemSetting()
            group_size.name = SystemSettingKeys.GROUP_SIZE
        group_size.value = max_size
        current_app.db.session.add(group_size)
        current_app.db.session.commit()

    @staticmethod
    def get_ssh_welcome_header() -> str:
        msg = SystemSetting.get_setting(SystemSettingKeys.SSH_WELCOME_MSG)
        if msg is None:
            return default_ssh_welcome_msg
        else:
            return msg.value

    @staticmethod
    def set_ssh_welcome_header(msg: str):
        assert isinstance(msg, str)
        setting_msg = SystemSetting.get_setting(SystemSettingKeys.SSH_WELCOME_MSG)
        if setting_msg is None:
            setting_msg = SystemSetting()
            setting_msg.name = SystemSettingKeys.SSH_WELCOME_MSG
        setting_msg.value = msg
        current_app.db.session.add(setting_msg)
        current_app.db.session.commit()