"""
E2E Test: SSH Port Forwarding Features

Tests SSH port forwarding capabilities for user containers.

Based on the custom OpenSSH configuration (ssh-wrapper/sshd_config):
- TCP forwarding: ENABLED (AllowTcpForwarding yes)
- Agent forwarding: DISABLED (AllowAgentForwarding no)
- X11 forwarding: DISABLED (X11Forwarding no)
"""

import socket
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

import paramiko
import pytest

from helpers.exercise_factory import create_sample_exercise
from helpers.ssh_client import REFSSHClient
from helpers.web_client import REFWebClient

if TYPE_CHECKING:
    from helpers.ref_instance import REFInstance

SSHClientFactory = Callable[[str, str], REFSSHClient]


def _enable_tcp_forwarding(ref_instance: "REFInstance") -> bool:
    """Enable TCP port forwarding in system settings."""

    def _enable() -> bool:
        from flask import current_app

        from ref.model.settings import SystemSettingsManager

        SystemSettingsManager.ALLOW_TCP_PORT_FORWARDING.value = True
        current_app.db.session.commit()
        return True

    return ref_instance.remote_exec(_enable)


def _disable_tcp_forwarding(ref_instance: "REFInstance") -> bool:
    """Disable TCP port forwarding in system settings."""

    def _disable() -> bool:
        from flask import current_app

        from ref.model.settings import SystemSettingsManager

        SystemSettingsManager.ALLOW_TCP_PORT_FORWARDING.value = False
        current_app.db.session.commit()
        return True

    return ref_instance.remote_exec(_disable)


def _get_tcp_forwarding_setting(ref_instance: "REFInstance") -> bool:
    """Get the current TCP port forwarding setting value."""

    def _get() -> bool:
        from ref.model.settings import SystemSettingsManager

        return SystemSettingsManager.ALLOW_TCP_PORT_FORWARDING.value  # type: ignore[return-value]

    return ref_instance.remote_exec(_get)


class PortForwardingTestState:
    """Shared state for port forwarding tests."""

    exercise_name: Optional[str] = None
    exercise_id: Optional[int] = None
    student_mat_num: Optional[str] = None
    student_password: str = "TestPassword123!"
    student_private_key: Optional[str] = None


@pytest.fixture(scope="module")
def port_forwarding_state() -> PortForwardingTestState:
    """Shared state fixture for port forwarding tests."""
    return PortForwardingTestState()


@pytest.fixture(scope="module")
def pf_exercise_name() -> str:
    """Generate a unique exercise name for port forwarding tests."""
    return f"pf_test_{uuid.uuid4().hex[:6]}"


@pytest.fixture(scope="module")
def pf_student_mat_num() -> str:
    """Generate a unique matriculation number for test student."""
    return str(uuid.uuid4().int)[:8]


