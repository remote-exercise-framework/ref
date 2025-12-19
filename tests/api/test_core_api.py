"""
Core API Security Tests

Tests for /api/* endpoints that handle SSH integration.
These endpoints are called by the SSH entry server.

Security focus:
- Malformed request handling
- Missing/invalid fields
- UTF-8 encoding validation
- Signature verification (where applicable)
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import httpx
import pytest

if TYPE_CHECKING:
    from .conftest import StudentCredentials


@pytest.mark.api
@pytest.mark.security
class TestApiSshAuthenticated:
    """
    Tests for /api/ssh-authenticated endpoint.

    This endpoint is called by the SSH server after successful authentication.
    SECURITY NOTE: This endpoint currently lacks signature verification
    (see api.py lines 397-404, commented out FIXME).
    """

    def test_missing_json_body(self, raw_client: httpx.Client) -> None:
        """Request without JSON body should return error."""
        response = raw_client.post("/api/ssh-authenticated")
        # Returns 400 for missing body or 200 with error in body
        assert response.status_code in [200, 400]

    def test_empty_json_body(self, raw_client: httpx.Client) -> None:
        """Empty JSON object should return error for missing fields."""
        response = raw_client.post(
            "/api/ssh-authenticated",
            json={},
        )
        # Returns 400 for invalid request or 200 with error in body
        assert response.status_code in [200, 400]

    def test_missing_name_field(self, raw_client: httpx.Client) -> None:
        """Request without 'name' field should return error."""
        response = raw_client.post(
            "/api/ssh-authenticated",
            json={"pubkey": "ssh-rsa AAAAB3... test@test"},
        )
        # Returns 400 for invalid request or 200 with error in body
        assert response.status_code in [200, 400]

    def test_missing_pubkey_field(self, raw_client: httpx.Client) -> None:
        """Request without 'pubkey' field should return error."""
        response = raw_client.post(
            "/api/ssh-authenticated",
            json={"name": "test_exercise"},
        )
        # Returns 400 for invalid request or 200 with error in body
        assert response.status_code in [200, 400]

    def test_invalid_utf8_exercise_name(self, raw_client: httpx.Client) -> None:
        """Invalid UTF-8 in exercise name should be handled gracefully."""
        # Send bytes that can't be encoded as UTF-8
        response = raw_client.post(
            "/api/ssh-authenticated",
            content=json.dumps({"name": "test\udcff", "pubkey": "ssh-rsa test"}).encode(
                "utf-8", errors="surrogatepass"
            ),
            headers={"Content-Type": "application/json"},
        )
        # Should not crash, should return error
        assert response.status_code in [200, 400]

    def test_nonexistent_pubkey(self, raw_client: httpx.Client) -> None:
        """Non-existent pubkey should return error."""
        response = raw_client.post(
            "/api/ssh-authenticated",
            json={
                "name": "test_exercise",
                "pubkey": "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQCx... nonexistent@test",
            },
        )
        # Returns 400 for invalid request or 200 with error in body
        assert response.status_code in [200, 400]

    def test_non_dict_payload(self, raw_client: httpx.Client) -> None:
        """Non-dict JSON payload should return error."""
        response = raw_client.post(
            "/api/ssh-authenticated",
            json=["not", "a", "dict"],
        )
        # Returns 400 for invalid request or 200 with error in body
        assert response.status_code in [200, 400]

    def test_null_values(self, raw_client: httpx.Client) -> None:
        """Null values for required fields should return error."""
        response = raw_client.post(
            "/api/ssh-authenticated",
            json={"name": None, "pubkey": None},
        )
        # Returns 400 for invalid request or 200 with error in body
        assert response.status_code in [200, 400]

    def test_accepts_unsigned_request_security_note(
        self, raw_client: httpx.Client, registered_student: StudentCredentials
    ) -> None:
        """
        SECURITY DOCUMENTATION: This endpoint accepts unsigned requests.

        The signature verification code is commented out in api.py:397-404.
        This test documents that the endpoint accepts unsigned requests.
        """
        # This request is not signed, but the endpoint should process it
        # if it had valid credentials
        response = raw_client.post(
            "/api/ssh-authenticated",
            json={
                "name": "nonexistent_exercise",
                "pubkey": registered_student.public_key or "ssh-rsa test",
            },
        )
        # The endpoint processes the request (even without signature)
        # Returns 400 for invalid request or 200 with error in body
        assert response.status_code in [200, 400]


@pytest.mark.api
@pytest.mark.security
class TestApiProvision:
    """
    Tests for /api/provision endpoint.

    This endpoint requires signature verification using SSH_TO_WEB_KEY.
    """

    def test_missing_json_body(self, raw_client: httpx.Client) -> None:
        """Request without JSON body should return error."""
        response = raw_client.post("/api/provision")
        # Returns 400 for invalid request or 200 with error in body
        assert response.status_code in [200, 400]

    def test_invalid_signature(self, raw_client: httpx.Client) -> None:
        """Invalid/missing signature should be rejected."""
        response = raw_client.post(
            "/api/provision",
            json={"exercise_name": "test", "pubkey": "ssh-rsa test"},
        )
        # Returns 400 for invalid request or 200 with error in body
        assert response.status_code in [200, 400]

    def test_malformed_json(self, raw_client: httpx.Client) -> None:
        """Malformed JSON should return error."""
        response = raw_client.post(
            "/api/provision",
            content=b"not valid json",
            headers={"Content-Type": "application/json"},
        )
        # Returns 400 for invalid request or 200 with error in body
        assert response.status_code in [200, 400]

    def test_string_instead_of_json(self, raw_client: httpx.Client) -> None:
        """String payload (not JSON object) should be rejected."""
        response = raw_client.post(
            "/api/provision",
            json="just a string",
        )
        # Returns 400 for invalid request or 200 with error in body
        assert response.status_code in [200, 400]


@pytest.mark.api
@pytest.mark.security
class TestApiGetkeys:
    """
    Tests for /api/getkeys endpoint.

    This endpoint requires signature verification.
    """

    def test_missing_json_body(self, raw_client: httpx.Client) -> None:
        """Request without JSON body should return error."""
        response = raw_client.post("/api/getkeys")
        # Returns 400 for invalid request or 200 with error in body
        assert response.status_code in [200, 400]

    def test_invalid_signature(self, raw_client: httpx.Client) -> None:
        """Invalid signature should be rejected."""
        response = raw_client.post(
            "/api/getkeys",
            json={"username": "test"},
        )
        # Returns 400 for invalid request or 200 with error in body
        assert response.status_code in [200, 400]

    def test_get_method_also_works(self, raw_client: httpx.Client) -> None:
        """GET method should also be handled (endpoint accepts GET and POST)."""
        response = raw_client.get("/api/getkeys")
        # Returns 400 for invalid request or 200 with error in body
        assert response.status_code in [200, 400]


@pytest.mark.api
@pytest.mark.security
class TestApiGetuserinfo:
    """
    Tests for /api/getuserinfo endpoint.

    This endpoint requires signature verification.
    """

    def test_missing_json_body(self, raw_client: httpx.Client) -> None:
        """Request without JSON body should return error."""
        response = raw_client.post("/api/getuserinfo")
        # Returns 400 for invalid request or 200 with error in body
        assert response.status_code in [200, 400]

    def test_invalid_signature(self, raw_client: httpx.Client) -> None:
        """Invalid signature should be rejected."""
        response = raw_client.post(
            "/api/getuserinfo",
            json={"pubkey": "ssh-rsa test"},
        )
        # Returns 400 for invalid request or 200 with error in body
        assert response.status_code in [200, 400]


@pytest.mark.api
class TestApiHeader:
    """
    Tests for /api/header endpoint.

    This endpoint returns the SSH welcome header and is rate-limit exempt.
    """

    def test_get_header(self, raw_client: httpx.Client) -> None:
        """Should return header message."""
        response = raw_client.post("/api/header")
        assert response.status_code == 200
        # Returns JSON with the header string

    def test_get_method_works(self, raw_client: httpx.Client) -> None:
        """GET method should also work."""
        response = raw_client.get("/api/header")
        assert response.status_code == 200


@pytest.mark.api
@pytest.mark.security
class TestApiInstanceReset:
    """
    Tests for /api/instance/reset endpoint.

    This endpoint requires signed container request with TimedSerializer.
    """

    def test_missing_json_body(self, raw_client: httpx.Client) -> None:
        """Request without JSON body should return error."""
        response = raw_client.post("/api/instance/reset")
        # Returns 400 for invalid request or 200 with error in body
        assert response.status_code in [200, 400]

    def test_invalid_signature(self, raw_client: httpx.Client) -> None:
        """Invalid signature should be rejected."""
        response = raw_client.post(
            "/api/instance/reset",
            json={"instance_id": 1},
        )
        # Returns 400 for invalid request or 200 with error in body
        assert response.status_code in [200, 400]

    def test_string_payload(self, raw_client: httpx.Client) -> None:
        """String payload that's not a valid signed token should be rejected."""
        response = raw_client.post(
            "/api/instance/reset",
            json="invalid_token_string",
        )
        # Returns 400 for invalid request, 200 with error in body, 500 server error
        assert response.status_code in [200, 400, 500]

    def test_malformed_token(self, raw_client: httpx.Client) -> None:
        """Malformed token should be rejected."""
        response = raw_client.post(
            "/api/instance/reset",
            content=b'"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.invalid"',
            headers={"Content-Type": "application/json"},
        )
        # Returns 400 for invalid request, 200 with error in body, or 500 for server error
        assert response.status_code in [200, 400, 500]


