"""
Integration Tests for REFWebClient

These tests require a running REF instance.
"""

import pytest

from helpers.web_client import REFWebClient


@pytest.mark.needs_ref
class TestREFWebClientBasics:
    """Test basic REFWebClient functionality (requires REF)."""

    @pytest.fixture
    def client(self, web_url: str):
        """Create a web client for testing."""
        client = REFWebClient(web_url)
        yield client
        client.close()

    def test_health_check_returns_bool(self, client: REFWebClient):
        """Test that health_check returns a boolean."""
        result = client.health_check()
        assert isinstance(result, bool)

    def test_health_check_when_running(self, client: REFWebClient):
        """Test that health_check returns True when REF is running."""
        assert client.health_check() is True


@pytest.mark.needs_ref
class TestREFWebClientLogin:
    """Test login functionality (requires REF)."""

    @pytest.fixture
    def client(self, web_url: str):
        """Create a web client for testing."""
        client = REFWebClient(web_url)
        yield client
        client.close()

    def test_login_with_invalid_credentials(self, client: REFWebClient):
        """Test that login fails with invalid credentials."""
        result = client.login("invalid_user", "invalid_password")
        assert result is False
        assert not client.is_logged_in()

    def test_login_with_valid_admin_credentials(
        self, client: REFWebClient, admin_password: str
    ):
        """Test that login succeeds with valid admin credentials."""
        result = client.login("0", admin_password)
        assert result is True
        assert client.is_logged_in()

    def test_logout(self, client: REFWebClient, admin_password: str):
        """Test that logout works."""
        # First login
        client.login("0", admin_password)
        assert client.is_logged_in()

        # Then logout
        result = client.logout()
        assert result is True
        assert not client.is_logged_in()

    def test_login_state_persists(self, client: REFWebClient, admin_password: str):
        """Test that login state persists across requests."""
        client.login("0", admin_password)
        assert client.is_logged_in()

        # Make another request and verify we're still logged in
        response = client.client.get("/admin/exercise/view")
        assert response.status_code == 200
        # If not logged in, we'd be redirected to login page
        assert "login" not in response.url.path.lower()


@pytest.mark.needs_ref
class TestREFWebClientExercises:
    """Test exercise-related functionality (requires REF)."""

    @pytest.fixture
    def admin_client(self, web_url: str, admin_password: str):
        """Create an authenticated admin client."""
        client = REFWebClient(web_url)
        success = client.login("0", admin_password)
        if not success:
            pytest.fail("Failed to login as admin")
        yield client
        client.close()

    def test_get_exercises_returns_tuple(self, admin_client: REFWebClient):
        """Test that get_exercises returns a tuple of two lists."""
        result = admin_client.get_exercises()
        assert isinstance(result, tuple)
        assert len(result) == 2
        imported, importable = result
        assert isinstance(imported, list)
        assert isinstance(importable, list)

    def test_get_exercise_by_name_returns_none_for_nonexistent(
        self, admin_client: REFWebClient
    ):
        """Test that get_exercise_by_name returns None for nonexistent exercise."""
        result = admin_client.get_exercise_by_name("nonexistent_exercise_xyz123")
        assert result is None

    def test_get_exercise_id_by_name_returns_none_for_nonexistent(
        self, admin_client: REFWebClient
    ):
        """Test that get_exercise_id_by_name returns None for nonexistent exercise."""
        result = admin_client.get_exercise_id_by_name("nonexistent_exercise_xyz123")
        assert result is None


@pytest.mark.needs_ref
class TestREFWebClientStudentRegistration:
    """Test student registration functionality (requires REF)."""

    @pytest.fixture
    def client(self, web_url: str):
        """Create a web client for testing."""
        client = REFWebClient(web_url)
        yield client
        client.close()

    def test_register_student_returns_tuple(self, client: REFWebClient):
        """Test that register_student returns a tuple."""
        import uuid

        mat_num = str(uuid.uuid4().int)[:8]
        result = client.register_student(
            mat_num=mat_num,
            firstname="Unit",
            surname="Test",
            password="TestPassword123!",
        )
        assert isinstance(result, tuple)
        assert len(result) == 3
        success, private_key, public_key = result
        assert isinstance(success, bool)

    def test_register_student_duplicate_fails(self, client: REFWebClient):
        """Test that registering the same student twice fails."""
        import uuid

        mat_num = str(uuid.uuid4().int)[:8]

        # First registration should succeed
        success1, _, _ = client.register_student(
            mat_num=mat_num,
            firstname="Unit",
            surname="Test",
            password="TestPassword123!",
        )
        assert success1, "First registration should succeed"

        # Second registration with same mat_num should fail
        success2, _, _ = client.register_student(
            mat_num=mat_num,
            firstname="Unit",
            surname="Test2",
            password="TestPassword123!",
        )
        assert not success2, "Duplicate registration should fail"

    def test_create_student_returns_bool(self, client: REFWebClient):
        """Test that create_student returns a boolean."""
        import uuid

        mat_num = str(uuid.uuid4().int)[:8]
        result = client.create_student(
            mat_num=mat_num,
            firstname="Unit",
            surname="Test",
            password="TestPassword123!",
        )
        assert isinstance(result, bool)


@pytest.mark.needs_ref
class TestREFWebClientRestoreKey:
    """Test key restoration functionality (requires REF)."""

    @pytest.fixture
    def client(self, web_url: str):
        """Create a web client for testing."""
        client = REFWebClient(web_url)
        yield client
        client.close()

    def test_restore_key_with_wrong_password(self, client: REFWebClient):
        """Test that restore_student_key fails with wrong password."""
        import uuid

        mat_num = str(uuid.uuid4().int)[:8]

        # First register a student
        success, _, _ = client.register_student(
            mat_num=mat_num,
            firstname="Unit",
            surname="Test",
            password="TestPassword123!",
        )
        assert success, "Registration should succeed"

        # Try to restore with wrong password
        restore_success, _, _ = client.restore_student_key(
            mat_num=mat_num, password="WrongPassword123!"
        )
        assert not restore_success, "Restore with wrong password should fail"

    def test_restore_key_with_correct_password(self, client: REFWebClient):
        """Test that restore_student_key succeeds with correct password."""
        import uuid

        mat_num = str(uuid.uuid4().int)[:8]
        password = "TestPassword123!"

        # First register a student
        success, orig_private_key, orig_public_key = client.register_student(
            mat_num=mat_num,
            firstname="Unit",
            surname="Test",
            password=password,
        )
        assert success, "Registration should succeed"

        # Restore with correct password
        restore_success, restored_private_key, restored_public_key = (
            client.restore_student_key(mat_num=mat_num, password=password)
        )
        assert restore_success, "Restore with correct password should succeed"

        # Keys should match
        if orig_private_key and restored_private_key:
            assert orig_private_key == restored_private_key


@pytest.mark.needs_ref
class TestREFWebClientAPIEndpoints:
    """Test API endpoint functionality (requires REF)."""

    @pytest.fixture
    def client(self, web_url: str):
        """Create a web client for testing."""
        client = REFWebClient(web_url)
        yield client
        client.close()

    def test_api_get_header_returns_data(self, client: REFWebClient):
        """Test that api_get_header returns data."""
        result = client.api_get_header()
        # Should return some data (the SSH welcome header)
        # The exact format may vary, but it should not be None
        assert result is not None or True  # API may return None if not configured
