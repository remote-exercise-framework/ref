"""
Rate Limiting Tests

Tests to verify rate limiting behavior on sensitive endpoints.

Security focus:
- Brute force prevention
- Rate limit enforcement
- Proper error responses when rate limited

NOTE: Rate limiting is DISABLED by default in test mode (RATELIMIT_ENABLED=false).
These tests document the expected rate limiting behavior and verify endpoints
work correctly when rate limiting is disabled. To test actual rate limiting,
set RATELIMIT_ENABLED=true in the test instance configuration.
"""

from __future__ import annotations

import httpx
import pytest


@pytest.mark.api
@pytest.mark.security
class TestStudentEndpointRateLimiting:
    """
    Tests for rate limiting on student endpoints.

    /student/getkey and /student/restoreKey have rate limits of:
    - 16 per minute
    - 1024 per day

    NOTE: Rate limiting is disabled in test mode by default.
    """

    def test_getkey_rate_limit_documented(self, raw_client: httpx.Client) -> None:
        """
        Document rate limiting behavior for /student/getkey.

        Rate limit: 16 per minute; 1024 per day
        This test documents the expected behavior.
        """
        # Make a request to verify endpoint works
        response = raw_client.get("/student/getkey")
        assert response.status_code == 200

    def test_restorekey_rate_limit_documented(self, raw_client: httpx.Client) -> None:
        """
        Document rate limiting behavior for /student/restoreKey.

        Rate limit: 16 per minute; 1024 per day
        This test documents the expected behavior.
        """
        response = raw_client.get("/student/restoreKey")
        assert response.status_code == 200

    def test_key_download_rate_limit_documented(self, raw_client: httpx.Client) -> None:
        """
        Document rate limiting behavior for key downloads.

        Rate limit: 16 per minute; 1024 per day
        """
        # Try to access with invalid token (just testing endpoint responds)
        response = raw_client.get("/student/download/pubkey/test")
        # Should get 400 (invalid token)
        assert response.status_code == 400


@pytest.mark.api
@pytest.mark.security
class TestInstanceApiRateLimiting:
    """
    Tests for rate limiting on instance API endpoints.

    /api/instance/reset and /api/instance/submit have rate limits of:
    - 3 per minute
    - 24 per day

    /api/instance/info has rate limit of:
    - 10 per minute

    NOTE: Rate limiting is disabled in test mode by default.
    """

    def test_instance_reset_rate_limit_documented(
        self, raw_client: httpx.Client
    ) -> None:
        """
        Document rate limiting behavior for /api/instance/reset.

        Rate limit: 3 per minute; 24 per day
        """
        # First request should work (even if auth fails)
        response = raw_client.post(
            "/api/instance/reset",
            json="invalid_token",
        )
        assert response.status_code == 400

    def test_instance_submit_rate_limit_documented(
        self, raw_client: httpx.Client
    ) -> None:
        """
        Document rate limiting behavior for /api/instance/submit.

        Rate limit: 3 per minute; 24 per day
        """
        response = raw_client.post(
            "/api/instance/submit",
            json="invalid_token",
        )
        assert response.status_code == 400

    def test_instance_info_rate_limit_documented(
        self, raw_client: httpx.Client
    ) -> None:
        """
        Document rate limiting behavior for /api/instance/info.

        Rate limit: 10 per minute
        """
        response = raw_client.post(
            "/api/instance/info",
            json="invalid_token",
        )
        assert response.status_code == 400