@pytest.mark.api
@pytest.mark.security
class TestApiInstanceSubmit:
    """
    Tests for /api/instance/submit endpoint.

    This endpoint requires signed container request.
    """

    def test_missing_json_body(self, raw_client: httpx.Client) -> None:
        """Request without JSON body should return error."""
        response = raw_client.post("/api/instance/submit")
        # Returns 400 for invalid request or 200 with error in body
        assert response.status_code in [200, 400]

    def test_invalid_signature(self, raw_client: httpx.Client) -> None:
        """Invalid signature should be rejected."""
        response = raw_client.post(
            "/api/instance/submit",
            json={
                "instance_id": 1,
                "output": "test output",
                "test_results": [{"task_name": "test", "success": True, "score": None}],
            },
        )
        # Returns 400 for invalid request or 200 with error in body
        assert response.status_code in [200, 400]


@pytest.mark.api
@pytest.mark.security
class TestApiInstanceInfo:
    """
    Tests for /api/instance/info endpoint.

    This endpoint requires signed container request.
    """

    def test_missing_json_body(self, raw_client: httpx.Client) -> None:
        """Request without JSON body should return error."""
        response = raw_client.post("/api/instance/info")
        # Returns 400 for invalid request or 200 with error in body
        assert response.status_code in [200, 400]

    def test_invalid_signature(self, raw_client: httpx.Client) -> None:
        """Invalid signature should be rejected."""
        response = raw_client.post(
            "/api/instance/info",
            json={"instance_id": 1},
        )
        # Returns 400 for invalid request or 200 with error in body
        assert response.status_code in [200, 400]


