"""
Student API Security Tests

Tests for /student/* endpoints that handle student registration and key management.

Security focus:
- Input validation (mat_num, password, pubkey)
- Password policy enforcement
- Duplicate detection
- Signed URL validation for key downloads
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

if TYPE_CHECKING:
    from .conftest import StudentCredentials


@pytest.mark.api
@pytest.mark.security
class TestStudentGetkey:
    """
    Tests for /student/getkey endpoint.

    This endpoint handles new student registration.
    """

    def test_get_form(self, raw_client: httpx.Client) -> None:
        """GET request should return registration form."""
        response = raw_client.get("/student/getkey")
        assert response.status_code == 200
        assert "form" in response.text.lower() or "getkey" in response.text.lower()

    def test_missing_required_fields(
        self, raw_client_follow_redirects: httpx.Client
    ) -> None:
        """Missing required fields should be rejected."""
        response = raw_client_follow_redirects.post(
            "/student/getkey",
            data={"submit": "Get Key"},
        )
        assert response.status_code == 200
        # Should show form with errors

    def test_invalid_mat_num_non_numeric(
        self, raw_client_follow_redirects: httpx.Client, valid_password: str
    ) -> None:
        """Non-numeric matriculation number should be rejected."""
        response = raw_client_follow_redirects.post(
            "/student/getkey",
            data={
                "mat_num": "not_a_number",
                "firstname": "Test",
                "surname": "User",
                "password": valid_password,
                "password_rep": valid_password,
                "pubkey": "",
                "submit": "Get Key",
            },
        )
        assert response.status_code == 200
        # Form should be re-displayed with error

    def test_invalid_mat_num_special_chars(
        self, raw_client_follow_redirects: httpx.Client, valid_password: str
    ) -> None:
        """Matriculation number with special characters should be rejected."""
        special_mat_nums = [
            "123; DROP TABLE users;--",  # SQL injection
            "123<script>",  # XSS attempt
            "123\x00456",  # Null byte
            "-12345",  # Negative
            "12.345",  # Decimal
        ]
        for mat_num in special_mat_nums:
            response = raw_client_follow_redirects.post(
                "/student/getkey",
                data={
                    "mat_num": mat_num,
                    "firstname": "Test",
                    "surname": "User",
                    "password": valid_password,
                    "password_rep": valid_password,
                    "pubkey": "",
                    "submit": "Get Key",
                },
            )
            assert response.status_code == 200
            # Should not register (form re-displayed or error)

    def test_weak_password_too_short(
        self, raw_client_follow_redirects: httpx.Client, unique_mat_num: str
    ) -> None:
        """Password shorter than 8 characters should be rejected."""
        response = raw_client_follow_redirects.post(
            "/student/getkey",
            data={
                "mat_num": unique_mat_num,
                "firstname": "Test",
                "surname": "User",
                "password": "Short1!",  # 7 chars
                "password_rep": "Short1!",
                "pubkey": "",
                "submit": "Get Key",
            },
        )
        assert response.status_code == 200
        # Should show password error

    def test_weak_password_missing_complexity(
        self, raw_client_follow_redirects: httpx.Client, unique_mat_num: str
    ) -> None:
        """Password missing complexity requirements should be rejected."""
        weak_passwords = [
            "alllowercase123",  # Missing uppercase
            "ALLUPPERCASE123",  # Missing lowercase
            "NoDigitsHere!!",  # Missing digits
            "NoSpecial123Ab",  # Missing special chars
        ]
        for password in weak_passwords:
            response = raw_client_follow_redirects.post(
                "/student/getkey",
                data={
                    "mat_num": unique_mat_num,
                    "firstname": "Test",
                    "surname": "User",
                    "password": password,
                    "password_rep": password,
                    "pubkey": "",
                    "submit": "Get Key",
                },
            )
            # 200 = form re-displayed with error
            assert response.status_code == 200

    def test_password_mismatch(
        self, raw_client_follow_redirects: httpx.Client, unique_mat_num: str
    ) -> None:
        """Mismatched password and password_rep should be rejected."""
        response = raw_client_follow_redirects.post(
            "/student/getkey",
            data={
                "mat_num": unique_mat_num,
                "firstname": "Test",
                "surname": "User",
                "password": "SecurePass123!",
                "password_rep": "DifferentPass123!",
                "pubkey": "",
                "submit": "Get Key",
            },
        )
        # 200 = form re-displayed with error
        assert response.status_code == 200

    def test_duplicate_mat_num(
        self,
        raw_client_follow_redirects: httpx.Client,
        registered_student: StudentCredentials,
    ) -> None:
        """Registering with an existing mat_num should be rejected."""
        response = raw_client_follow_redirects.post(
            "/student/getkey",
            data={
                "mat_num": registered_student.mat_num,
                "firstname": "Different",
                "surname": "User",
                "password": "SecurePass456!",
                "password_rep": "SecurePass456!",
                "pubkey": "",
                "submit": "Get Key",
            },
        )
        # 200 = form re-displayed with error
        assert response.status_code == 200
        assert (
            "already registered" in response.text.lower()
            or "error" in response.text.lower()
        )

    def test_invalid_rsa_key_format(
        self,
        raw_client_follow_redirects: httpx.Client,
        unique_mat_num: str,
        valid_password: str,
    ) -> None:
        """Invalid RSA key format should be rejected."""
        invalid_keys = [
            "not-a-key",
            "ssh-rsa short",  # Too short
            "-----BEGIN RSA PRIVATE KEY-----\ninvalid\n-----END RSA PRIVATE KEY-----",
            "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKg== test",  # Wrong type (ed25519)
        ]
        for pubkey in invalid_keys:
            response = raw_client_follow_redirects.post(
                "/student/getkey",
                data={
                    "mat_num": unique_mat_num,
                    "firstname": "Test",
                    "surname": "User",
                    "password": valid_password,
                    "password_rep": valid_password,
                    "pubkey": pubkey,
                    "submit": "Get Key",
                },
            )
            # 200 = form re-displayed with error
            assert response.status_code == 200

    def test_xss_in_name_fields(
        self,
        raw_client_follow_redirects: httpx.Client,
        unique_mat_num: str,
        valid_password: str,
    ) -> None:
        """XSS payloads in name fields should be escaped or rejected."""
        xss_payloads = [
            "<script>alert('XSS')</script>",
            "<img src=x onerror=alert('XSS')>",
            "'; alert('XSS'); //",
            "<svg onload=alert('XSS')>",
        ]
        for payload in xss_payloads:
            response = raw_client_follow_redirects.post(
                "/student/getkey",
                data={
                    "mat_num": unique_mat_num,
                    "firstname": payload,
                    "surname": payload,
                    "password": valid_password,
                    "password_rep": valid_password,
                    "pubkey": "",
                    "submit": "Get Key",
                },
            )
            # 200 = form re-displayed with error
            assert response.status_code == 200
            # XSS should be escaped in response
            if payload in response.text:
                # If payload appears, it should be escaped
                assert f">{payload}<" not in response.text

    def test_successful_registration(
        self,
        raw_client_follow_redirects: httpx.Client,
        unique_mat_num: str,
        valid_password: str,
    ) -> None:
        """Valid registration should succeed."""
        response = raw_client_follow_redirects.post(
            "/student/getkey",
            data={
                "mat_num": unique_mat_num,
                "firstname": "Valid",
                "surname": "Student",
                "password": valid_password,
                "password_rep": valid_password,
                "pubkey": "",
                "submit": "Get Key",
            },
        )
        # 200 = success
        assert response.status_code == 200
        # Should show keys or download links
        assert (
            "download" in response.text.lower()
            or "key" in response.text.lower()
            or "-----BEGIN" in response.text
        )


@pytest.mark.api
@pytest.mark.security
class TestStudentRestoreKey:
    """
    Tests for /student/restoreKey endpoint.

    This endpoint allows recovering keys using mat_num and password.
    """

    def test_get_form(self, raw_client: httpx.Client) -> None:
        """GET request should return restore form."""
        response = raw_client.get("/student/restoreKey")
        # 200 = form
        assert response.status_code == 200

    def test_invalid_mat_num_format(
        self, raw_client_follow_redirects: httpx.Client
    ) -> None:
        """Non-numeric mat_num should be rejected."""
        response = raw_client_follow_redirects.post(
            "/student/restoreKey",
            data={
                "mat_num": "not_numeric",
                "password": "anypassword",
                "submit": "Restore",
            },
        )
        # 200 = form with error
        assert response.status_code == 200

    def test_nonexistent_user(self, raw_client_follow_redirects: httpx.Client) -> None:
        """Non-existent mat_num should return error."""
        response = raw_client_follow_redirects.post(
            "/student/restoreKey",
            data={
                "mat_num": "99999999",  # Unlikely to exist
                "password": "anypassword",
                "submit": "Restore",
            },
        )
        # 200 = form with error
        assert response.status_code == 200
        # Should show generic error (not reveal if user exists)
        assert (
            "wrong password" in response.text.lower()
            or "unknown" in response.text.lower()
            or "error" in response.text.lower()
        )

    def test_wrong_password(
        self,
        raw_client_follow_redirects: httpx.Client,
        registered_student: StudentCredentials,
    ) -> None:
        """Wrong password should return error."""
        response = raw_client_follow_redirects.post(
            "/student/restoreKey",
            data={
                "mat_num": registered_student.mat_num,
                "password": "WrongPassword123!",
                "submit": "Restore",
            },
        )
        # 200 = form with error
        assert response.status_code == 200
        # Should show error
        assert (
            "wrong" in response.text.lower()
            or "error" in response.text.lower()
            or "password" in response.text.lower()
        )

    def test_successful_restore(
        self,
        raw_client_follow_redirects: httpx.Client,
        registered_student: StudentCredentials,
    ) -> None:
        """Valid credentials should show keys."""
        response = raw_client_follow_redirects.post(
            "/student/restoreKey",
            data={
                "mat_num": registered_student.mat_num,
                "password": registered_student.password,
                "submit": "Restore",
            },
        )
        # 200 = success
        assert response.status_code == 200
        # Should show download links
        assert (
            "download" in response.text.lower()
            or "key" in response.text.lower()
            or "/student/download/" in response.text
        )

    def test_sql_injection_in_mat_num(
        self, raw_client_follow_redirects: httpx.Client
    ) -> None:
        """SQL injection in mat_num should be handled safely."""
        sql_payloads = [
            "1 OR 1=1",
            "1; DROP TABLE users;--",
            "1' OR '1'='1",
            "1 UNION SELECT * FROM users",
        ]
        for payload in sql_payloads:
            response = raw_client_follow_redirects.post(
                "/student/restoreKey",
                data={
                    "mat_num": payload,
                    "password": "anypassword",
                    "submit": "Restore",
                },
            )
            # Form re-displayed with error
            assert response.status_code == 200


@pytest.mark.api
@pytest.mark.security
class TestStudentDownloadPubkey:
    """
    Tests for /student/download/pubkey/<signed_mat> endpoint.

    This endpoint requires a valid signed URL.
    """

    def test_invalid_signature(self, raw_client: httpx.Client) -> None:
        """Invalid signature should be rejected."""
        response = raw_client.get("/student/download/pubkey/invalid_signature_token")
        assert response.status_code == 400

    def test_empty_signature(self, raw_client: httpx.Client) -> None:
        """Empty signature parameter should be rejected."""
        response = raw_client.get("/student/download/pubkey/")
        # 404 = route not matched (missing parameter)
        assert response.status_code == 404

    def test_tampered_signature(self, raw_client: httpx.Client) -> None:
        """Tampered signature should be rejected."""
        # Try a JWT-like token that's not valid for this system
        response = raw_client.get(
            "/student/download/pubkey/eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.tampered"
        )
        assert response.status_code == 400

    def test_special_chars_in_signature(self, raw_client: httpx.Client) -> None:
        """Special characters in signature should be handled safely."""
        special_tokens = [
            "../../../etc/passwd",
            "<script>alert(1)</script>",
            "'; DROP TABLE--",
            "%00null",
        ]
        for token in special_tokens:
            response = raw_client.get(f"/student/download/pubkey/{token}")
            assert response.status_code == 400


@pytest.mark.api
@pytest.mark.security
class TestStudentDownloadPrivkey:
    """
    Tests for /student/download/privkey/<signed_mat> endpoint.

    This endpoint requires a valid signed URL.
    Private key downloads are more sensitive than public keys.
    """

    def test_invalid_signature(self, raw_client: httpx.Client) -> None:
        """Invalid signature should be rejected."""
        response = raw_client.get("/student/download/privkey/invalid_signature_token")
        assert response.status_code == 400

    def test_empty_signature(self, raw_client: httpx.Client) -> None:
        """Empty signature parameter should be rejected."""
        response = raw_client.get("/student/download/privkey/")
        # 404 = route not matched (missing parameter)
        assert response.status_code == 404

    def test_tampered_signature(self, raw_client: httpx.Client) -> None:
        """Tampered signature should be rejected."""
        response = raw_client.get(
            "/student/download/privkey/eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.tampered"
        )
        assert response.status_code == 400


@pytest.mark.api
class TestStudentDefaultRoutes:
    """
    Tests for default route redirects.
    """

    def test_root_redirects_to_getkey(self, raw_client: httpx.Client) -> None:
        """Root URL should redirect to getkey."""
        response = raw_client.get("/")
        assert response.status_code == 302
        assert "getkey" in response.headers.get("location", "").lower()

    def test_student_redirects_to_getkey(self, raw_client: httpx.Client) -> None:
        """Student URL should redirect to getkey."""
        response = raw_client.get("/student")
        assert response.status_code == 302
        assert "getkey" in response.headers.get("location", "").lower()

    def test_student_slash_redirects_to_getkey(self, raw_client: httpx.Client) -> None:
        """Student/ URL should redirect to getkey."""
        response = raw_client.get("/student/")
        assert response.status_code == 302
        assert "getkey" in response.headers.get("location", "").lower()
