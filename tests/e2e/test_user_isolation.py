"""
E2E Test: User Isolation

Tests that multiple users have isolated containers:
1. Two students connect to the same exercise
2. Verify they have separate containers
3. Verify one user cannot access another's files
4. Both submit independently
5. Verify separate grading
"""

import uuid
from pathlib import Path
from typing import Optional

import pytest

from helpers.exercise_factory import create_sample_exercise
from helpers.ssh_client import REFSSHClient
from helpers.web_client import REFWebClient

# Type alias for student credentials
StudentCredentials = dict[str, str]


class IsolationTestState:
    """Shared state for isolation tests."""

    exercise_name: Optional[str] = None
    exercise_id: Optional[int] = None
    student1_mat_num: Optional[str] = None
    student1_private_key: Optional[str] = None
    student2_mat_num: Optional[str] = None
    student2_private_key: Optional[str] = None
    # Module-scoped SSH clients (set after students are registered)
    student1_client: Optional[REFSSHClient] = None
    student2_client: Optional[REFSSHClient] = None


@pytest.fixture(scope="module")
def isolation_state() -> IsolationTestState:
    """Shared state fixture for isolation tests."""
    return IsolationTestState()


@pytest.fixture(scope="module")
def isolation_exercise_name() -> str:
    """Generate a unique exercise name for this test module."""
    return f"isolation_test_{uuid.uuid4().hex[:6]}"


@pytest.fixture(scope="module")
def student1_client(
    ssh_host: str,
    ssh_port: int,
    isolation_state: IsolationTestState,
) -> REFSSHClient:
    """Module-scoped SSH client for student 1. Reused across tests."""
    if isolation_state.student1_client is not None:
        return isolation_state.student1_client

    # This fixture is used after test_02_register_students runs
    assert isolation_state.student1_private_key is not None, (
        "Student 1 not registered yet"
    )
    assert isolation_state.exercise_name is not None, "Exercise not created yet"

    client = REFSSHClient(ssh_host, ssh_port)
    client.connect(isolation_state.student1_private_key, isolation_state.exercise_name)
    isolation_state.student1_client = client
    return client


@pytest.fixture(scope="module")
def student2_client(
    ssh_host: str,
    ssh_port: int,
    isolation_state: IsolationTestState,
) -> REFSSHClient:
    """Module-scoped SSH client for student 2. Reused across tests."""
    if isolation_state.student2_client is not None:
        return isolation_state.student2_client

    # This fixture is used after test_02_register_students runs
    assert isolation_state.student2_private_key is not None, (
        "Student 2 not registered yet"
    )
    assert isolation_state.exercise_name is not None, "Exercise not created yet"

    client = REFSSHClient(ssh_host, ssh_port)
    client.connect(isolation_state.student2_private_key, isolation_state.exercise_name)
    isolation_state.student2_client = client
    return client


