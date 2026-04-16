"""
E2E Test: SSH Key Type Support

Tests SSH authentication with different key types (RSA, ed25519, ECDSA).

This test module verifies that users can register with different SSH key types
and successfully connect to exercise containers via SSH.
"""

import uuid
from pathlib import Path
from typing import Callable, Optional

import pytest

from helpers.exercise_factory import create_sample_exercise
from helpers.ssh_client import REFSSHClient
from helpers.web_client import REFWebClient

SSHClientFactory = Callable[[str, str], REFSSHClient]


class KeyTypeTestState:
    """Shared state for key type tests."""

    exercise_name: Optional[str] = None
    exercise_id: Optional[int] = None
    # RSA student
    rsa_mat_num: Optional[str] = None
    rsa_private_key: Optional[str] = None
    # ed25519 student
    ed25519_mat_num: Optional[str] = None
    ed25519_private_key: Optional[str] = None
    # ECDSA student
    ecdsa_mat_num: Optional[str] = None
    ecdsa_private_key: Optional[str] = None

    student_password: str = "TestPassword123!"


@pytest.fixture(scope="module")
def key_type_state() -> KeyTypeTestState:
    """Shared state fixture for key type tests."""
    return KeyTypeTestState()


@pytest.fixture(scope="module")
def kt_exercise_name() -> str:
    """Generate a unique exercise name for key type tests."""
    return f"keytype_test_{uuid.uuid4().hex[:6]}"


def _generate_ed25519_key_pair() -> tuple[str, str]:
    """Generate an ed25519 key pair."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
        PublicFormat,
    )

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    private_pem = private_key.private_bytes(
        Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption()
    ).decode()
    public_openssh = public_key.public_bytes(
        Encoding.OpenSSH, PublicFormat.OpenSSH
    ).decode()

    return private_pem, public_openssh


def _generate_ecdsa_key_pair() -> tuple[str, str]:
    """Generate an ECDSA key pair."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
        PublicFormat,
    )

    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()

    private_pem = private_key.private_bytes(
        Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption()
    ).decode()
    public_openssh = public_key.public_bytes(
        Encoding.OpenSSH, PublicFormat.OpenSSH
    ).decode()

    return private_pem, public_openssh


