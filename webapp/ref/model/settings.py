import secrets
import string
from typing import Any, Optional

from flask import current_app
from sqlalchemy import PickleType, Text
from sqlalchemy.orm import Mapped, mapped_column

from ref import db

from .util import CommonDbOpsMixin, ModelToStringMixin


def generate_installation_id() -> str:
    """Generate a random 6-character alphanumeric ID for this REF installation."""
    chars = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(6))


class SystemSetting(CommonDbOpsMixin, ModelToStringMixin, db.Model):
    __to_str_fields__ = ["id", "name"]
    __tablename__ = "system_setting"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    value: Mapped[Optional[Any]] = mapped_column(PickleType)

    @staticmethod
    def get_setting(name):
        res = SystemSetting.query.filter(SystemSetting.name == name).one_or_none()
        return res


class Setting:
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
        assert isinstance(val, self.type_), (
            f"isinstance({type(val)}, {self.type_}) failed"
        )
        entry = SystemSetting.query.filter(SystemSetting.name == self.key).one_or_none()
        if entry is None:
            entry = SystemSetting()
            entry.name = self.key
        entry.value = val
        current_app.db.session.add(entry)

    value = property(_get_value, _set_value)


default_ssh_welcome_msg = r"""
 ____  ____  ____                 _ __
/ __ \/ __/ / __/__ ______ ______(_) /___ __
/ /_/ /\ \  _\ \/ -_) __/ // / __/ / __/ // /
\____/___/ /___/\__/\__/\_,_/_/ /_/\__/\_, /
                                    /___/"""


class SystemSettingsManager:
    # Unique ID for this REF installation, used to distinguish Docker resources
    INSTALLATION_ID = Setting("INSTALLATION_ID", str, None)

    REGESTRATION_ENABLED = Setting("REGESTRATION_ENABLED", bool, True)
    MAINTENANCE_ENABLED = Setting("MAINTENANCE_ENABLED", bool, False)
    SUBMISSION_DISABLED = Setting("SUBMISSION_DISABLED", bool, False)
    SUBMISSION_ALLOW_DELETE = Setting("SUBMISSION_ALLOW_DELETE", bool, False)
    TELEGRAM_LOGGER_TOKEN = Setting("TELEGRAM_LOGGER_TOKEN", str, "")
    TELEGRAM_LOGGER_CHANNEL_ID = Setting("TELEGRAM_LOGGER_CHANNEL_ID", str, "")

    # Whether to hide submissins that belong to an ongoing exercise
    # for the grading assistant.
    SUBMISSION_HIDE_ONGOING = Setting("SUBMISSION_HIDE_ONGOING", bool, False)

    COURSE_NAME = Setting("COURSE_NAME", str, "OS-Security")
    COURSE_OF_STUDY = Setting("COURSE_OF_STUDY", list, ["A"])

    GROUPS_ENABLED = Setting("GROUPS_ENABLED", bool, False)
    GROUP_SIZE = Setting("GROUP_SIZE", int, 1)

    SSH_HOSTNAME = Setting("SSH_HOSTNAME", str, "127.0.0.1")
    SSH_PORT = Setting("SSH_PORT", str, "22")

    ALLOW_TCP_PORT_FORWARDING = Setting("ALLOW_TCP_PORT_FORWARDING", bool, False)
    ALLOW_ROOT_LOGINS_FOR_ADMINS = Setting("ALLOW_ROOT_LOGINS_FOR_ADMINS", bool, False)
    INSTANCE_SSH_INTROSPECTION = Setting("INSTANCE_SSH_INTROSPECTION", bool, True)
    INSTANCE_NON_DEFAULT_PROVISIONING = Setting(
        "INSTANCE_NON_DEFAULT_PROVISIONING", bool, False
    )

    SSH_WELCOME_MSG = Setting("SSH_WELCOME_MSG", str, default_ssh_welcome_msg)
    SSH_MESSAGE_OF_THE_DAY = Setting("SSH_MESSAGE_OF_THE_DAY", str, None)

    TIMEZONE = Setting("TIMEZONE", str, "Europe/Berlin")

    # Public scoreboard toggle, active visual view, and ranking strategy.
    # See ref/core/scoring.py for the set of valid ids for each.
    SCOREBOARD_ENABLED = Setting("SCOREBOARD_ENABLED", bool, False)
    SCOREBOARD_VIEW = Setting("SCOREBOARD_VIEW", str, "default")
    SCOREBOARD_RANKING_MODE = Setting(
        "SCOREBOARD_RANKING_MODE", str, "f1_time_weighted"
    )

    # Which page students land on when visiting "/". One of
    # {"registration", "scoreboard"}.
    LANDING_PAGE = Setting("LANDING_PAGE", str, "registration")
