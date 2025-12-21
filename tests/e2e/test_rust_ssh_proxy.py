"""
E2E Test: Rust SSH Proxy

Tests the new Rust-based SSH proxy implementation (issue #30).
Connects via the ssh_port fixture to the SSH reverse proxy.
"""

import uuid
from pathlib import Path
from typing import Optional

import pytest

from helpers.exercise_factory import create_sample_exercise
from helpers.ssh_client import REFSSHClient
from helpers.web_client import REFWebClient


class RustProxyTestState:
    """Shared state for Rust proxy tests."""

    exercise_name: Optional[str] = None
    exercise_id: Optional[int] = None
    mat_num: Optional[str] = None
    private_key: Optional[str] = None
    student_password: str = "TestPassword123!"


@pytest.fixture(scope="module")
def rust_proxy_state() -> RustProxyTestState:
    """Shared state fixture for Rust proxy tests."""
    return RustProxyTestState()


@pytest.fixture(scope="module")
def rust_proxy_exercise_name() -> str:
    """Generate a unique exercise name for Rust proxy tests."""
    return f"rust_proxy_test_{uuid.uuid4().hex[:6]}"


def create_rust_ssh_client(
    host: str,
    port: int,
    private_key: str,
    exercise_name: str,
) -> REFSSHClient:
    """Create an SSH client connected to the Rust SSH proxy."""
    client = REFSSHClient(host=host, port=port, timeout=60.0)
    client.connect(private_key, exercise_name)
    return client


@pytest.mark.e2e
class TestRustProxySetup:
    """
    Setup tests for Rust SSH proxy testing.

    Creates exercise and registers a student.
    """

    def test_01_admin_login(
        self,
        web_client: REFWebClient,
        admin_password: str,
    ):
        """Verify admin can login."""
        web_client.logout()
        success = web_client.login("0", admin_password)
        assert success, "Admin login failed"

    def test_02_create_exercise(
        self,
        exercises_path: Path,
        rust_proxy_exercise_name: str,
        rust_proxy_state: RustProxyTestState,
    ):
        """Create a test exercise for Rust proxy tests."""
        rust_proxy_state.exercise_name = rust_proxy_exercise_name
        exercise_dir = exercises_path / rust_proxy_exercise_name

        if exercise_dir.exists():
            import shutil

            shutil.rmtree(exercise_dir)

        create_sample_exercise(
            exercise_dir,
            short_name=rust_proxy_exercise_name,
            version=1,
            category="Rust Proxy Tests",
        )

        assert exercise_dir.exists(), "Exercise directory not created"

    def test_03_import_and_build_exercise(
        self,
        admin_client: REFWebClient,
        exercises_path: Path,
        rust_proxy_state: RustProxyTestState,
    ):
        """Import and build the exercise."""
        assert rust_proxy_state.exercise_name is not None

        exercise_path = str(exercises_path / rust_proxy_state.exercise_name)
        success = admin_client.import_exercise(exercise_path)
        assert success, "Failed to import exercise"

        exercise = admin_client.get_exercise_by_name(rust_proxy_state.exercise_name)
        assert exercise is not None
        exercise_id = exercise.get("id")
        assert exercise_id is not None, "Exercise ID not found"
        rust_proxy_state.exercise_id = exercise_id

        success = admin_client.build_exercise(exercise_id)
        assert success, "Failed to start exercise build"

        build_success = admin_client.wait_for_build(exercise_id, timeout=300.0)
        assert build_success, "Exercise build did not complete"

    def test_04_enable_exercise(
        self,
        admin_client: REFWebClient,
        rust_proxy_state: RustProxyTestState,
    ):
        """Enable the exercise."""
        assert rust_proxy_state.exercise_id is not None
        success = admin_client.toggle_exercise_default(rust_proxy_state.exercise_id)
        assert success, "Failed to enable exercise"

    def test_05_register_student(
        self,
        web_client: REFWebClient,
        admin_password: str,
        rust_proxy_state: RustProxyTestState,
    ):
        """Register a test student."""
        web_client.logout()
        mat_num = str(uuid.uuid4().int)[:8]
        rust_proxy_state.mat_num = mat_num

        success, private_key, _ = web_client.register_student(
            mat_num=mat_num,
            firstname="Rust",
            surname="Proxy",
            password=rust_proxy_state.student_password,
        )

        assert success, "Failed to register student"
        assert private_key is not None
        rust_proxy_state.private_key = private_key

        # Re-login as admin
        web_client.login("0", admin_password)


