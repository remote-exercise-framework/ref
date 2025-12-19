"""
API Security Test Configuration and Fixtures

Provides fixtures for testing API endpoints with malformed requests,
security vulnerabilities, and input validation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Generator, Optional

import httpx
import pytest

if TYPE_CHECKING:
    from helpers.ref_instance import REFInstance


@dataclass
class StudentCredentials:
    """Credentials for a registered student."""

    mat_num: str
    firstname: str
    surname: str
    password: str
    private_key: Optional[str]
    public_key: Optional[str]


@pytest.fixture(scope="function")
def raw_client(web_url: str) -> Generator[httpx.Client, None, None]:
    """
    Raw HTTP client without session/auth for testing unauthenticated access.

    This client does NOT follow redirects by default, allowing tests to
    verify redirect behavior and status codes.
    """
    client = httpx.Client(
        base_url=web_url,
        timeout=30.0,
        follow_redirects=False,
    )
    yield client
    client.close()


@pytest.fixture(scope="function")
def raw_client_follow_redirects(web_url: str) -> Generator[httpx.Client, None, None]:
    """
    Raw HTTP client that follows redirects.

    Use this when you need to verify the final destination of redirects.
    """
    client = httpx.Client(
        base_url=web_url,
        timeout=30.0,
        follow_redirects=True,
    )
    yield client
    client.close()


@pytest.fixture(scope="function")
def registered_student(
    raw_client_follow_redirects: httpx.Client, unique_test_id: str
) -> StudentCredentials:
    """
    Create a registered student and return credentials.

    Uses the /student/getkey endpoint to register a new student.
    """
    mat_num = str(abs(hash(unique_test_id)) % 10000000)
    password = "TestPass123!"  # Meets password policy

    data = {
        "mat_num": mat_num,
        "firstname": f"Test_{unique_test_id[:4]}",
        "surname": f"User_{unique_test_id[4:8]}",
        "password": password,
        "password_rep": password,
        "pubkey": "",  # Let system generate keys
        "submit": "Get Key",
    }

    response = raw_client_follow_redirects.post("/student/getkey", data=data)
    assert response.status_code == 200, f"Failed to register student: {response.text}"

    # Extract keys from response
    private_key = None
    public_key = None

    if "-----BEGIN RSA PRIVATE KEY-----" in response.text:
        import re

        priv_match = re.search(
            r"(-----BEGIN RSA PRIVATE KEY-----.*?-----END RSA PRIVATE KEY-----)",
            response.text,
            re.DOTALL,
        )
        if priv_match:
            private_key = priv_match.group(1)

    if "ssh-rsa " in response.text:
        import re

        pub_match = re.search(r"(ssh-rsa [A-Za-z0-9+/=]+)", response.text)
        if pub_match:
            public_key = pub_match.group(1)

    # Also try download links
    if "/student/download/privkey/" in response.text:
        import re

        link_match = re.search(r'/student/download/privkey/([^"\'>\s]+)', response.text)
        if link_match:
            key_resp = raw_client_follow_redirects.get(
                f"/student/download/privkey/{link_match.group(1)}"
            )
            if key_resp.status_code == 200:
                private_key = key_resp.text

    if "/student/download/pubkey/" in response.text:
        import re

        link_match = re.search(r'/student/download/pubkey/([^"\'>\s]+)', response.text)
        if link_match:
            key_resp = raw_client_follow_redirects.get(
                f"/student/download/pubkey/{link_match.group(1)}"
            )
            if key_resp.status_code == 200:
                public_key = key_resp.text

    return StudentCredentials(
        mat_num=mat_num,
        firstname=data["firstname"],
        surname=data["surname"],
        password=password,
        private_key=private_key,
        public_key=public_key,
    )


@pytest.fixture(scope="function")
def unique_mat_num(unique_test_id: str) -> str:
    """Generate a unique matriculation number for testing."""
    return str(abs(hash(unique_test_id + "mat")) % 10000000)


@pytest.fixture(scope="function")
def valid_password() -> str:
    """Return a password that meets the password policy."""
    return "SecurePass123!"


@pytest.fixture(scope="function")
def admin_session(
    raw_client_follow_redirects: httpx.Client, admin_password: str
) -> httpx.Client:
    """
    Get an authenticated admin session.

    Returns the same client but logged in as admin.
    """
    response = raw_client_follow_redirects.post(
        "/login",
        data={
            "username": "0",  # Admin mat_num
            "password": admin_password,
            "submit": "Login",
        },
    )
    # Should redirect to admin page on success
    assert response.status_code == 200, f"Admin login failed: {response.text}"
    return raw_client_follow_redirects


def pytest_configure(config: pytest.Config) -> None:
    """Configure pytest markers for API tests."""
    config.addinivalue_line("markers", "api: API security tests")
    config.addinivalue_line("markers", "security: Security-focused tests")


@pytest.fixture(scope="function")
def file_browser_token_factory(
    ref_instance: "REFInstance",
) -> Callable[[str], str]:
    """
    Factory fixture for generating valid file browser tokens.

    Returns a function that takes a path_prefix and returns a signed token.
    This allows tests to verify that path traversal attempts are blocked
    at the path validation layer, not just due to invalid tokens.

    Usage:
        def test_path_traversal(admin_session, file_browser_token_factory):
            token = file_browser_token_factory("/tmp/test")
            response = admin_session.post(
                "/admin/file-browser/load-file",
                data={"path": "../etc/passwd", "token": token, "hide_hidden_files": "true"},
            )
            assert response.status_code == 400  # Blocked by path validation
    """
    from helpers.method_exec import sign_file_browser_path

    def _create_token(path_prefix: str) -> str:
        return sign_file_browser_path(ref_instance, path_prefix)

    return _create_token
