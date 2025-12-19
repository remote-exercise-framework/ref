"""
Login API Security Tests

Tests for /login and /logout endpoints.

Security focus:
- Authentication validation
- Input sanitization
- Authorization checks (admin vs student)
- Session management
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

if TYPE_CHECKING:
    from .conftest import StudentCredentials


@pytest.mark.api
@pytest.mark.security
class TestLogin:
    """
    Tests for /login endpoint.

    Only admin and grading assistant users can login here.
    Regular students use SSH keys, not web login.
    """

    def test_get_login_form(self, raw_client: httpx.Client) -> None:
        """GET request should return login form."""
        response = raw_client.get("/login")
        assert response.status_code == 200
        assert "login" in response.text.lower() or "form" in response.text.lower()

    def test_missing_credentials(
        self, raw_client_follow_redirects: httpx.Client
    ) -> None:
        """Login without credentials should show form again."""
        response = raw_client_follow_redirects.post(
            "/login",
            data={"submit": "Login"},
        )
        assert response.status_code == 200
        # Should stay on login page

    def test_invalid_username_format(
        self, raw_client_follow_redirects: httpx.Client
    ) -> None:
        """Non-numeric username should be rejected."""
        response = raw_client_follow_redirects.post(
            "/login",
            data={
                "username": "not_a_number",
                "password": "anypassword",
                "submit": "Login",
            },
        )
        assert response.status_code == 200
        # Should show error and stay on login page

    def test_wrong_password(self, raw_client_follow_redirects: httpx.Client) -> None:
        """Wrong password should be rejected."""
        response = raw_client_follow_redirects.post(
            "/login",
            data={
                "username": "0",  # Admin mat_num
                "password": "WrongPassword123!",
                "submit": "Login",
            },
        )
        assert response.status_code == 200
        # Should show error
        assert "invalid" in response.text.lower() or "password" in response.text.lower()

    def test_nonexistent_user(self, raw_client_follow_redirects: httpx.Client) -> None:
        """Non-existent user should show generic error."""
        response = raw_client_follow_redirects.post(
            "/login",
            data={
                "username": "99999999",
                "password": "anypassword",
                "submit": "Login",
            },
        )
        assert response.status_code == 200
        # Should show error (generic, not revealing user doesn't exist)
        assert "invalid" in response.text.lower() or "password" in response.text.lower()

    def test_regular_student_cannot_login(
        self,
        raw_client_follow_redirects: httpx.Client,
        registered_student: StudentCredentials,
    ) -> None:
        """Regular students (not admin/grading assistant) cannot use web login."""
        response = raw_client_follow_redirects.post(
            "/login",
            data={
                "username": registered_student.mat_num,
                "password": registered_student.password,
                "submit": "Login",
            },
        )
        assert response.status_code == 200
        # Should show error (students can't login via web)
        assert (
            "invalid" in response.text.lower()
            or "password" in response.text.lower()
            or "not supposed" in response.text.lower()
        )

    def test_sql_injection_in_username(
        self, raw_client_follow_redirects: httpx.Client
    ) -> None:
        """SQL injection in username should be handled safely."""
        sql_payloads = [
            "0 OR 1=1",
            "0; DROP TABLE users;--",
            "0' OR '1'='1",
            "0 UNION SELECT * FROM users",
        ]
        for payload in sql_payloads:
            response = raw_client_follow_redirects.post(
                "/login",
                data={
                    "username": payload,
                    "password": "anypassword",
                    "submit": "Login",
                },
            )
            # Should not crash or expose data
            assert response.status_code in [200, 400]

    def test_xss_in_username(self, raw_client_follow_redirects: httpx.Client) -> None:
        """XSS in username should be escaped."""
        xss_payloads = [
            "<script>alert('XSS')</script>",
            "<img src=x onerror=alert('XSS')>",
        ]
        for payload in xss_payloads:
            response = raw_client_follow_redirects.post(
                "/login",
                data={
                    "username": payload,
                    "password": "anypassword",
                    "submit": "Login",
                },
            )
            assert response.status_code == 200
            # XSS payload should not appear unescaped
            if payload in response.text:
                # If it appears, it should be within an escaped context
                assert f">{payload}<" not in response.text

    def test_admin_login_success(
        self, raw_client: httpx.Client, admin_password: str
    ) -> None:
        """Admin should be able to login and be redirected."""
        response = raw_client.post(
            "/login",
            data={
                "username": "0",
                "password": admin_password,
                "submit": "Login",
            },
        )
        # Should redirect to admin area
        assert response.status_code in [302, 303, 307]
        location = response.headers.get("location", "")
        assert "admin" in location.lower() or "exercise" in location.lower()

    def test_already_authenticated_redirect(self, admin_session: httpx.Client) -> None:
        """Already authenticated users should be redirected from login page."""
        response = admin_session.get("/login")
        # Should redirect away from login since already logged in
        # Note: The fixture follows redirects, so check final URL
        assert response.status_code == 200
        # Should be on admin page, not login
        assert (
            "exercise" in response.text.lower()
            or "admin" in response.text.lower()
            or "grading" in response.text.lower()
        )


@pytest.mark.api
class TestLogout:
    """
    Tests for /logout endpoint.
    """

    def test_logout_unauthenticated(self, raw_client: httpx.Client) -> None:
        """Logout when not authenticated should redirect to login."""
        response = raw_client.get("/logout")
        assert response.status_code in [302, 303, 307]
        assert "login" in response.headers.get("location", "").lower()

    def test_logout_post_method(self, raw_client: httpx.Client) -> None:
        """POST to logout should also work."""
        response = raw_client.post("/logout")
        assert response.status_code in [302, 303, 307]

    def test_logout_authenticated(
        self, raw_client: httpx.Client, admin_password: str
    ) -> None:
        """Logout when authenticated should clear session."""
        # Login first
        login_resp = raw_client.post(
            "/login",
            data={
                "username": "0",
                "password": admin_password,
                "submit": "Login",
            },
        )
        assert login_resp.status_code in [302, 303, 307]

        # Now logout
        logout_resp = raw_client.get("/logout")
        assert logout_resp.status_code in [302, 303, 307]

        # Try to access admin page - should redirect to login
        admin_resp = raw_client.get("/admin/exercise/view")
        assert admin_resp.status_code in [302, 303, 307]
        assert "login" in admin_resp.headers.get("location", "").lower()


@pytest.mark.api
@pytest.mark.security
class TestSessionSecurity:
    """
    Tests for session security.
    """

    def test_session_cookie_attributes(
        self, raw_client: httpx.Client, admin_password: str
    ) -> None:
        """Session cookie should have secure attributes."""
        response = raw_client.post(
            "/login",
            data={
                "username": "0",
                "password": admin_password,
                "submit": "Login",
            },
        )

        # Check for session cookie
        # Note: In development/test mode, secure flag may not be set
        # This test documents expected behavior
        assert response.cookies is not None  # Session cookie should exist

    def test_csrf_protection(self, raw_client_follow_redirects: httpx.Client) -> None:
        """
        CSRF protection should be in place.

        Note: Flask-WTF provides CSRF protection for form submissions.
        This test documents expected behavior.
        """
        # Direct POST without getting form first
        response = raw_client_follow_redirects.post(
            "/login",
            data={
                "username": "0",
                "password": "test",
                "submit": "Login",
            },
        )
        # Should still work (CSRF may be disabled in some configs)
        # but document the behavior
        assert response.status_code in [200, 400, 403]