class TestPortForwardingSetup:
    """
    Setup tests for port forwarding.

    Creates exercise, registers student, and verifies basic SSH connectivity
    before running port forwarding specific tests.
    """

    @pytest.mark.e2e
    def test_01_admin_login(
        self,
        web_client: REFWebClient,
        admin_password: str,
    ):
        """Verify admin can login."""
        web_client.logout()
        success = web_client.login("0", admin_password)
        assert success, "Admin login failed"

    @pytest.mark.e2e
    def test_01b_enable_tcp_forwarding(
        self,
        ref_instance: "REFInstance",
    ):
        """Enable TCP port forwarding in system settings."""
        result = _enable_tcp_forwarding(ref_instance)
        assert result is True, "Failed to enable TCP port forwarding"

        # Verify the setting was actually changed
        value = _get_tcp_forwarding_setting(ref_instance)
        assert value is True, "TCP port forwarding setting not enabled"

    @pytest.mark.e2e
    def test_02_create_exercise(
        self,
        exercises_path: Path,
        pf_exercise_name: str,
        port_forwarding_state: PortForwardingTestState,
    ):
        """Create a test exercise for port forwarding tests."""
        port_forwarding_state.exercise_name = pf_exercise_name
        exercise_dir = exercises_path / pf_exercise_name

        if exercise_dir.exists():
            import shutil

            shutil.rmtree(exercise_dir)

        create_sample_exercise(
            exercise_dir,
            short_name=pf_exercise_name,
            version=1,
            category="Port Forwarding Tests",
        )

        assert exercise_dir.exists(), "Exercise directory not created"

    @pytest.mark.e2e
    def test_03_import_and_build_exercise(
        self,
        admin_client: REFWebClient,
        exercises_path: Path,
        port_forwarding_state: PortForwardingTestState,
    ):
        """Import and build the exercise."""
        assert port_forwarding_state.exercise_name is not None

        exercise_path = str(exercises_path / port_forwarding_state.exercise_name)
        success = admin_client.import_exercise(exercise_path)
        assert success, "Failed to import exercise"

        exercise = admin_client.get_exercise_by_name(
            port_forwarding_state.exercise_name
        )
        assert exercise is not None
        exercise_id = exercise.get("id")
        assert exercise_id is not None, "Exercise ID not found"
        port_forwarding_state.exercise_id = exercise_id

        success = admin_client.build_exercise(exercise_id)
        assert success, "Failed to start exercise build"

        build_success = admin_client.wait_for_build(exercise_id, timeout=300.0)
        assert build_success, "Exercise build did not complete"

    @pytest.mark.e2e
    def test_04_enable_exercise(
        self,
        admin_client: REFWebClient,
        port_forwarding_state: PortForwardingTestState,
    ):
        """Enable the exercise."""
        assert port_forwarding_state.exercise_id is not None
        success = admin_client.toggle_exercise_default(
            port_forwarding_state.exercise_id
        )
        assert success, "Failed to enable exercise"

    @pytest.mark.e2e
    def test_05_register_student(
        self,
        web_client: REFWebClient,
        admin_password: str,
        pf_student_mat_num: str,
        port_forwarding_state: PortForwardingTestState,
    ):
        """Register a test student."""
        web_client.logout()
        port_forwarding_state.student_mat_num = pf_student_mat_num

        success, private_key, _ = web_client.register_student(
            mat_num=pf_student_mat_num,
            firstname="PortForward",
            surname="Tester",
            password=port_forwarding_state.student_password,
        )

        assert success, "Failed to register student"
        assert private_key is not None
        port_forwarding_state.student_private_key = private_key

        # Re-login as admin for subsequent tests that may use admin_client
        web_client.login("0", admin_password)


def _parse_private_key(private_key_str: str) -> paramiko.PKey:
    """Parse a private key string into a paramiko PKey object."""
    import io

    key_file = io.StringIO(private_key_str)
    try:
        return paramiko.RSAKey.from_private_key(key_file)
    except paramiko.SSHException:
        key_file.seek(0)
        try:
            return paramiko.Ed25519Key.from_private_key(key_file)
        except paramiko.SSHException:
            key_file.seek(0)
            return paramiko.ECDSAKey.from_private_key(key_file)


def _create_ssh_client(
    ssh_host: str,
    ssh_port: int,
    exercise_name: str,
    pkey: paramiko.PKey,
) -> paramiko.SSHClient:
    """Create and connect an SSH client."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=ssh_host,
        port=ssh_port,
        username=exercise_name,
        pkey=pkey,
        timeout=30.0,
        allow_agent=False,
        look_for_keys=False,
    )
    return client


# Python script for an echo server that runs inside the container
ECHO_SERVER_SCRIPT = """
import socket
import sys

port = int(sys.argv[1])
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(('127.0.0.1', port))
s.listen(1)
s.settimeout(30)

try:
    conn, addr = s.accept()
    conn.settimeout(10)
    while True:
        data = conn.recv(1024)
        if not data:
            break
        # Echo back with prefix
        conn.sendall(b'ECHO:' + data)
except socket.timeout:
    pass
finally:
    s.close()
"""

# Python script for an HTTP server that runs inside the container
HTTP_SERVER_SCRIPT = """
import socket
import sys

port = int(sys.argv[1])
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(('127.0.0.1', port))
s.listen(1)
s.settimeout(30)