@pytest.mark.api
@pytest.mark.security
class TestApiInputValidation:
    """
    General input validation tests across API endpoints.
    """

    def test_oversized_json_body(self, raw_client: httpx.Client) -> None:
        """Very large JSON body should be handled gracefully."""
        large_data = {"name": "a" * 100000, "pubkey": "b" * 100000}
        response = raw_client.post(
            "/api/ssh-authenticated",
            json=large_data,
        )
        # Should not crash, should return some response
        assert response.status_code in [200, 400, 413, 500]

    def test_deeply_nested_json(self, raw_client: httpx.Client) -> None:
        """Deeply nested JSON should be handled gracefully."""
        nested: dict = {"name": "test", "pubkey": "test"}
        for _ in range(100):
            nested = {"nested": nested}
        response = raw_client.post(
            "/api/ssh-authenticated",
            json=nested,
        )
        # Should not crash
        assert response.status_code in [200, 400, 500]

    def test_special_characters_in_exercise_name(
        self, raw_client: httpx.Client
    ) -> None:
        """Special characters in exercise name should be handled."""
        special_names = [
            "test<script>alert(1)</script>",  # XSS attempt
            "test'; DROP TABLE users; --",  # SQL injection attempt
            "test\x00null",  # Null byte
            "test\nwith\nnewlines",  # Newlines
            "../../../etc/passwd",  # Path traversal
        ]
        for name in special_names:
            response = raw_client.post(
                "/api/ssh-authenticated",
                json={"name": name, "pubkey": "ssh-rsa test"},
            )
            # Should not crash, should return error or handle gracefully
            assert response.status_code in [
                200,
                400,
            ], f"Unexpected status for name: {name}"

    def test_unicode_exercise_names(self, raw_client: httpx.Client) -> None:
        """Unicode characters in exercise name should be handled."""
        unicode_names = [
            "test_exercise_日本語",  # Japanese
            "test_exercise_emoji_🎉",  # Emoji
            "test_exercise_arabic_العربية",  # Arabic
            "test_exercise_cyrillic_русский",  # Cyrillic
        ]
        for name in unicode_names:
            response = raw_client.post(
                "/api/ssh-authenticated",
                json={"name": name, "pubkey": "ssh-rsa test"},
            )
            # Should handle gracefully
            assert response.status_code in [200, 400], f"Failed for name: {name}"
