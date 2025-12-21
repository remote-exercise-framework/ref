import datetime
import uuid
from typing import TYPE_CHECKING, List, Optional

from flask_bcrypt import check_password_hash, generate_password_hash
from flask_login import UserMixin
from sqlalchemy import ForeignKey, LargeBinary, PickleType, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ref import db
from ref.model.enums import CourseOfStudies, UserAuthorizationGroups

from .util import CommonDbOpsMixin, ModelToStringMixin

if TYPE_CHECKING:
    from .instance import Instance


class UserGroup(CommonDbOpsMixin, ModelToStringMixin, db.Model):
    __to_str_fields__ = ["id", "name"]
    __tablename__ = "user_group"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)

    users: Mapped[List["User"]] = relationship(
        "User", back_populates="group", lazy=True, passive_deletes="all"
    )


class User(CommonDbOpsMixin, ModelToStringMixin, UserMixin, db.Model):
    __to_str_fields__ = ["id", "is_admin", "first_name", "surname", "nickname"]
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(primary_key=True)
    login_token: Mapped[Optional[str]] = mapped_column(Text)

    first_name: Mapped[str] = mapped_column(Text)
    surname: Mapped[str] = mapped_column(Text)
    nickname: Mapped[Optional[str]] = mapped_column(Text, unique=True)

    # backref is group
    group_id: Mapped[Optional[int]] = mapped_column(ForeignKey("user_group.id"))
    group: Mapped[Optional["UserGroup"]] = relationship(
        "UserGroup", foreign_keys=[group_id], back_populates="users"
    )

    password: Mapped[bytes] = mapped_column(LargeBinary)
    mat_num: Mapped[str] = mapped_column(Text, unique=True)

    registered_date: Mapped[datetime.datetime]
    pub_key: Mapped[str] = mapped_column(Text)
    priv_key: Mapped[Optional[str]] = mapped_column(Text)
    course_of_studies: Mapped[Optional[CourseOfStudies]]

    auth_groups: Mapped[List[UserAuthorizationGroups]] = mapped_column(PickleType)

    # Exercise instances associated to the student
    exercise_instances: Mapped[List["Instance"]] = relationship(
        "Instance", back_populates="user", lazy="joined", passive_deletes="all"
    )

    def __init__(self):
        self.login_token = str(uuid.uuid4())

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
        return f"{self.id}:{self.login_token}"

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.surname}"

    @property
    def instances(self) -> List["Instance"]:
        return [i for i in self.exercise_instances if not i.submission]

    @property
    def submissions(self) -> List["Instance"]:
        return [i for i in self.exercise_instances if i.submission]