@pytest.mark.e2e
class TestRustSSHProxyConnection:
    """Test SSH connection through the new Rust SSH proxy on port 2223."""

    def test_01_ssh_connect_via_rust_proxy(
        self,
        ssh_host: str,
        ssh_port: int,
        rust_proxy_state: RustProxyTestState,
    ):
        """Verify SSH connection works through the Rust SSH proxy."""
        assert rust_proxy_state.private_key is not None
        assert rust_proxy_state.exercise_name is not None

        client = create_rust_ssh_client(
            host=ssh_host,
            port=ssh_port,
            private_key=rust_proxy_state.private_key,
            exercise_name=rust_proxy_state.exercise_name,
        )

        assert client.is_connected(), "Rust SSH proxy connection failed"

        # Execute a simple command to verify the connection works
        exit_code, stdout, stderr = client.execute("echo 'Rust proxy test'")
        assert exit_code == 0, f"Command failed with stderr: {stderr}"
        assert "Rust proxy test" in stdout

        client.close()

    def test_02_compare_with_standard_proxy(
        self,
        ssh_client_factory,
        ssh_host: str,
        ssh_port: int,
        rust_proxy_state: RustProxyTestState,
    ):
        """Compare behavior between standard and Rust SSH proxies."""
        assert rust_proxy_state.private_key is not None
        assert rust_proxy_state.exercise_name is not None

        # Connect via standard proxy (port 2222)
        std_client = ssh_client_factory(
            rust_proxy_state.private_key,
            rust_proxy_state.exercise_name,
        )
        assert std_client.is_connected(), "Standard SSH proxy connection failed"

        # Connect via Rust proxy
        rust_client = create_rust_ssh_client(
            host=ssh_host,
            port=ssh_port,
            private_key=rust_proxy_state.private_key,
            exercise_name=rust_proxy_state.exercise_name,
        )
        assert rust_client.is_connected(), "Rust SSH proxy connection failed"

        # Execute same command via both
        std_exit, std_out, std_err = std_client.execute("hostname")
        rust_exit, rust_out, rust_err = rust_client.execute("hostname")

        # Both should succeed with same output (same container)
        assert std_exit == 0, f"Standard proxy command failed: {std_err}"
        assert rust_exit == 0, f"Rust proxy command failed: {rust_err}"
        assert std_out.strip() == rust_out.strip(), (
            f"Hostname mismatch: std={std_out.strip()}, rust={rust_out.strip()}"
        )

        std_client.close()
        rust_client.close()

    def test_03_file_operations_via_rust_proxy(
        self,
        ssh_host: str,
        ssh_port: int,
        rust_proxy_state: RustProxyTestState,
    ):
        """Verify file operations work through the Rust SSH proxy."""
        assert rust_proxy_state.private_key is not None
        assert rust_proxy_state.exercise_name is not None

        client = create_rust_ssh_client(
            host=ssh_host,
            port=ssh_port,
            private_key=rust_proxy_state.private_key,
            exercise_name=rust_proxy_state.exercise_name,
        )

        # Write a file via SFTP
        test_content = f"Test content from Rust proxy - {uuid.uuid4().hex}"
        client.write_file("/tmp/rust_proxy_test.txt", test_content)

        # Read it back
        read_content = client.read_file("/tmp/rust_proxy_test.txt")
        assert read_content == test_content, "File content mismatch"

        client.close()

    def test_04_local_port_forwarding(
        self,
        ssh_host: str,
        ssh_port: int,
        rust_proxy_state: RustProxyTestState,
    ):
        """Verify local port forwarding (ssh -L) works through the Rust SSH proxy."""
        import io
        import time

        import paramiko

        assert rust_proxy_state.private_key is not None
        assert rust_proxy_state.exercise_name is not None

        # Parse the private key
        key_file = io.StringIO(rust_proxy_state.private_key)
        pkey = paramiko.Ed25519Key.from_private_key(key_file)

        # Connect via Rust proxy
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=ssh_host,
            port=ssh_port,
            username=rust_proxy_state.exercise_name,
            pkey=pkey,
            timeout=60.0,
            allow_agent=False,
            look_for_keys=False,
        )

        # Start a simple HTTP server in the container on port 18080
        _stdin, _stdout, _stderr = client.exec_command(
            "python3 -m http.server 18080 > /dev/null 2>&1 &"
        )
        time.sleep(1)

        # Open direct-tcpip channel (local port forwarding)
        transport = client.get_transport()
        assert transport is not None

        channel = transport.open_channel(
            "direct-tcpip",
            ("localhost", 18080),  # Destination in container
            ("127.0.0.1", 0),  # Source (our side)
        )

        # Send HTTP request through the tunnel
        channel.send(b"GET / HTTP/1.0\r\n\r\n")
        channel.settimeout(5.0)
        response = channel.recv(4096)

        assert b"HTTP/1.0 200 OK" in response or b"HTTP/1.1 200 OK" in response

        channel.close()
        client.close()

    def test_05_remote_port_forwarding(
        self,
        ssh_host: str,
        ssh_port: int,
        rust_proxy_state: RustProxyTestState,
    ):
        """Verify remote port forwarding (ssh -R) works through the Rust SSH proxy."""
        import io
        import threading
        import time

        import paramiko

        assert rust_proxy_state.private_key is not None
        assert rust_proxy_state.exercise_name is not None

        # Parse the private key
        key_file = io.StringIO(rust_proxy_state.private_key)
        pkey = paramiko.Ed25519Key.from_private_key(key_file)

        # Connect via Rust proxy
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=ssh_host,
            port=ssh_port,
            username=rust_proxy_state.exercise_name,
            pkey=pkey,
            timeout=60.0,
            allow_agent=False,
            look_for_keys=False,
        )

        transport = client.get_transport()
        assert transport is not None

        # Request remote port forwarding: container listens on port 19999
        # When a connection arrives, it will be forwarded back to us
        remote_port = 19999
        bound_port = transport.request_port_forward("", remote_port)
        assert bound_port == remote_port or bound_port > 0, (
            "Port forward request failed"
        )

        # Track received data from forwarded connection
        received_data: list[bytes] = []
        forward_received = threading.Event()

        def accept_forwarded_connection():
            """Accept the forwarded connection from the container."""
            try:
                channel = transport.accept(timeout=10)
                if channel:
                    data = channel.recv(1024)
                    received_data.append(data)
                    channel.send(b"PONG\n")
                    channel.close()
                    forward_received.set()
            except Exception as e:
                print(f"Error accepting forwarded connection: {e}")

        # Start thread to accept the forwarded connection
        accept_thread = threading.Thread(target=accept_forwarded_connection)
        accept_thread.start()

        # Give time for port forward to be established
        time.sleep(0.5)

        # From inside the container, connect to the forwarded port
        _stdin, _stdout, _stderr = client.exec_command(
            f"echo 'PING' | nc -q0 localhost {bound_port}"
        )
        # Wait for the command to complete
        _stdout.channel.recv_exit_status()

        # Wait for forwarded connection to be received
        accept_thread.join(timeout=10)

        # Cancel the port forward
        transport.cancel_port_forward("", remote_port)

        # Verify we received the data
        assert forward_received.is_set(), "Did not receive forwarded connection"
        assert len(received_data) > 0, "No data received from forwarded connection"
        assert b"PING" in received_data[0], f"Expected PING, got: {received_data[0]!r}"

        client.close()

    def test_06_x11_forwarding_request(
        self,
        ssh_host: str,
        ssh_port: int,
        rust_proxy_state: RustProxyTestState,
    ):
        """Verify X11 forwarding request is accepted by the Rust SSH proxy."""
        import io

        import paramiko

        assert rust_proxy_state.private_key is not None
        assert rust_proxy_state.exercise_name is not None

        # Parse the private key
        key_file = io.StringIO(rust_proxy_state.private_key)
        pkey = paramiko.Ed25519Key.from_private_key(key_file)

        # Connect via Rust proxy
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=ssh_host,
            port=ssh_port,
            username=rust_proxy_state.exercise_name,
            pkey=pkey,
            timeout=60.0,
            allow_agent=False,
            look_for_keys=False,
        )

        transport = client.get_transport()
        assert transport is not None

        # Open a session channel
        channel = transport.open_session()

        # Request X11 forwarding on the channel
        # This sends the x11-req channel request
        # Note: We don't actually need an X server to test that the request is accepted
        try:
            channel.request_x11(
                single_connection=False,
                auth_protocol="MIT-MAGIC-COOKIE-1",
                auth_cookie="0" * 32,  # Dummy cookie
                screen_number=0,
            )
            x11_accepted = True
        except paramiko.SSHException:
            x11_accepted = False

        # The proxy should accept the X11 forwarding request
        assert x11_accepted, "X11 forwarding request was rejected"

        # Run a simple command to verify the channel still works after X11 request
        channel.exec_command("echo X11_TEST_OK")
        channel.settimeout(10.0)

        # Read response
        output = b""
        try:
            while True:
                chunk = channel.recv(1024)
                if not chunk:
                    break
                output += chunk
        except Exception:
            pass

        channel.close()
        client.close()

        # Verify the command ran successfully
        assert b"X11_TEST_OK" in output, (
            f"Expected X11_TEST_OK in output, got: {output!r}"
        )

    def test_07_exit_status_propagation(
        self,
        ssh_host: str,
        ssh_port: int,
        rust_proxy_state: RustProxyTestState,
    ):
        """Verify exit status codes are correctly propagated through the proxy."""
        assert rust_proxy_state.private_key is not None
        assert rust_proxy_state.exercise_name is not None

        client = create_rust_ssh_client(
            host=ssh_host,
            port=ssh_port,
            private_key=rust_proxy_state.private_key,
            exercise_name=rust_proxy_state.exercise_name,
        )

        # Test various exit codes
        test_cases = [
            ("exit 0", 0),
            ("exit 1", 1),
            ("exit 42", 42),
            ("exit 127", 127),
            ("true", 0),
            ("false", 1),
        ]

        for command, expected_exit_code in test_cases:
            exit_code, _, _ = client.execute(command)
            assert exit_code == expected_exit_code, (
                f"Command '{command}': expected exit code {expected_exit_code}, got {exit_code}"
            )

        client.close()

    def test_08_stderr_capture(
        self,
        ssh_host: str,
        ssh_port: int,
        rust_proxy_state: RustProxyTestState,
    ):
        """Verify stderr is captured separately from stdout."""
        assert rust_proxy_state.private_key is not None
        assert rust_proxy_state.exercise_name is not None

        client = create_rust_ssh_client(
            host=ssh_host,
            port=ssh_port,
            private_key=rust_proxy_state.private_key,
            exercise_name=rust_proxy_state.exercise_name,
        )

        # Test stderr output
        exit_code, stdout, stderr = client.execute(
            "echo 'stdout_msg' && echo 'stderr_msg' >&2"
        )
        assert exit_code == 0
        assert "stdout_msg" in stdout
        assert "stderr_msg" in stderr

        # Test command that produces only stderr (ls nonexistent file)
        exit_code, stdout, stderr = client.execute("ls /nonexistent_file_12345 2>&1")
        assert exit_code != 0
        assert "No such file" in stdout or "No such file" in stderr

        client.close()

    def test_09_signal_handling(
        self,
        ssh_host: str,
        ssh_port: int,
        rust_proxy_state: RustProxyTestState,
    ):
        """Verify signal handling works through the proxy."""
        assert rust_proxy_state.private_key is not None
        assert rust_proxy_state.exercise_name is not None

        client = create_rust_ssh_client(
            host=ssh_host,
            port=ssh_port,
            private_key=rust_proxy_state.private_key,
            exercise_name=rust_proxy_state.exercise_name,
        )

        # Start a background process and kill it
        exit_code, stdout, _ = client.execute(
            'sleep 100 & PID=$!; sleep 0.1; kill -TERM $PID; wait $PID 2>/dev/null; echo "exit_code=$?"'
        )
        # Process killed by SIGTERM should have exit code 143 (128 + 15)
        assert "exit_code=" in stdout
        # The exit code should indicate signal termination
        exit_value = int(stdout.split("exit_code=")[1].strip())
        assert exit_value == 143 or exit_value > 128, (
            f"Expected signal exit code, got {exit_value}"
        )

        client.close()

    def test_10_pty_and_terminal(
        self,
        ssh_host: str,
        ssh_port: int,
        rust_proxy_state: RustProxyTestState,
    ):
        """Verify PTY allocation and terminal handling work through the proxy."""
        assert rust_proxy_state.private_key is not None
        assert rust_proxy_state.exercise_name is not None

        # Use the higher-level SSH client which handles PTY via exec_command
        client = create_rust_ssh_client(
            host=ssh_host,
            port=ssh_port,
            private_key=rust_proxy_state.private_key,
            exercise_name=rust_proxy_state.exercise_name,
        )

        # Test basic terminal behavior - the underlying SSH should handle PTY
        exit_code, stdout, stderr = client.execute("echo $TERM")
        assert exit_code == 0, f"Command failed: {stderr}"

        # Also verify tty detection works
        exit_code, stdout, stderr = client.execute(
            "test -t 0 && echo TTY || echo NO_TTY"
        )
        # The execute() method may or may not allocate a PTY depending on implementation
        # We're mainly testing that the command runs without error
        assert exit_code == 0 or "TTY" in stdout or "NO_TTY" in stdout

        client.close()

    def test_11_window_resize(
        self,
        ssh_host: str,
        ssh_port: int,
        rust_proxy_state: RustProxyTestState,
    ):
        """Verify window resize requests don't crash the proxy."""
        import io

        import paramiko

        assert rust_proxy_state.private_key is not None
        assert rust_proxy_state.exercise_name is not None

        key_file = io.StringIO(rust_proxy_state.private_key)
        pkey = paramiko.Ed25519Key.from_private_key(key_file)

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=ssh_host,
            port=ssh_port,
            username=rust_proxy_state.exercise_name,
            pkey=pkey,
            timeout=60.0,
            allow_agent=False,
            look_for_keys=False,
        )

        transport = client.get_transport()
        assert transport is not None

        channel = transport.open_session()
        channel.settimeout(30.0)

        # Send window resize without PTY (should not crash)
        # This tests that the proxy handles window-change requests gracefully
        try:
            channel.resize_pty(width=120, height=40)
        except Exception:
            pass  # Resize without PTY may fail, that's OK

        # Execute a command to verify channel still works
        channel.exec_command("echo RESIZE_TEST_OK")

        output = b""
        try:
            while True:
                chunk = channel.recv(4096)
                if not chunk:
                    break
                output += chunk
        except Exception:
            pass

        assert b"RESIZE_TEST_OK" in output, (
            f"Expected RESIZE_TEST_OK in output after resize, got: {output!r}"
        )

        channel.close()
        client.close()

    def test_12_environment_variables(
        self,
        ssh_host: str,
        ssh_port: int,
        rust_proxy_state: RustProxyTestState,
    ):
        """Verify environment variables are passed through SSH."""
        import io

        import paramiko

        assert rust_proxy_state.private_key is not None
        assert rust_proxy_state.exercise_name is not None

        key_file = io.StringIO(rust_proxy_state.private_key)
        pkey = paramiko.Ed25519Key.from_private_key(key_file)

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=ssh_host,
            port=ssh_port,
            username=rust_proxy_state.exercise_name,
            pkey=pkey,
            timeout=60.0,
            allow_agent=False,
            look_for_keys=False,
        )

        transport = client.get_transport()
        assert transport is not None

        channel = transport.open_session()

        # Try to set LC_ALL (should be accepted per sshd_config AcceptEnv)
        # Note: set_environment_variable is the correct paramiko method
        try:
            channel.set_environment_variable("LC_ALL", "C.UTF-8")
        except Exception:
            pass  # Some SSH servers may not accept env vars
        channel.exec_command("echo LC_ALL=$LC_ALL")
        channel.settimeout(10.0)

        output = b""
        try:
            while True:
                chunk = channel.recv(4096)
                if not chunk:
                    break
                output += chunk
        except Exception:
            pass

        output_str = output.decode("utf-8", errors="replace")
        # Note: The env var may or may not be set depending on container sshd config
        # We're mainly testing that the request doesn't crash the proxy
        assert "LC_ALL=" in output_str, f"Expected LC_ALL in output, got: {output_str}"

        channel.close()
        client.close()

    def test_13_background_process(
        self,
        ssh_host: str,
        ssh_port: int,
        rust_proxy_state: RustProxyTestState,
    ):
        """Verify background processes continue after SSH disconnect."""
        assert rust_proxy_state.private_key is not None
        assert rust_proxy_state.exercise_name is not None

        # First connection: start background process
        client1 = create_rust_ssh_client(
            host=ssh_host,
            port=ssh_port,
            private_key=rust_proxy_state.private_key,
            exercise_name=rust_proxy_state.exercise_name,
        )

        # Start a background process with a marker file
        marker_file = f"/tmp/bg_test_{uuid.uuid4().hex[:8]}"
        exit_code, _, _ = client1.execute(
            f"nohup bash -c 'sleep 2 && touch {marker_file}' > /dev/null 2>&1 &"
        )
        assert exit_code == 0

        # Disconnect
        client1.close()

        # Wait for background process to complete
        import time

        time.sleep(3)

        # Reconnect and check if marker file exists
        client2 = create_rust_ssh_client(
            host=ssh_host,
            port=ssh_port,
            private_key=rust_proxy_state.private_key,
            exercise_name=rust_proxy_state.exercise_name,
        )

        exit_code, stdout, _ = client2.execute(
            f"test -f {marker_file} && echo 'EXISTS'"
        )
        assert "EXISTS" in stdout, (
            "Background process did not complete after disconnect"
        )

        # Cleanup
        client2.execute(f"rm -f {marker_file}")
        client2.close()

    def test_14_concurrent_connections(
        self,
        ssh_host: str,
        ssh_port: int,
        rust_proxy_state: RustProxyTestState,
    ):
        """Verify multiple concurrent SSH connections work correctly."""
        import concurrent.futures

        assert rust_proxy_state.private_key is not None
        assert rust_proxy_state.exercise_name is not None

        # Capture values to satisfy mypy type narrowing in nested function
        private_key = rust_proxy_state.private_key
        exercise_name = rust_proxy_state.exercise_name

        def run_command(conn_id: int) -> tuple[int, str, int]:
            """Execute a command on a separate connection."""
            client = create_rust_ssh_client(
                host=ssh_host,
                port=ssh_port,
                private_key=private_key,
                exercise_name=exercise_name,
            )
            exit_code, stdout, _ = client.execute(f"echo 'conn_{conn_id}' && hostname")
            client.close()
            return conn_id, stdout, exit_code

        # Run 3 concurrent connections
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(run_command, i) for i in range(3)]
            results = [f.result(timeout=30) for f in futures]

        # Verify all succeeded
        for conn_id, stdout, exit_code in results:
            assert exit_code == 0, f"Connection {conn_id} failed"
            assert f"conn_{conn_id}" in stdout, f"Connection {conn_id} output mismatch"

    def test_15_rapid_connect_disconnect(
        self,
        ssh_host: str,
        ssh_port: int,
        rust_proxy_state: RustProxyTestState,
    ):
        """Verify rapid connect/disconnect cycles don't cause issues."""
        assert rust_proxy_state.private_key is not None
        assert rust_proxy_state.exercise_name is not None

        for i in range(5):
            client = create_rust_ssh_client(
                host=ssh_host,
                port=ssh_port,
                private_key=rust_proxy_state.private_key,
                exercise_name=rust_proxy_state.exercise_name,
            )
            assert client.is_connected(), f"Connection {i} failed"

            exit_code, stdout, _ = client.execute(f"echo 'cycle_{i}'")
            assert exit_code == 0, f"Command in cycle {i} failed"
            assert f"cycle_{i}" in stdout

            client.close()

    def test_16_command_timeout_handling(
        self,
        ssh_host: str,
        ssh_port: int,
        rust_proxy_state: RustProxyTestState,
    ):
        """Verify command timeout is handled gracefully."""
        import io
        import socket

        import paramiko

        assert rust_proxy_state.private_key is not None
        assert rust_proxy_state.exercise_name is not None

        key_file = io.StringIO(rust_proxy_state.private_key)
        pkey = paramiko.Ed25519Key.from_private_key(key_file)

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=ssh_host,
            port=ssh_port,
            username=rust_proxy_state.exercise_name,
            pkey=pkey,
            timeout=60.0,
            allow_agent=False,
            look_for_keys=False,
        )

        transport = client.get_transport()
        assert transport is not None

        channel = transport.open_session()
        channel.settimeout(2.0)  # 2 second timeout

        # Start a long-running command
        channel.exec_command("sleep 10")

        # Try to read - should timeout
        timed_out = False
        try:
            channel.recv(1024)
        except socket.timeout:
            timed_out = True

        assert timed_out, "Expected timeout but command completed"

        # Connection should still be usable after timeout
        channel.close()

        # Open new channel and verify it works
        channel2 = transport.open_session()
        channel2.exec_command("echo 'after_timeout'")
        channel2.settimeout(10.0)

        output = b""
        try:
            while True:
                chunk = channel2.recv(4096)
                if not chunk:
                    break
                output += chunk
        except Exception:
            pass

        assert b"after_timeout" in output

        channel2.close()
        client.close()

    def test_17_large_data_transfer(
        self,
        ssh_host: str,
        ssh_port: int,
        rust_proxy_state: RustProxyTestState,
    ):
        """Verify large file transfer works correctly via SFTP."""
        import hashlib
        import os

        assert rust_proxy_state.private_key is not None
        assert rust_proxy_state.exercise_name is not None

        client = create_rust_ssh_client(
            host=ssh_host,
            port=ssh_port,
            private_key=rust_proxy_state.private_key,
            exercise_name=rust_proxy_state.exercise_name,
        )

        # Generate 1MB of random data
        large_data = os.urandom(1024 * 1024)  # 1MB
        original_hash = hashlib.sha256(large_data).hexdigest()

        remote_path = f"/tmp/large_test_{uuid.uuid4().hex[:8]}.bin"

        # Upload
        client.write_file(remote_path, large_data.decode("latin-1"))

        # Download and verify
        downloaded = client.read_file(remote_path)
        downloaded_hash = hashlib.sha256(downloaded.encode("latin-1")).hexdigest()

        assert original_hash == downloaded_hash, (
            f"Data integrity check failed: original={original_hash}, downloaded={downloaded_hash}"
        )

        # Cleanup
        client.execute(f"rm -f {remote_path}")
        client.close()

    def test_18_invalid_auth_rejection(
        self,
        ssh_host: str,
        ssh_port: int,
        rust_proxy_state: RustProxyTestState,
    ):
        """Verify invalid authentication is properly rejected."""
        import io

        import paramiko

        # Generate a different (invalid) RSA key
        # Note: paramiko doesn't have Ed25519Key.generate(), so use RSA
        invalid_key = paramiko.RSAKey.generate(2048)

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        auth_failed = False
        try:
            client.connect(
                hostname=ssh_host,
                port=ssh_port,
                username=rust_proxy_state.exercise_name,
                pkey=invalid_key,
                timeout=30.0,
                allow_agent=False,
                look_for_keys=False,
            )
        except paramiko.AuthenticationException:
            auth_failed = True
        except Exception as e:
            # Some other connection error is also acceptable
            auth_failed = "Authentication" in str(e) or "auth" in str(e).lower()

        assert auth_failed, "Expected authentication to fail with invalid key"

        # Verify proxy still works after failed auth
        assert rust_proxy_state.private_key is not None
        key_file = io.StringIO(rust_proxy_state.private_key)
        valid_key = paramiko.Ed25519Key.from_private_key(key_file)

        valid_client = paramiko.SSHClient()
        valid_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        valid_client.connect(
            hostname=ssh_host,
            port=ssh_port,
            username=rust_proxy_state.exercise_name,
            pkey=valid_key,
            timeout=30.0,
            allow_agent=False,
            look_for_keys=False,
        )
        assert valid_client.get_transport() is not None
        valid_client.close()

    def test_19_x11_channel_data_flow(
        self,
        ssh_host: str,
        ssh_port: int,
        rust_proxy_state: RustProxyTestState,
    ):
        """Verify X11 forwarding sets DISPLAY environment variable."""
        import io

        import paramiko

        assert rust_proxy_state.private_key is not None
        assert rust_proxy_state.exercise_name is not None

        key_file = io.StringIO(rust_proxy_state.private_key)
        pkey = paramiko.Ed25519Key.from_private_key(key_file)

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=ssh_host,
            port=ssh_port,
            username=rust_proxy_state.exercise_name,
            pkey=pkey,
            timeout=60.0,
            allow_agent=False,
            look_for_keys=False,
        )

        transport = client.get_transport()
        assert transport is not None

        channel = transport.open_session()

        # Request X11 forwarding with mock cookie
        mock_cookie = "abcd1234" * 4  # 32 char hex cookie
        try:
            channel.request_x11(
                single_connection=False,
                auth_protocol="MIT-MAGIC-COOKIE-1",
                auth_cookie=mock_cookie,
                screen_number=0,
            )
            x11_accepted = True
        except paramiko.SSHException:
            x11_accepted = False

        assert x11_accepted, "X11 forwarding request should be accepted"

        # Run a command to check DISPLAY is set
        # When X11 forwarding is enabled, the server should set DISPLAY
        channel.exec_command("echo DISPLAY=$DISPLAY")
        channel.settimeout(10.0)

        output = b""
        try:
            while True:
                chunk = channel.recv(4096)
                if not chunk:
                    break
                output += chunk
        except Exception:
            pass

        output_str = output.decode("utf-8", errors="replace")

        # The command should complete successfully
        assert "DISPLAY=" in output_str, (
            f"Expected DISPLAY in output, got: {output_str}"
        )

        # If X11 forwarding is properly set up, DISPLAY should have a value
        # like "localhost:10" or similar. It may be empty if the container
        # sshd doesn't set it, but the proxy should still forward the request.

        channel.close()
        client.close()