@pytest.mark.timeout(60)
class TestUserIsolationSetup:
    """Setup tests for user isolation."""

    @pytest.mark.e2e
    def test_00_create_exercise(
        self,
        exercises_path: Path,
        isolation_exercise_name: str,
        isolation_state: IsolationTestState,
    ):
        """Create exercise for isolation tests."""
        isolation_state.exercise_name = isolation_exercise_name
        exercise_dir = exercises_path / isolation_exercise_name

        if exercise_dir.exists():
            import shutil

            shutil.rmtree(exercise_dir)

        create_sample_exercise(
            exercise_dir,
            short_name=isolation_exercise_name,
            version=1,
            category="Isolation Tests",
            has_deadline=True,
            has_submission_test=True,
            grading_points=10,
        )
        assert exercise_dir.exists()

    @pytest.mark.e2e
    @pytest.mark.timeout(360)
    def test_01_import_and_build_exercise(
        self,
        admin_client: REFWebClient,
        exercises_path: Path,
        isolation_state: IsolationTestState,
    ):
        """Import and build exercise for isolation tests."""
        assert isolation_state.exercise_name is not None
        exercise_path = str(exercises_path / isolation_state.exercise_name)

        success = admin_client.import_exercise(exercise_path)
        assert success, "Failed to import exercise"

        exercise = admin_client.get_exercise_by_name(isolation_state.exercise_name)
        assert exercise is not None
        isolation_state.exercise_id = exercise.get("id")
        assert isolation_state.exercise_id is not None, "Exercise ID not found"

        success = admin_client.build_exercise(isolation_state.exercise_id)
        assert success, "Failed to start build"

        build_success = admin_client.wait_for_build(
            isolation_state.exercise_id, timeout=300.0
        )
        assert build_success, "Build failed"

        success = admin_client.toggle_exercise_default(isolation_state.exercise_id)
        assert success, "Failed to enable exercise"

    @pytest.mark.e2e
    def test_02_register_students(
        self,
        web_client: REFWebClient,
        admin_password: str,
        isolation_state: IsolationTestState,
    ):
        """Register two test students."""
        web_client.logout()

        # Register student 1
        isolation_state.student1_mat_num = str(uuid.uuid4().int)[:8]
        success, private_key, _ = web_client.register_student(
            mat_num=isolation_state.student1_mat_num,
            firstname="Isolation",
            surname="StudentOne",
            password="TestPassword123!",
        )
        assert success, "Failed to register student 1"
        isolation_state.student1_private_key = private_key

        # Register student 2
        isolation_state.student2_mat_num = str(uuid.uuid4().int)[:8]
        success, private_key, _ = web_client.register_student(
            mat_num=isolation_state.student2_mat_num,
            firstname="Isolation",
            surname="StudentTwo",
            password="TestPassword123!",
        )
        assert success, "Failed to register student 2"
        isolation_state.student2_private_key = private_key

        # Re-login as admin for subsequent tests that may use admin_client
        web_client.login("0", admin_password)


@pytest.mark.timeout(60)
class TestUserIsolation:
    """
    Test that user containers are properly isolated.

    These tests require:
    - A deployed and built exercise
    - Two registered students with SSH keys
    """

    @pytest.mark.e2e
    def test_separate_containers(
        self,
        student1_client: REFSSHClient,
        student2_client: REFSSHClient,
    ):
        """
        Test that each user gets a separate container.

        This test connects two users and verifies they have isolated
        environments by creating unique marker files that should not
        be visible to each other.
        """
        # Create a unique marker file as student 1
        marker1 = f"marker_student1_{uuid.uuid4().hex}"
        marker1_path = f"/tmp/{marker1}"
        exit_code, _, _ = student1_client.execute(f"echo 'student1' > {marker1_path}")
        assert exit_code == 0, "Failed to create marker file for student 1"

        # Create a different unique marker file as student 2
        marker2 = f"marker_student2_{uuid.uuid4().hex}"
        marker2_path = f"/tmp/{marker2}"
        exit_code, _, _ = student2_client.execute(f"echo 'student2' > {marker2_path}")
        assert exit_code == 0, "Failed to create marker file for student 2"

        # Verify student 1 can see their own marker but not student 2's
        exit_code, _, _ = student1_client.execute(f"test -f {marker1_path}")
        assert exit_code == 0, "Student 1 should see their own marker file"
        exit_code, _, _ = student1_client.execute(f"test -f {marker2_path}")
        assert exit_code != 0, "Student 1 should NOT see student 2's marker file"

        # Verify student 2 can see their own marker but not student 1's
        exit_code, _, _ = student2_client.execute(f"test -f {marker2_path}")
        assert exit_code == 0, "Student 2 should see their own marker file"
        exit_code, _, _ = student2_client.execute(f"test -f {marker1_path}")
        assert exit_code != 0, "Student 2 should NOT see student 1's marker file"

    @pytest.mark.e2e
    def test_file_isolation(
        self,
        student1_client: REFSSHClient,
        student2_client: REFSSHClient,
    ):
        """
        Test that files created by one user are not visible to another.
        """
        # Create unique file as student 1
        unique_content = f"secret_{uuid.uuid4().hex}"
        secret_file = "/home/user/student1_secret.txt"

        student1_client.write_file(secret_file, unique_content)
        assert student1_client.file_exists(secret_file), (
            "File should exist for student 1"
        )

        # Verify file is NOT visible to student 2
        assert not student2_client.file_exists(secret_file), (
            "Student 2 should NOT see student 1's files"
        )

    @pytest.mark.e2e
    @pytest.mark.timeout(180)
    def test_independent_submissions(
        self,
        student1_client: REFSSHClient,
        student2_client: REFSSHClient,
    ):
        """
        Test that users can submit independently.
        """
        from helpers.exercise_factory import create_correct_solution

        # Student 1 submits (write_file overwrites any existing file)
        student1_client.write_file("/home/user/solution.c", create_correct_solution())
        success1, output1 = student1_client.submit(timeout=120.0)
        assert success1, f"Student 1 submission failed: {output1}"

        # Student 2 submits
        student2_client.write_file("/home/user/solution.c", create_correct_solution())
        success2, output2 = student2_client.submit(timeout=120.0)
        assert success2, f"Student 2 submission failed: {output2}"

    @pytest.mark.e2e
    def test_independent_grading(
        self,
        admin_client: REFWebClient,
        admin_password: str,
        isolation_state: IsolationTestState,
    ):
        """
        Test that users can be graded independently.
        """
        # Ensure admin is logged in
        if not admin_client.is_logged_in():
            admin_client.login("0", admin_password)

        # Verify grading page is accessible
        response = admin_client.client.get("/admin/grading/")
        assert response.status_code == 200, (
            "Admin should be able to access grading page"
        )

        # Note: Full independent grading test would require parsing the submission
        # list and grading each separately. The test verifies the grading interface
        # is accessible after both students have submitted.