@pytest.mark.e2e
class TestKeyTypeSetup:
    """
    Setup tests for key type testing.

    Creates exercise and registers students with different key types.
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
        kt_exercise_name: str,
        key_type_state: KeyTypeTestState,
    ):
        """Create a test exercise for key type tests."""
        key_type_state.exercise_name = kt_exercise_name
        exercise_dir = exercises_path / kt_exercise_name

        if exercise_dir.exists():
            import shutil

            shutil.rmtree(exercise_dir)

        create_sample_exercise(
            exercise_dir,
            short_name=kt_exercise_name,
            version=1,
            category="Key Type Tests",
        )

        assert exercise_dir.exists(), "Exercise directory not created"

    def test_03_import_and_build_exercise(
        self,
        admin_client: REFWebClient,
        exercises_path: Path,
        key_type_state: KeyTypeTestState,
    ):
        """Import and build the exercise."""
        assert key_type_state.exercise_name is not None

        exercise_path = str(exercises_path / key_type_state.exercise_name)
        success = admin_client.import_exercise(exercise_path)
        assert success, "Failed to import exercise"

        exercise = admin_client.get_exercise_by_name(key_type_state.exercise_name)
        assert exercise is not None
        exercise_id = exercise.get("id")
        assert exercise_id is not None, "Exercise ID not found"
        key_type_state.exercise_id = exercise_id

        success = admin_client.build_exercise(exercise_id)
        assert success, "Failed to start exercise build"

        build_success = admin_client.wait_for_build(exercise_id, timeout=300.0)
        assert build_success, "Exercise build did not complete"

    def test_04_enable_exercise(
        self,
        admin_client: REFWebClient,
        key_type_state: KeyTypeTestState,
    ):
        """Enable the exercise."""
        assert key_type_state.exercise_id is not None
        success = admin_client.toggle_exercise_default(key_type_state.exercise_id)
        assert success, "Failed to enable exercise"

    def test_05_register_rsa_student(
        self,
        web_client: REFWebClient,
        admin_password: str,
        key_type_state: KeyTypeTestState,
    ):
        """Register a test student with auto-generated RSA key."""
        web_client.logout()
        mat_num = str(uuid.uuid4().int)[:8]
        key_type_state.rsa_mat_num = mat_num

        success, private_key, _ = web_client.register_student(
            mat_num=mat_num,
            firstname="RSA",
            surname="Tester",
            password=key_type_state.student_password,
        )

        assert success, "Failed to register RSA student"
        assert private_key is not None
        key_type_state.rsa_private_key = private_key

        # Re-login as admin
        web_client.login("0", admin_password)

    def test_06_register_ed25519_student(
        self,
        web_client: REFWebClient,
        admin_password: str,
        key_type_state: KeyTypeTestState,
    ):
        """Register a test student with ed25519 key."""
        web_client.logout()
        mat_num = str(uuid.uuid4().int)[:8]
        key_type_state.ed25519_mat_num = mat_num

        private_pem, public_openssh = _generate_ed25519_key_pair()

        success, _, _ = web_client.register_student(
            mat_num=mat_num,
            firstname="Ed25519",
            surname="Tester",
            password=key_type_state.student_password,
            pubkey=public_openssh,
        )

        assert success, "Failed to register ed25519 student"
        key_type_state.ed25519_private_key = private_pem

        # Re-login as admin
        web_client.login("0", admin_password)

    def test_07_register_ecdsa_student(
        self,
        web_client: REFWebClient,
        admin_password: str,
        key_type_state: KeyTypeTestState,
    ):
        """Register a test student with ECDSA key."""
        web_client.logout()
        mat_num = str(uuid.uuid4().int)[:8]
        key_type_state.ecdsa_mat_num = mat_num

        private_pem, public_openssh = _generate_ecdsa_key_pair()

        success, _, _ = web_client.register_student(
            mat_num=mat_num,
            firstname="ECDSA",
            surname="Tester",
            password=key_type_state.student_password,
            pubkey=public_openssh,
        )

        assert success, "Failed to register ECDSA student"
        key_type_state.ecdsa_private_key = private_pem

        # Re-login as admin
        web_client.login("0", admin_password)


@pytest.mark.e2e
class TestRSASSHConnection:
    """Test SSH connection with RSA key."""

    def test_ssh_connect_with_rsa(
        self,
        ssh_client_factory: SSHClientFactory,
        key_type_state: KeyTypeTestState,
    ):
        """Verify SSH connection works with RSA key."""
        assert key_type_state.rsa_private_key is not None
        assert key_type_state.exercise_name is not None

        client = ssh_client_factory(
            key_type_state.rsa_private_key,
            key_type_state.exercise_name,
        )

        assert client.is_connected(), "RSA SSH connection failed"

        # Execute a simple command to verify the connection works
        exit_code, stdout, stderr = client.execute("echo 'RSA test'")
        assert exit_code == 0, f"Command failed with stderr: {stderr}"
        assert "RSA test" in stdout

        client.close()


@pytest.mark.e2e
class TestEd25519SSHConnection:
    """Test SSH connection with ed25519 key."""

    def test_ssh_connect_with_ed25519(
        self,
        ssh_client_factory: SSHClientFactory,
        key_type_state: KeyTypeTestState,
    ):
        """Verify SSH connection works with ed25519 key."""
        assert key_type_state.ed25519_private_key is not None
        assert key_type_state.exercise_name is not None

        client = ssh_client_factory(
            key_type_state.ed25519_private_key,
            key_type_state.exercise_name,
        )

        assert client.is_connected(), "ed25519 SSH connection failed"

        # Execute a simple command to verify the connection works
        exit_code, stdout, stderr = client.execute("echo 'ed25519 test'")
        assert exit_code == 0, f"Command failed with stderr: {stderr}"
        assert "ed25519 test" in stdout

        client.close()

    def test_file_operations_with_ed25519(
        self,
        ssh_client_factory: SSHClientFactory,
        key_type_state: KeyTypeTestState,
    ):
        """Verify file operations work over SSH with ed25519 key."""
        assert key_type_state.ed25519_private_key is not None
        assert key_type_state.exercise_name is not None

        client = ssh_client_factory(
            key_type_state.ed25519_private_key,
            key_type_state.exercise_name,
        )

        # Write a file
        test_content = "Test file content from ed25519 connection"
        client.write_file("/tmp/ed25519_test.txt", test_content)

        # Read it back
        read_content = client.read_file("/tmp/ed25519_test.txt")
        assert read_content == test_content

        client.close()


@pytest.mark.e2e
class TestECDSASSHConnection:
    """Test SSH connection with ECDSA key."""

    def test_ssh_connect_with_ecdsa(
        self,
        ssh_client_factory: SSHClientFactory,
        key_type_state: KeyTypeTestState,
    ):
        """Verify SSH connection works with ECDSA key."""
        assert key_type_state.ecdsa_private_key is not None
        assert key_type_state.exercise_name is not None

        client = ssh_client_factory(
            key_type_state.ecdsa_private_key,
            key_type_state.exercise_name,
        )

        assert client.is_connected(), "ECDSA SSH connection failed"

        # Execute a simple command to verify the connection works
        exit_code, stdout, stderr = client.execute("echo 'ECDSA test'")
        assert exit_code == 0, f"Command failed with stderr: {stderr}"
        assert "ECDSA test" in stdout

        client.close()
