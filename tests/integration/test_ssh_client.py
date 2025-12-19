"""
Integration Tests for REFSSHClient

These tests require a running REF instance.
"""

import pytest

from helpers.ssh_client import REFSSHClient, wait_for_ssh_ready


@pytest.mark.needs_ref
class TestWaitForSSHReadyOnline:
    """Test the wait_for_ssh_ready utility function (requires REF)."""

    def test_returns_true_when_server_reachable(self, ssh_host: str, ssh_port: int):
        """Test that wait_for_ssh_ready returns True when server is up."""
        result = wait_for_ssh_ready(ssh_host, ssh_port, timeout=10.0, interval=1.0)
        assert isinstance(result, bool)
        # If REF is running, this should be True
        assert result is True


@pytest.mark.needs_ref
class TestREFSSHClientConnection:
    """Test SSH connection functionality (requires REF)."""

    @pytest.fixture
    def registered_student(self, web_url: str):
        """Register a student and return credentials."""
        import uuid
        from helpers.web_client import REFWebClient

        client = REFWebClient(web_url)
        mat_num = str(uuid.uuid4().int)[:8]
        password = "TestPassword123!"

        success, private_key, public_key = client.register_student(
            mat_num=mat_num,
            firstname="SSH",
            surname="Test",
            password=password,
        )
        client.close()

        if not success or not private_key:
            pytest.fail("Failed to register student for SSH test")

        return {
            "mat_num": mat_num,
            "private_key": private_key,
            "public_key": public_key,
        }

    def test_connect_requires_private_key(self, ssh_host: str, ssh_port: int):
        """Test that connect fails without valid private key."""
        client = REFSSHClient(ssh_host, ssh_port)
        with pytest.raises(Exception):
            # Invalid private key should raise an exception
            client.connect("not-a-valid-key", "test-exercise")

    def test_close_on_unconnected_client(self, ssh_host: str, ssh_port: int):
        """Test that close works on unconnected client."""
        client = REFSSHClient(ssh_host, ssh_port)
        # Should not raise any exception
        client.close()
        assert not client.is_connected()