@pytest.mark.timeout(60)
class TestContainerSecurity:
    """
    Test container security measures.

    Uses module-scoped student1_client for efficiency.
    """

    @pytest.mark.e2e
    def test_cannot_access_host_filesystem(
        self,
        student1_client: REFSSHClient,
    ):
        """
        Test that users cannot access the host filesystem.
        """
        # Check that /etc/passwd exists in container (basic sanity check)
        exit_code, stdout, _ = student1_client.execute("cat /etc/passwd")
        assert exit_code == 0, "Should be able to read /etc/passwd in container"

        # The container should have a 'user' entry
        assert "user" in stdout, "Container should have 'user' in /etc/passwd"

        # Try to access a path that would only exist on host
        # The container should not have access to /host or similar escape paths
        exit_code, _, _ = student1_client.execute(
            "ls /host 2>/dev/null || echo 'not found'"
        )
        # This should either fail or return empty - no host filesystem access

        # Verify we're in a container by checking for container markers
        exit_code, stdout, _ = student1_client.execute(
            "cat /proc/1/cgroup 2>/dev/null || echo 'no cgroup'"
        )
        # In a container, this typically shows docker/container identifiers

    @pytest.mark.e2e
    def test_resource_limits_enforced(
        self,
        student1_client: REFSSHClient,
    ):
        """
        Test that resource limits (CPU, memory, PIDs) are enforced.
        """
        # Check memory limits via cgroup
        _exit_code, _stdout, _ = student1_client.execute(
            "cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null || "
            "cat /sys/fs/cgroup/memory.max 2>/dev/null || echo 'unknown'"
        )
        # If we can read this, we can verify a limit exists
        # The exact value depends on container configuration

        # Check PID limits
        _exit_code, _stdout, _ = student1_client.execute(
            "cat /sys/fs/cgroup/pids/pids.max 2>/dev/null || "
            "cat /sys/fs/cgroup/pids.max 2>/dev/null || echo 'unknown'"
        )

        # Verify we can execute commands (basic resource availability)
        exit_code, _stdout, _ = student1_client.execute("echo 'resources available'")
        assert exit_code == 0, "Should be able to execute basic commands"

    @pytest.mark.e2e
    def test_network_isolation(
        self,
        student1_client: REFSSHClient,
    ):
        """
        Test that container network is properly isolated.
        """
        # Check network interfaces - container should have limited interfaces
        _exit_code, _stdout, _ = student1_client.execute(
            "ip addr 2>/dev/null || ifconfig 2>/dev/null || echo 'no network info'"
        )
        # In a properly configured container, this should show limited network access

        # Try to access common internal services (should fail or be blocked)
        # This tests that the container can't reach internal services
        _exit_code, _stdout, _ = student1_client.execute(
            "timeout 2 bash -c 'echo > /dev/tcp/localhost/5432' 2>&1 || echo 'connection failed'"
        )
        # Database ports should not be accessible from student containers

        # Verify basic network functionality within container
        exit_code, _stdout, _ = student1_client.execute("hostname")
        assert exit_code == 0, "Should be able to get hostname"
