"""
Integration tests for the admin user-edit view.

Covers `/admin/student/edit/<id>`, and in particular the authorization
group assignment - the one place in the app that changes a user's role,
and the reason `UserManager.set_auth_groups` exists.
"""

from typing import Any, Dict, List

import pytest

from helpers.method_exec import create_user, user_auth_groups, user_login_token
from helpers.web_client import REFWebClient

ADMIN_MAT_NUM = "0"
STUDENT = "Student"
GRADING_ASSISTANT = "Grading Assistant"
ADMIN = "Admin"


def _edit_path(user_id: int) -> str:
    return f"/admin/student/edit/{user_id}"


def _form_data(user: Dict[str, Any], auth_groups: List[str]) -> Dict[str, Any]:
    """
    A complete edit form.

    Every field is sent on every POST: the view writes what the form
    carries, so omitting a field blanks it rather than leaving it alone.
    `pubkey` is DataRequired, and the password fields must stay empty or
    the view treats the submission as a password change.
    """
    return {
        "id": str(user["id"]),
        "mat_num": user["mat_num"],
        "firstname": user["first_name"],
        "surname": user["surname"],
        "auth_group": auth_groups,
        "group": "",
        "pubkey": user["pub_key"],
        "password": "",
        "password_rep": "",
        "submit": "Update",
    }


@pytest.fixture
def editable_user(ref_instance: Any) -> Dict[str, Any]:
    """A plain student to be edited, with the fields the form needs."""
    import uuid

    mat_num = str(uuid.uuid4().int)[:8]
    created = create_user(
        ref_instance,
        mat_num=mat_num,
        first_name="Edit",
        surname="Target",
        password="EditTarget123!",
    )
    created["first_name"] = "Edit"
    created["surname"] = "Target"
    return created


@pytest.fixture
def admin_web_client(web_client_factory: Any, admin_password: str) -> REFWebClient:
    client = web_client_factory()
    assert client.login(ADMIN_MAT_NUM, admin_password), "admin login failed"
    return client


class TestAuthGroupEditing:
    def test_a_new_role_is_stored(
        self,
        ref_instance: Any,
        admin_web_client: REFWebClient,
        editable_user: Dict[str, Any],
    ) -> None:
        """Promoting a student to grading assistant persists."""
        user_id = editable_user["id"]
        assert user_auth_groups(ref_instance, user_id) == [STUDENT]

        response = admin_web_client.client.post(
            _edit_path(user_id),
            data=_form_data(editable_user, [STUDENT, GRADING_ASSISTANT]),
        )

        assert response.status_code == 200, response.status_code
        assert user_auth_groups(ref_instance, user_id) == [
            GRADING_ASSISTANT,
            STUDENT,
        ]

    def test_a_role_change_invalidates_the_session(
        self,
        ref_instance: Any,
        admin_web_client: REFWebClient,
        editable_user: Dict[str, Any],
    ) -> None:
        """
        The user is logged out when their roles change.

        Otherwise a demoted user keeps whatever the old role let them do
        until their cookie expires.
        """
        user_id = editable_user["id"]
        before = user_login_token(ref_instance, user_id)
        assert before, "user has no session token to invalidate"

        admin_web_client.client.post(
            _edit_path(user_id),
            data=_form_data(editable_user, [STUDENT, ADMIN]),
        )

        assert user_login_token(ref_instance, user_id) != before

    def test_resubmitting_the_same_roles_keeps_the_session(
        self,
        ref_instance: Any,
        admin_web_client: REFWebClient,
        editable_user: Dict[str, Any],
    ) -> None:
        """
        An edit that does not change the roles must not log the user out.

        This is what `set_auth_groups` reports back: saving the form after
        correcting a typo in a surname should not kick the user out of
        their session.
        """
        user_id = editable_user["id"]
        before = user_login_token(ref_instance, user_id)

        editable_user["surname"] = "Target-Renamed"
        response = admin_web_client.client.post(
            _edit_path(user_id),
            data=_form_data(editable_user, [STUDENT]),
        )

        assert response.status_code == 200
        assert user_auth_groups(ref_instance, user_id) == [STUDENT]
        assert user_login_token(ref_instance, user_id) == before

    def test_a_non_admin_cannot_edit_a_user(
        self,
        ref_instance: Any,
        web_client: REFWebClient,
        editable_user: Dict[str, Any],
    ) -> None:
        """An anonymous client cannot promote anyone."""
        user_id = editable_user["id"]

        web_client.client.post(
            _edit_path(user_id),
            data=_form_data(editable_user, [STUDENT, ADMIN]),
        )

        assert user_auth_groups(ref_instance, user_id) == [STUDENT]
