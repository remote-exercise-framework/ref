"""User management operations."""

import datetime

from flask import current_app

from ref.model.enums import UserAuthorizationGroups
from ref.model.user import User, UserGroup

from .instance import InstanceManager


class UserManager:
    """
    Provides factory methods and lifecycle operations for User objects.
    """

    @staticmethod
    def create_student(
        mat_num: str,
        first_name: str,
        surname: str,
        password: str,
        pub_key: str | None = None,
        priv_key: str | None = None,
        group: UserGroup | None = None,
    ) -> User:
        """
        Create a new student user.

        The user is NOT added to the session - the caller must add and commit.

        Args:
            mat_num: Unique matriculation number
            first_name: User's first name
            surname: User's surname
            password: Plain-text password (will be hashed)
            pub_key: Optional SSH public key
            priv_key: Optional SSH private key
            group: Optional UserGroup to attach the new user to

        Returns:
            The created User object (not yet in session)
        """
        user = User()
        user.mat_num = mat_num
        user.first_name = first_name
        user.surname = surname
        user.set_password(password)
        user.pub_key = pub_key
        user.priv_key = priv_key
        user.registered_date = datetime.datetime.utcnow()
        user.auth_groups = [UserAuthorizationGroups.STUDENT]
        if group is not None:
            user.group = group
        return user

    @staticmethod
    def delete_with_instances(user: User) -> None:
        """
        Delete a user and all their associated instances.

        This removes all instances via InstanceManager.remove(), then deletes
        the user. Does NOT commit - caller must commit.

        Args:
            user: The user to delete
        """
        for instance in list(user.exercise_instances):
            mgr = InstanceManager(instance)
            mgr.remove()
        current_app.db.session.delete(user)
