"""
REF SSH Client Helper

SSH client for connecting to REF exercise containers during E2E tests.
"""

import io
import socket
import time
from typing import Optional, Tuple

import paramiko


class REFSSHClient:
    """
    SSH client for connecting to REF exercise containers.

    Handles SSH connections through the REF SSH entry server.
    """

    # Default timeout for individual commands (10 seconds as requested)
    DEFAULT_COMMAND_TIMEOUT: float = 10.0
    # Default timeout for connection operations (60 seconds for container interactions)
    DEFAULT_CONNECTION_TIMEOUT: float = 60.0

    def __init__(self, host: str, port: int, timeout: float = 60.0):
        """
        Initialize the SSH client.

        Args:
            host: SSH server hostname
            port: SSH server port
            timeout: Connection timeout in seconds (default: 60s for container interactions)
        """
        self.host = host
        self.port = port
        self.timeout = timeout
        self.command_timeout = self.DEFAULT_COMMAND_TIMEOUT
        self.client: Optional[paramiko.SSHClient] = None
        self._connected = False
        # Store credentials for reconnection
        self._private_key: Optional[str] = None
        self._exercise_name: Optional[str] = None

    def connect(
        self,
        private_key: str,
        exercise_name: str,
        username: str = "user",
    ) -> bool:
        """
        Connect to an exercise container.

        In REF, the SSH username is the exercise name, and the user is authenticated
        by their SSH key.

        Args:
            private_key: The user's private SSH key (PEM format)
            exercise_name: Name of the exercise to connect to
            username: Local username (default: "user")

        Returns:
            True if connection was successful
        """
        # Store credentials for potential reconnection
        self._private_key = private_key
        self._exercise_name = exercise_name

        try:
            # Parse the private key
            key_file = io.StringIO(private_key)
            try:
                pkey = paramiko.RSAKey.from_private_key(key_file)
            except paramiko.SSHException:
                key_file.seek(0)
                try:
                    pkey = paramiko.Ed25519Key.from_private_key(key_file)
                except paramiko.SSHException:
                    key_file.seek(0)
                    pkey = paramiko.ECDSAKey.from_private_key(key_file)

            # Create SSH client
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            # Connect - in REF, the username is the exercise name
            self.client.connect(
                hostname=self.host,
                port=self.port,
                username=exercise_name,
                pkey=pkey,
                timeout=self.timeout,
                allow_agent=False,
                look_for_keys=False,
            )

            self._connected = True
            return True

        except Exception as e:
            self._connected = False
            raise ConnectionError(f"Failed to connect to REF: {e}") from e

    def reconnect(self, wait_time: float = 5.0, max_retries: int = 12) -> bool:
        """
        Reconnect to the container after a reset or disconnect.

        Args:
            wait_time: Time to wait between reconnection attempts
            max_retries: Maximum number of reconnection attempts

        Returns:
            True if reconnection was successful
        """
        if self._private_key is None or self._exercise_name is None:
            raise RuntimeError("Cannot reconnect: no stored credentials")

        # Close existing connection if any
        self.close()

        # Wait and retry connection
        for attempt in range(max_retries):
            time.sleep(wait_time)
            try:
                return self.connect(self._private_key, self._exercise_name)
            except ConnectionError:
                if attempt == max_retries - 1:
                    raise
        return False

    def close(self):
        """Close the SSH connection."""
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass
            self.client = None
        self._connected = False

    def is_connected(self) -> bool:
        """Check if the client is connected."""
        return self._connected and self.client is not None

    def execute(
        self,
        command: str,
        timeout: Optional[float] = None,
    ) -> Tuple[int, str, str]:
        """
        Execute a command in the container.

        Args:
            command: Command to execute
            timeout: Command timeout (uses command_timeout default of 10s if None)

        Returns:
            Tuple of (exit_code, stdout, stderr)

        Raises:
            TimeoutError: If the command doesn't complete within timeout
        """
        if not self.is_connected():
            raise RuntimeError("Not connected to SSH server")
        assert self.client is not None  # For type checker

        # Use command_timeout (10s default) for individual commands
        timeout = timeout or self.command_timeout

        _stdin, stdout, stderr = self.client.exec_command(
            command,
            timeout=timeout,
        )

        # Set channel timeout for exit status wait
        channel = stdout.channel
        channel.settimeout(timeout)

        # Wait for exit status with timeout
        if not channel.status_event.wait(timeout):
            channel.close()
            raise TimeoutError(f"Command '{command}' timed out after {timeout}s")

        exit_code = channel.recv_exit_status()
        stdout_str = stdout.read().decode("utf-8", errors="replace")
        stderr_str = stderr.read().decode("utf-8", errors="replace")

        return exit_code, stdout_str, stderr_str

    def write_file(self, remote_path: str, content: str, mode: int = 0o644) -> bool:
        """
        Write a file to the container.

        Args:
            remote_path: Path in the container
            content: File content
            mode: File permissions

        Returns:
            True if successful
        """
        if not self.is_connected():
            raise RuntimeError("Not connected to SSH server")
        assert self.client is not None  # For type checker

        try:
            sftp = self.client.open_sftp()
            try:
                with sftp.file(remote_path, "w") as f:
                    f.write(content)
                sftp.chmod(remote_path, mode)
                return True
            finally:
                sftp.close()
        except Exception as e:
            raise IOError(f"Failed to write file: {e}") from e

    def read_file(self, remote_path: str) -> str:
        """
        Read a file from the container.

        Args:
            remote_path: Path in the container

        Returns:
            File content as string
        """
        if not self.is_connected():
            raise RuntimeError("Not connected to SSH server")
        assert self.client is not None  # For type checker

        try:
            sftp = self.client.open_sftp()
            try:
                with sftp.file(remote_path, "r") as f:
                    return f.read().decode("utf-8", errors="replace")
            finally:
                sftp.close()
        except Exception as e:
            raise IOError(f"Failed to read file: {e}") from e

    def file_exists(self, remote_path: str) -> bool:
        """
        Check if a file exists in the container.

        Args:
            remote_path: Path in the container

        Returns:
            True if file exists
        """
        if not self.is_connected():
            raise RuntimeError("Not connected to SSH server")
        assert self.client is not None  # For type checker

        try:
            sftp = self.client.open_sftp()
            try:
                sftp.stat(remote_path)
                return True
            except FileNotFoundError:
                return False
            finally:
                sftp.close()
        except Exception:
            return False

    def list_files(self, remote_path: str = ".") -> list[str]:
        """
        List files in a directory.

        Args:
            remote_path: Directory path in the container

        Returns:
            List of filenames
        """
        if not self.is_connected():
            raise RuntimeError("Not connected to SSH server")
        assert self.client is not None  # For type checker

        try:
            sftp = self.client.open_sftp()
            try:
                return sftp.listdir(remote_path)
            finally:
                sftp.close()
        except Exception as e:
            raise IOError(f"Failed to list files: {e}") from e

    def run_task_command(self, task_cmd: str, timeout: float = 60.0) -> Tuple[int, str]:
        """
        Run a REF task command (task check, task submit, task reset).

        Args:
            task_cmd: Task subcommand (e.g., "check", "submit", "reset")
            timeout: Command timeout

        Returns:
            Tuple of (exit_code, output)
        """
        exit_code, stdout, stderr = self.execute(f"task {task_cmd}", timeout=timeout)
        output = stdout + stderr
        return exit_code, output

    def submit(self, timeout: float = 60.0) -> Tuple[bool, str]:
        """
        Submit the current solution.

        Args:
            timeout: Submission timeout

        Returns:
            Tuple of (success, output)
        """
        # The task submit command prompts for confirmation, send "y" to confirm
        exit_code, stdout, stderr = self.execute_with_input(
            "task submit", "y\n", timeout=timeout
        )
        output = stdout + stderr
        success = exit_code == 0 and "successfully created" in output.lower()
        return success, output

    def check(self, timeout: float = 60.0) -> Tuple[bool, str]:
        """
        Run the submission tests (without submitting).

        Args:
            timeout: Test timeout

        Returns:
            Tuple of (all_tests_passed, output)
        """
        exit_code, output = self.run_task_command("check", timeout=timeout)
        return exit_code == 0, output

    def execute_with_input(
        self,
        command: str,
        stdin_input: str,
        timeout: Optional[float] = None,
    ) -> Tuple[int, str, str]:
        """
        Execute a command with stdin input.

        Args:
            command: Command to execute
            stdin_input: Input to send to stdin
            timeout: Command timeout (uses command_timeout default of 10s if None)

        Returns:
            Tuple of (exit_code, stdout, stderr)

        Raises:
            TimeoutError: If the command doesn't complete within timeout
        """
        if not self.is_connected():
            raise RuntimeError("Not connected to SSH server")
        assert self.client is not None

        # Use command_timeout (10s default) for individual commands
        timeout = timeout or self.command_timeout

        stdin, stdout, stderr = self.client.exec_command(
            command,
            timeout=timeout,
        )

        # Send input to stdin
        stdin.write(stdin_input)
        stdin.channel.shutdown_write()

        # Set channel timeout for exit status wait
        channel = stdout.channel
        channel.settimeout(timeout)

        # Wait for exit status with timeout
        if not channel.status_event.wait(timeout):
            channel.close()
            raise TimeoutError(f"Command '{command}' timed out after {timeout}s")

        exit_code = channel.recv_exit_status()
        stdout_str = stdout.read().decode("utf-8", errors="replace")
        stderr_str = stderr.read().decode("utf-8", errors="replace")

        return exit_code, stdout_str, stderr_str

    def reset(self, timeout: float = 30.0, reconnect: bool = True) -> Tuple[bool, str]:
        """
        Reset the instance to initial state.

        Note: After reset, the container is destroyed and recreated, which means
        the SSH connection is lost. If reconnect=True (default), this method
        will attempt to reconnect after the reset.

        Args:
            timeout: Reset timeout
            reconnect: Whether to automatically reconnect after reset (default: True)

        Returns:
            Tuple of (success, output)
        """
        if not self.is_connected():
            raise RuntimeError("Not connected to SSH server")
        assert self.client is not None

        # The task reset command prompts for confirmation, send "y" to confirm
        # We need to handle this specially because the connection will drop
        stdin, stdout, stderr = self.client.exec_command(
            "task reset",
            timeout=timeout,
        )

        # Send confirmation
        stdin.write("y\n")
        stdin.channel.shutdown_write()

        # Try to read output - the connection may drop during this
        output = ""
        try:
            channel = stdout.channel
            channel.settimeout(timeout)

            # Read output until connection drops or command completes
            stdout_data = stdout.read().decode("utf-8", errors="replace")
            stderr_data = stderr.read().decode("utf-8", errors="replace")
            output = stdout_data + stderr_data
        except Exception:
            # Connection dropped during read - this is expected for reset
            pass

        # After reset, the container is destroyed and recreated
        # The connection will be closed by the server
        self._connected = False

        # Check for success indicators in output
        # The reset command outputs "Resetting instance now" before disconnecting
        success = (
            "Resetting instance now" in output or "closed by remote host" in output
        )

        if reconnect:
            # Wait for the new container to be ready and reconnect
            # Use shorter wait times since containers typically restart in 5-10s
            try:
                self.reconnect(wait_time=1.0, max_retries=20)
            except ConnectionError as e:
                return False, f"{output}\nFailed to reconnect after reset: {e}"

        return success, output

    def get_info(self, timeout: float = 30.0) -> Tuple[bool, str]:
        """
        Get instance info.

        Args:
            timeout: Command timeout

        Returns:
            Tuple of (success, output)
        """
        exit_code, output = self.run_task_command("info", timeout=timeout)
        return exit_code == 0, output


def wait_for_ssh_ready(
    host: str,
    port: int,
    timeout: float = 30.0,
    interval: float = 1.0,
) -> bool:
    """
    Wait for the SSH server to be ready.

    Args:
        host: SSH server hostname
        port: SSH server port
        timeout: Maximum time to wait
        interval: Time between connection attempts

    Returns:
        True if server is ready, False if timeout
    """
    start = time.time()
    while time.time() - start < timeout:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(interval)
            sock.connect((host, port))
            sock.close()
            return True
        except (socket.error, socket.timeout):
            time.sleep(interval)
    return False