@pytest.mark.api
@pytest.mark.security
class TestRateLimitExemptEndpoints:
    """
    Tests for endpoints that are exempt from rate limiting.

    Some endpoints are marked with @limiter.exempt for operational reasons.
    NOTE: Rate limiting is disabled in test mode, so these tests verify
    endpoints work without rate limiting.
    """

    def test_ssh_authenticated_exempt(self, raw_client: httpx.Client) -> None:
        """
        /api/ssh-authenticated is rate limit exempt.

        This is because SSH connections may come in bursts.
        """
        # Should always work (no rate limit)
        for _ in range(5):
            response = raw_client.post(
                "/api/ssh-authenticated",
                json={"name": "test", "pubkey": "test"},
            )
            assert response.status_code == 400

    def test_provision_exempt(self, raw_client: httpx.Client) -> None:
        """
        /api/provision is rate limit exempt.

        This is called by SSH server for each connection.
        """
        for _ in range(5):
            response = raw_client.post(
                "/api/provision",
                json={"exercise_name": "test", "pubkey": "test"},
            )
            assert response.status_code == 400

    def test_getkeys_exempt(self, raw_client: httpx.Client) -> None:
        """
        /api/getkeys is rate limit exempt.

        This is called by SSH server to get authorized keys.
        """
        for _ in range(5):
            response = raw_client.post(
                "/api/getkeys",
                json={"username": "test"},
            )
            assert response.status_code == 400

    def test_getuserinfo_exempt(self, raw_client: httpx.Client) -> None:
        """
        /api/getuserinfo is rate limit exempt.
        """
        for _ in range(5):
            response = raw_client.post(
                "/api/getuserinfo",
                json={"pubkey": "test"},
            )
            assert response.status_code == 400

    def test_header_exempt(self, raw_client: httpx.Client) -> None:
        """
        /api/header is rate limit exempt.
        """
        for _ in range(5):
            response = raw_client.post("/api/header")
            assert response.status_code == 200


@pytest.mark.api
@pytest.mark.security
class TestBruteForceProtection:
    """
    Tests for brute force protection.

    These tests verify endpoint behavior under repeated requests.
    NOTE: Rate limiting is disabled in test mode by default.
    """

    def test_login_brute_force_documentation(self, raw_client: httpx.Client) -> None:
        """
        Document brute force protection on login.

        Note: Rate limiting is disabled in test mode.
        This test verifies multiple failed logins are handled correctly.
        """
        # Try multiple failed logins
        for i in range(5):
            response = raw_client.post(
                "/login",
                data={
                    "username": "0",
                    "password": f"wrong_password_{i}",
                    "submit": "Login",
                },
            )
            # Form re-shown with error
            assert response.status_code == 200

    def test_restorekey_brute_force_documentation(
        self, raw_client: httpx.Client, unique_mat_num: str
    ) -> None:
        """
        Document brute force protection on key restore.

        Rate limit: 16 per minute (when enabled)
        NOTE: Rate limiting is disabled in test mode.
        """
        # Try multiple failed restores
        for i in range(5):
            response = raw_client.post(
                "/student/restoreKey",
                data={
                    "mat_num": unique_mat_num,
                    "password": f"wrong_{i}",
                    "submit": "Restore",
                },
            )
            # Form re-shown with error
            assert response.status_code == 200


@pytest.mark.api
class TestRateLimitHeaders:
    """
    Tests for rate limit headers in responses.

    Many rate limiters include headers like:
    - X-RateLimit-Limit
    - X-RateLimit-Remaining
    - X-RateLimit-Reset
    - Retry-After (when rate limited)

    NOTE: Rate limiting is disabled in test mode, so headers may not be present.
    """

    def test_rate_limit_headers_documented(self, raw_client: httpx.Client) -> None:
        """
        Document presence of rate limit headers.

        This test checks if rate limit headers are present.
        NOTE: Rate limiting is disabled in test mode.
        """
        response = raw_client.get("/student/getkey")

        # Check for common rate limit headers
        # Flask-Limiter may or may not include these headers
        # This test documents which headers are present
        has_limit = "X-RateLimit-Limit" in response.headers
        has_remaining = "X-RateLimit-Remaining" in response.headers
        has_reset = "X-RateLimit-Reset" in response.headers

        # Endpoint should respond successfully
        assert response.status_code == 200
        # Headers may or may not be present depending on config
        _ = (has_limit, has_remaining, has_reset)  # Document presence
