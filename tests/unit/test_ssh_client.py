"""
Unit Tests for REFSSHClient

These tests verify the SSH client helper functions work correctly.
All tests in this file can run without a running REF instance.
"""

import pytest

from helpers.ssh_client import REFSSHClient, wait_for_ssh_ready


@pytest.mark.offline
class TestWaitForSSHReadyOffline:
    """Test the wait_for_ssh_ready utility function (offline tests)."""

    def test_returns_false_when_server_unreachable(self):
        """Test that wait_for_ssh_ready returns False for unreachable server."""
        # Use a port that's almost certainly not listening
        result = wait_for_ssh_ready("localhost", 59999, timeout=2.0, interval=0.5)
        assert result is False

    def test_respects_timeout(self):
        """Test that wait_for_ssh_ready respects the timeout parameter."""
        import time

        start = time.time()
        # Use a short timeout
        wait_for_ssh_ready("localhost", 59999, timeout=1.0, interval=0.5)
        elapsed = time.time() - start
        # Should not take much longer than timeout
        assert elapsed < 3.0


@pytest.mark.offline
class TestREFSSHClientInitialization:
    """Test REFSSHClient initialization."""

    def test_client_initialization(self):
        """Test that client initializes correctly."""
        client = REFSSHClient("localhost", 2222)
        assert client.host == "localhost"
        assert client.port == 2222
        assert client.client is None
        assert not client.is_connected()

    def test_client_with_custom_timeout(self):
        """Test that client accepts custom timeout."""
        client = REFSSHClient("localhost", 2222, timeout=60.0)
        assert client.timeout == 60.0

    def test_client_default_timeout(self):
        """Test that client has default timeouts (60s connection, 10s commands)."""
        client = REFSSHClient("localhost", 2222)
        assert client.timeout == 60.0  # Connection timeout for container interactions
        assert client.command_timeout == 10.0  # Individual command timeout


@pytest.mark.offline
class TestREFSSHClientCommands:
    """Test SSH command execution functionality (offline - tests error handling)."""

    def test_execute_raises_when_not_connected(self):
        """Test that execute raises error when not connected."""
        client = REFSSHClient("localhost", 2222)
        with pytest.raises(RuntimeError, match="Not connected"):
            client.execute("echo test")

    def test_write_file_raises_when_not_connected(self):
        """Test that write_file raises error when not connected."""
        client = REFSSHClient("localhost", 2222)
        with pytest.raises(RuntimeError, match="Not connected"):
            client.write_file("/tmp/test", "content")

    def test_read_file_raises_when_not_connected(self):
        """Test that read_file raises error when not connected."""
        client = REFSSHClient("localhost", 2222)
        with pytest.raises(RuntimeError, match="Not connected"):
            client.read_file("/tmp/test")

    def test_file_exists_raises_when_not_connected(self):
        """Test that file_exists raises error when not connected."""
        client = REFSSHClient("localhost", 2222)
        with pytest.raises(RuntimeError, match="Not connected"):
            client.file_exists("/tmp/test")

    def test_list_files_raises_when_not_connected(self):
        """Test that list_files raises error when not connected."""
        client = REFSSHClient("localhost", 2222)
        with pytest.raises(RuntimeError, match="Not connected"):
            client.list_files("/tmp")


@pytest.mark.offline
class TestREFSSHClientTaskCommands:
    """Test REF task command functionality (offline - tests error handling)."""

    def test_run_task_command_requires_connection(self):
        """Test that task commands require connection."""
        client = REFSSHClient("localhost", 2222)
        with pytest.raises(RuntimeError, match="Not connected"):
            client.run_task_command("check")

    def test_submit_method_exists(self):
        """Test that submit method exists."""
        client = REFSSHClient("localhost", 2222)
        assert hasattr(client, "submit")
        assert callable(getattr(client, "submit"))

    def test_check_method_exists(self):
        """Test that check method exists."""
        client = REFSSHClient("localhost", 2222)
        assert hasattr(client, "check")
        assert callable(getattr(client, "check"))

    def test_reset_method_exists(self):
        """Test that reset method exists."""
        client = REFSSHClient("localhost", 2222)
        assert hasattr(client, "reset")
        assert callable(getattr(client, "reset"))

    def test_get_info_method_exists(self):
        """Test that get_info method exists."""
        client = REFSSHClient("localhost", 2222)
        assert hasattr(client, "get_info")
        assert callable(getattr(client, "get_info"))
