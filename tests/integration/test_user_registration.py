"""
Integration Tests: User Registration

Tests user creation by calling the User model directly via remote_exec.
Uses shared pre/post condition assertions from helpers/conditions.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

import pytest

from helpers.conditions import UserConditions
from helpers.method_exec import create_user, delete_user

if TYPE_CHECKING:
    from helpers.ref_instance import REFInstance


class TestUserCreation:
    """Tests for user creation via direct method calls."""

    @pytest.mark.integration
    def test_create_student_user(
        self,
        ref_instance: "REFInstance",
        unique_mat_num: str,
        cleanup_user: Callable[[str], str],
    ):
        """
        Test creating a student user via direct method call.

        Pre-condition: User does not exist
        Action: Create user via User model
        Post-conditions:
            - User exists with correct attributes
            - User has student authorization
            - User has SSH key
            - User has password set
        """
        mat_num = cleanup_user(unique_mat_num)

        # Pre-condition
        UserConditions.pre_user_not_exists(ref_instance, mat_num)

        # Action
        result = create_user(
            ref_instance,
            mat_num=mat_num,
            first_name="Integration",
            surname="TestUser",
            password="TestPassword123!",
            generate_ssh_key=True,
        )

        # Verify return value
        assert result["mat_num"] == mat_num
        assert result["id"] is not None
        assert result["private_key"] is not None

        # Post-conditions (shared assertions)
        user_data = UserConditions.post_user_created(
            ref_instance, mat_num, "Integration", "TestUser"
        )
        UserConditions.post_user_is_student(ref_instance, mat_num)
        UserConditions.post_user_has_ssh_key(ref_instance, mat_num)
        UserConditions.post_user_has_password(ref_instance, mat_num)

        # Additional verification
        assert user_data["is_student"] is True
        assert user_data["is_admin"] is False
        assert user_data["registered_date"] is not None

    @pytest.mark.integration
    def test_delete_user(
        self,
        ref_instance: "REFInstance",
        unique_mat_num: str,
    ):
        """
        Test deleting a user.

        Pre-condition: User exists
        Action: Delete user
        Post-condition: User no longer exists
        """
        mat_num = unique_mat_num

        # Setup: Create user first
        create_user(
            ref_instance,
            mat_num=mat_num,
            first_name="ToDelete",
            surname="User",
            password="TestPassword123!",
            generate_ssh_key=True,
        )

        # Verify user exists
        UserConditions.post_user_created(ref_instance, mat_num, "ToDelete", "User")

        # Action: Delete user
        result = delete_user(ref_instance, mat_num)
        assert result is True

        # Post-condition: User should no longer exist
        UserConditions.pre_user_not_exists(ref_instance, mat_num)

    @pytest.mark.integration
    def test_delete_nonexistent_user(
        self,
        ref_instance: "REFInstance",
        unique_mat_num: str,
    ):
        """
        Test that deleting a nonexistent user returns False.
        """
        mat_num = unique_mat_num

        # Ensure user doesn't exist
        UserConditions.pre_user_not_exists(ref_instance, mat_num)

        # Action: Try to delete nonexistent user
        result = delete_user(ref_instance, mat_num)
        assert result is False


class TestUserValidation:
    """Tests for user validation and constraints."""

    @pytest.mark.integration
    def test_create_duplicate_user_fails(
        self,
        ref_instance: "REFInstance",
        unique_mat_num: str,
        cleanup_user: Callable[[str], str],
    ):
        """
        Test that creating a user with duplicate mat_num fails.
        """
        mat_num = cleanup_user(unique_mat_num)

        # Create first user
        create_user(
            ref_instance,
            mat_num=mat_num,
            first_name="First",
            surname="User",
            password="TestPassword123!",
        )

        # Try to create second user with same mat_num
        with pytest.raises(Exception):
            create_user(
                ref_instance,
                mat_num=mat_num,
                first_name="Second",
                surname="User",
                password="TestPassword123!",
            )

    @pytest.mark.integration
    def test_user_password_is_hashed(
        self,
        ref_instance: "REFInstance",
        unique_mat_num: str,
        cleanup_user: Callable[[str], str],
    ):
        """
        Test that user passwords are properly hashed (not stored in plain text).
        """
        mat_num = cleanup_user(unique_mat_num)
        password = "TestPassword123!"

        # Create user
        create_user(
            ref_instance,
            mat_num=mat_num,
            first_name="Password",
            surname="Test",
            password=password,
        )

        # Verify password is hashed
        def _check_password_hashed() -> bool:
            from ref.model.user import User

            user = User.query.filter_by(mat_num=mat_num).first()
            if user is None:
                return False
            # Password should be hashed, not plain text
            return user.password != password and len(user.password) > 20

        result = ref_instance.remote_exec(_check_password_hashed)
        assert result is True, "Password should be hashed"

    @pytest.mark.integration
    def test_user_can_verify_password(
        self,
        ref_instance: "REFInstance",
        unique_mat_num: str,
        cleanup_user: Callable[[str], str],
    ):
        """
        Test that we can verify a user's password.
        """
        mat_num = cleanup_user(unique_mat_num)
        password = "TestPassword123!"

        # Create user
        create_user(
            ref_instance,
            mat_num=mat_num,
            first_name="Verify",
            surname="Test",
            password=password,
        )

        # Verify password check works
        def _check_password() -> dict[str, bool]:
            from ref.model.user import User

            user = User.query.filter_by(mat_num=mat_num).first()
            if user is None:
                return {"found": False, "correct": False, "wrong": False}
            return {
                "found": True,
                "correct": user.check_password(password),
                "wrong": user.check_password("WrongPassword"),
            }

        result = ref_instance.remote_exec(_check_password)
        assert result["found"] is True
        assert result["correct"] is True, "Correct password should verify"
        assert result["wrong"] is False, "Wrong password should not verify"