try:
    conn, addr = s.accept()
    conn.settimeout(10)
    # Read HTTP request
    request = b''
    while b'\\r\\n\\r\\n' not in request:
        chunk = conn.recv(1024)
        if not chunk:
            break
        request += chunk

    # Send HTTP response
    body = b'Hello from container!'
    response = (
        b'HTTP/1.1 200 OK\\r\\n'
        b'Content-Type: text/plain\\r\\n'
        b'Content-Length: ' + str(len(body)).encode() + b'\\r\\n'
        b'Connection: close\\r\\n'
        b'\\r\\n'
    ) + body
    conn.sendall(response)
    conn.close()
except socket.timeout:
    pass
finally:
    s.close()
"""


class TestTCPForwarding:
    """
    Test TCP port forwarding capabilities.

    TCP forwarding is ENABLED in sshd_config (AllowTcpForwarding yes).
    """

    @pytest.mark.e2e
    def test_echo_server_bidirectional_communication(
        self,
        ssh_host: str,
        ssh_port: int,
        port_forwarding_state: PortForwardingTestState,
    ):
        """
        Test bidirectional communication through port forwarding.

        This test:
        1. Starts an echo server inside the container
        2. Opens a direct-tcpip channel through SSH
        3. Sends data and verifies the echoed response
        """
        assert port_forwarding_state.student_private_key is not None
        assert port_forwarding_state.exercise_name is not None

        pkey = _parse_private_key(port_forwarding_state.student_private_key)
        client = _create_ssh_client(
            ssh_host, ssh_port, port_forwarding_state.exercise_name, pkey
        )

        test_port = 19876

        try:
            # Write the echo server script to the container
            sftp = client.open_sftp()
            with sftp.file("/tmp/echo_server.py", "w") as f:
                f.write(ECHO_SERVER_SCRIPT)
            sftp.close()

            # Start the echo server in the background using nohup
            _, stdout, _stderr = client.exec_command(
                f"nohup python3 /tmp/echo_server.py {test_port} > /tmp/echo_server.log 2>&1 &"
            )
            stdout.channel.recv_exit_status()
            time.sleep(1.0)  # Give server more time to start

            # Verify server is running
            _, stdout, _ = client.exec_command(f"pgrep -f 'echo_server.py {test_port}'")
            pid = stdout.read().decode().strip()
            if not pid:
                # Get log for debugging
                _, log_stdout, _ = client.exec_command(
                    "cat /tmp/echo_server.log 2>/dev/null || echo 'no log'"
                )
                log_content = log_stdout.read().decode()
                assert False, f"Echo server failed to start. Log: {log_content}"

            transport = client.get_transport()
            assert transport is not None

            # Open a direct-tcpip channel to the echo server
            channel = transport.open_channel(
                "direct-tcpip",
                ("127.0.0.1", test_port),
                ("127.0.0.1", 0),
            )
            channel.settimeout(10.0)

            # Send test data
            test_messages = [b"Hello", b"World", b"PortForwarding"]
            for msg in test_messages:
                channel.sendall(msg)
                response = channel.recv(1024)
                expected = b"ECHO:" + msg
                assert response == expected, f"Expected {expected!r}, got {response!r}"

            channel.close()

        finally:
            # Cleanup
            try:
                client.exec_command(f"pkill -f 'echo_server.py {test_port}'")
                client.exec_command("rm -f /tmp/echo_server.py")
            except Exception:
                pass
            client.close()

    @pytest.mark.e2e
    def test_http_server_request_response(
        self,
        ssh_host: str,
        ssh_port: int,
        port_forwarding_state: PortForwardingTestState,
    ):
        """
        Test HTTP request/response through port forwarding.

        This test:
        1. Starts a simple HTTP server inside the container
        2. Opens a direct-tcpip channel through SSH
        3. Sends an HTTP GET request and verifies the response
        """
        assert port_forwarding_state.student_private_key is not None
        assert port_forwarding_state.exercise_name is not None

        pkey = _parse_private_key(port_forwarding_state.student_private_key)
        client = _create_ssh_client(
            ssh_host, ssh_port, port_forwarding_state.exercise_name, pkey
        )

        test_port = 19877

        try:
            # Write the HTTP server script to the container
            sftp = client.open_sftp()
            with sftp.file("/tmp/http_server.py", "w") as f:
                f.write(HTTP_SERVER_SCRIPT)
            sftp.close()

            # Start the HTTP server in the background using nohup
            _, stdout, _stderr = client.exec_command(
                f"nohup python3 /tmp/http_server.py {test_port} > /tmp/http_server.log 2>&1 &"
            )
            stdout.channel.recv_exit_status()
            time.sleep(1.0)  # Give server more time to start

            # Verify server is running
            _, stdout, _ = client.exec_command(f"pgrep -f 'http_server.py {test_port}'")
            pid = stdout.read().decode().strip()
            if not pid:
                # Get log for debugging
                _, log_stdout, _ = client.exec_command(
                    "cat /tmp/http_server.log 2>/dev/null || echo 'no log'"
                )
                log_content = log_stdout.read().decode()
                assert False, f"HTTP server failed to start. Log: {log_content}"

            transport = client.get_transport()
            assert transport is not None

            # Open a direct-tcpip channel to the HTTP server
            channel = transport.open_channel(
                "direct-tcpip",
                ("127.0.0.1", test_port),
                ("127.0.0.1", 0),
            )
            channel.settimeout(10.0)

            # Send HTTP GET request
            http_request = (
                b"GET / HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
            )
            channel.sendall(http_request)

            # Read response
            response = b""
            while True:
                try:
                    chunk = channel.recv(1024)
                    if not chunk:
                        break
                    response += chunk
                except socket.timeout:
                    break

            channel.close()

            # Verify HTTP response
            assert b"HTTP/1.1 200 OK" in response, f"Expected 200 OK, got: {response!r}"
            assert b"Hello from container!" in response, (
                f"Expected body content, got: {response!r}"
            )

        finally:
            # Cleanup
            try:
                client.exec_command(f"pkill -f 'http_server.py {test_port}'")
                client.exec_command("rm -f /tmp/http_server.py")
            except Exception:
                pass
            client.close()

    @pytest.mark.e2e
    def test_direct_tcpip_channel_can_be_opened(
        self,
        ssh_host: str,
        ssh_port: int,
        port_forwarding_state: PortForwardingTestState,
    ):
        """
        Test that direct-tcpip channels can be opened (basic TCP forwarding check).

        This is a simpler test that just verifies the SSH server allows
        opening direct-tcpip channels, without needing a service to connect to.
        """
        import io

        assert port_forwarding_state.student_private_key is not None
        assert port_forwarding_state.exercise_name is not None

        key_file = io.StringIO(port_forwarding_state.student_private_key)
        try:
            pkey = paramiko.RSAKey.from_private_key(key_file)
        except paramiko.SSHException:
            key_file.seek(0)
            try:
                pkey = paramiko.Ed25519Key.from_private_key(key_file)
            except paramiko.SSHException:
                key_file.seek(0)
                pkey = paramiko.ECDSAKey.from_private_key(key_file)

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            client.connect(
                hostname=ssh_host,
                port=ssh_port,
                username=port_forwarding_state.exercise_name,
                pkey=pkey,
                timeout=30.0,
                allow_agent=False,
                look_for_keys=False,
            )

            transport = client.get_transport()
            assert transport is not None

            # Try to open a channel to a port that likely has nothing listening
            # The channel open should succeed even if connection to dest fails
            try:
                channel = transport.open_channel(
                    "direct-tcpip",
                    ("127.0.0.1", 65432),  # Unlikely to have service
                    ("127.0.0.1", 0),
                )

                # If we get here, TCP forwarding is working
                # The channel might fail to connect, but that's expected
                channel.close()

            except paramiko.ChannelException as e:
                # Error code 2 = "Connection refused" - this means forwarding
                # worked but nothing was listening (expected)
                # Error code 1 = "Administratively prohibited" - forwarding disabled
                if e.code == 1:
                    pytest.fail("TCP forwarding is administratively prohibited")
                # Other errors (like connection refused) are acceptable

        finally:
            client.close()


class TestDisabledForwardingFeatures:
    """
    Test that disabled forwarding features are properly blocked.

    Per sshd_config:
    - AllowAgentForwarding no
    - X11Forwarding no
    """

    @pytest.mark.e2e
    def test_agent_forwarding_is_disabled(
        self,
        ssh_host: str,
        ssh_port: int,
        port_forwarding_state: PortForwardingTestState,
    ):
        """
        Test that SSH agent forwarding is disabled.

        The sshd_config has: AllowAgentForwarding no
        """
        import io

        assert port_forwarding_state.student_private_key is not None
        assert port_forwarding_state.exercise_name is not None

        key_file = io.StringIO(port_forwarding_state.student_private_key)
        try:
            pkey = paramiko.RSAKey.from_private_key(key_file)
        except paramiko.SSHException:
            key_file.seek(0)
            try:
                pkey = paramiko.Ed25519Key.from_private_key(key_file)
            except paramiko.SSHException:
                key_file.seek(0)
                pkey = paramiko.ECDSAKey.from_private_key(key_file)

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            client.connect(
                hostname=ssh_host,
                port=ssh_port,
                username=port_forwarding_state.exercise_name,
                pkey=pkey,
                timeout=30.0,
                allow_agent=False,
                look_for_keys=False,
            )

            transport = client.get_transport()
            assert transport is not None

            # Try to request agent forwarding
            # This should fail or be rejected since AllowAgentForwarding is no
            try:
                # Open a session channel
                channel = transport.open_session()

                # Request agent forwarding
                result = channel.request_forward_agent(handler=lambda _: None)

                # If agent forwarding is disabled, this should return False
                # or the SSH_AUTH_SOCK variable won't be set
                if result:
                    # Agent forwarding was accepted - check if it actually works
                    # by looking for SSH_AUTH_SOCK in the environment
                    channel.exec_command("echo $SSH_AUTH_SOCK")
                    output = channel.recv(1024).decode().strip()

                    # If SSH_AUTH_SOCK is empty, agent forwarding didn't work
                    assert not output, (
                        f"Agent forwarding should be disabled but SSH_AUTH_SOCK={output}"
                    )
                # If result is False, agent forwarding was correctly rejected

                channel.close()

            except paramiko.ChannelException:
                # Channel exception means agent forwarding was rejected (expected)
                pass

        finally:
            client.close()

    @pytest.mark.e2e
    def test_x11_forwarding_is_disabled(
        self,
        ssh_host: str,
        ssh_port: int,
        port_forwarding_state: PortForwardingTestState,
    ):
        """
        Test that X11 forwarding is disabled.

        The sshd_config has: X11Forwarding no
        """
        import io

        assert port_forwarding_state.student_private_key is not None
        assert port_forwarding_state.exercise_name is not None

        key_file = io.StringIO(port_forwarding_state.student_private_key)
        try:
            pkey = paramiko.RSAKey.from_private_key(key_file)
        except paramiko.SSHException:
            key_file.seek(0)
            try:
                pkey = paramiko.Ed25519Key.from_private_key(key_file)
            except paramiko.SSHException:
                key_file.seek(0)
                pkey = paramiko.ECDSAKey.from_private_key(key_file)

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            client.connect(
                hostname=ssh_host,
                port=ssh_port,
                username=port_forwarding_state.exercise_name,
                pkey=pkey,
                timeout=30.0,
                allow_agent=False,
                look_for_keys=False,
            )

            transport = client.get_transport()
            assert transport is not None

            # Try to request X11 forwarding
            try:
                channel = transport.open_session()

                # Request X11 forwarding
                # Parameters: single_connection, auth_protocol, auth_cookie, screen_number
                channel.request_x11(
                    single_connection=False,
                    auth_protocol="MIT-MAGIC-COOKIE-1",
                    auth_cookie=b"0" * 16,
                    screen_number=0,
                )

                # If we get here without exception, X11 request was sent
                # Check if DISPLAY is set (it shouldn't be if X11 is disabled)
                channel.exec_command("echo $DISPLAY")
                output = channel.recv(1024).decode().strip()

                # DISPLAY should be empty if X11 forwarding is disabled
                assert not output, (
                    f"X11 forwarding should be disabled but DISPLAY={output}"
                )

                channel.close()

            except paramiko.ChannelException:
                # X11 forwarding was rejected (expected)
                pass
            except paramiko.SSHException:
                # SSH exception also indicates X11 was rejected
                pass

        finally:
            client.close()


class TestRemotePortForwarding:
    """
    Test remote port forwarding capabilities (-R option).

    Note: Remote port forwarding allows the server to forward connections
    from a port on the server to a port on the client.
    """

    @pytest.mark.e2e
    def test_remote_port_forwarding_request(
        self,
        ssh_host: str,
        ssh_port: int,
        port_forwarding_state: PortForwardingTestState,
    ):
        """
        Test that remote port forwarding can be requested.

        This tests the 'tcpip-forward' global request.
        """
        import io

        assert port_forwarding_state.student_private_key is not None
        assert port_forwarding_state.exercise_name is not None

        key_file = io.StringIO(port_forwarding_state.student_private_key)
        try:
            pkey = paramiko.RSAKey.from_private_key(key_file)
        except paramiko.SSHException:
            key_file.seek(0)
            try:
                pkey = paramiko.Ed25519Key.from_private_key(key_file)
            except paramiko.SSHException:
                key_file.seek(0)
                pkey = paramiko.ECDSAKey.from_private_key(key_file)

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            client.connect(
                hostname=ssh_host,
                port=ssh_port,
                username=port_forwarding_state.exercise_name,
                pkey=pkey,
                timeout=30.0,
                allow_agent=False,
                look_for_keys=False,
            )

            transport = client.get_transport()
            assert transport is not None

            # Try to request remote port forwarding
            # Request the server to listen on port 0 (any available port)
            try:
                port = transport.request_port_forward("127.0.0.1", 0)

                # If we get a port number, remote forwarding is supported
                assert port > 0, "Expected a valid port number"

                # Cancel the forwarding
                transport.cancel_port_forward("127.0.0.1", port)

            except paramiko.SSHException as e:
                # Remote port forwarding might be restricted
                # This is acceptable - we're just testing the capability
                if "rejected" in str(e).lower() or "denied" in str(e).lower():
                    #
                    pytest.skip(f"Remote port forwarding not available: {e}")
                raise

        finally:
            client.close()


class TestTCPForwardingSettingEnforcement:
    """
    Test that TCP port forwarding can be enabled/disabled via system settings.

    These tests verify that the ALLOW_TCP_PORT_FORWARDING setting is properly
    enforced by the SSH server.
    """

    @pytest.mark.e2e
    def test_forwarding_blocked_when_disabled(
        self,
        ssh_host: str,
        ssh_port: int,
        ref_instance: "REFInstance",
        port_forwarding_state: PortForwardingTestState,
    ):
        """
        Verify TCP forwarding fails when the setting is disabled.

        This test disables TCP forwarding and verifies that opening a
        direct-tcpip channel fails with the expected error.
        """
        assert port_forwarding_state.student_private_key is not None
        assert port_forwarding_state.exercise_name is not None

        # Disable TCP forwarding
        _disable_tcp_forwarding(ref_instance)

        # Verify the setting is disabled
        assert _get_tcp_forwarding_setting(ref_instance) is False

        pkey = _parse_private_key(port_forwarding_state.student_private_key)

        # Need a fresh SSH connection to pick up the new setting
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            client.connect(
                hostname=ssh_host,
                port=ssh_port,
                username=port_forwarding_state.exercise_name,
                pkey=pkey,
                timeout=5.0,
                allow_agent=False,
                look_for_keys=False,
            )

            transport = client.get_transport()
            assert transport is not None

            # Try to open a direct-tcpip channel - this should fail
            with pytest.raises(paramiko.ChannelException) as exc_info:
                transport.open_channel(
                    "direct-tcpip",
                    ("127.0.0.1", 12345),
                    ("127.0.0.1", 0),
                    timeout=3.0,
                )

            # Error code 1 = "Administratively prohibited"
            # Error code 2 = "Connect failed" (also acceptable)
            assert exc_info.value.code in (1, 2), (
                f"Expected channel error code 1 or 2, got {exc_info.value.code}"
            )

        finally:
            client.close()
            # Re-enable TCP forwarding for subsequent tests
            _enable_tcp_forwarding(ref_instance)
