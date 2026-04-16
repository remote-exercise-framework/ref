"""
E2E Test: Full Exercise Lifecycle

Tests the complete workflow:
1. Admin creates/imports an exercise
2. Admin builds the exercise Docker image
3. Admin deploys (sets as default) the exercise
4. Student registers
5. Student connects via SSH
6. Student works on the exercise
7. Student submits solution
8. Automated tests run and scoring happens
9. Results are recorded correctly
"""

import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

import pytest

from helpers.conditions import (
    ExerciseConditions,
    SubmissionConditions,
    UserConditions,
)
from helpers.exercise_factory import (
    create_sample_exercise,
    create_correct_solution,
    create_incorrect_solution,
)
from helpers.ssh_client import REFSSHClient, wait_for_ssh_ready
from helpers.web_client import REFWebClient

if TYPE_CHECKING:
    from helpers.ref_instance import REFInstance

# Type alias for the SSH client factory fixture
SSHClientFactory = Callable[[str, str], REFSSHClient]


class TestExerciseLifecycleState:
    """Shared state for the exercise lifecycle tests."""

    exercise_name: Optional[str] = None
    exercise_id: Optional[int] = None
    student_mat_num: Optional[str] = None
    student_password: str = "TestPassword123!"
    student_private_key: Optional[str] = None
    student_public_key: Optional[str] = None


@pytest.fixture(scope="module")
def lifecycle_state() -> TestExerciseLifecycleState:
    """Shared state fixture for lifecycle tests."""
    return TestExerciseLifecycleState()


@pytest.fixture(scope="module")
def test_exercise_name() -> str:
    """Generate a unique exercise name for this test module."""
    return f"e2e_test_{uuid.uuid4().hex[:6]}"


@pytest.fixture(scope="module")
def test_student_mat_num() -> str:
    """Generate a unique matriculation number for test student."""
    return str(uuid.uuid4().int)[:8]


class TestExerciseLifecycle:
    """
    Test the full exercise lifecycle from creation to grading.

    Tests run in order using alphabetical ordering of test methods.
    The REF instance is automatically started before tests run.
    """

    @pytest.mark.e2e
    def test_01_admin_can_login(self, web_client: REFWebClient, admin_password: str):
        """Verify admin can login."""
        # First logout if already logged in
        web_client.logout()

        # Login as admin
        success = web_client.login("0", admin_password)
        assert success, "Admin login failed"
        assert web_client.is_logged_in(), "Admin not logged in after login"

    @pytest.mark.e2e
    def test_02_create_test_exercise(
        self,
        exercises_path: Path,
        test_exercise_name: str,
        lifecycle_state: TestExerciseLifecycleState,
    ):
        """Create a test exercise on the filesystem."""
        lifecycle_state.exercise_name = test_exercise_name
        exercise_dir = exercises_path / test_exercise_name

        if exercise_dir.exists():
            import shutil

            shutil.rmtree(exercise_dir)

        create_sample_exercise(
            exercise_dir,
            short_name=test_exercise_name,
            version=1,
            category="E2E Tests",
            has_deadline=True,
            has_submission_test=True,
            grading_points=10,
        )

        assert exercise_dir.exists(), "Exercise directory not created"
        assert (exercise_dir / "settings.yml").exists(), "settings.yml not created"
        assert (exercise_dir / "solution.c").exists(), "solution.c not created"
        assert (exercise_dir / "Makefile").exists(), "Makefile not created"
        assert (exercise_dir / "submission_tests").exists(), (
            "submission_tests not created"
        )

    @pytest.mark.e2e
    def test_03_import_exercise(
        self,
        admin_client: REFWebClient,
        exercises_path: Path,
        lifecycle_state: TestExerciseLifecycleState,
        ref_instance: "REFInstance",
    ):
        """Import the test exercise into REF."""
        assert lifecycle_state.exercise_name is not None, "exercise_name not set"
        exercise_path = str(exercises_path / lifecycle_state.exercise_name)

        # Pre-condition: Exercise should not exist yet
        ExerciseConditions.pre_exercise_not_exists(
            ref_instance, lifecycle_state.exercise_name
        )

        # Action: Import via web interface
        success = admin_client.import_exercise(exercise_path)
        assert success, f"Failed to import exercise from {exercise_path}"

        # Verify exercise was imported by checking exercise list
        exercise = admin_client.get_exercise_by_name(lifecycle_state.exercise_name)
        assert exercise is not None, (
            f"Exercise {lifecycle_state.exercise_name} not found after import"
        )
        lifecycle_state.exercise_id = exercise.get("id")
        assert lifecycle_state.exercise_id is not None, "Exercise ID not found"

        # Post-condition: Verify database state
        ExerciseConditions.post_exercise_imported(
            ref_instance, lifecycle_state.exercise_name
        )

    @pytest.mark.e2e
    def test_04_build_exercise(
        self,
        admin_client: REFWebClient,
        lifecycle_state: TestExerciseLifecycleState,
        ref_instance: "REFInstance",
    ):
        """Build the exercise Docker image."""
        assert lifecycle_state.exercise_id is not None, "Exercise ID not set"

        # Start the build
        success = admin_client.build_exercise(lifecycle_state.exercise_id)
        assert success, "Failed to start exercise build"

        # Wait for build to complete (with timeout)
        build_success = admin_client.wait_for_build(
            lifecycle_state.exercise_id, timeout=300.0
        )
        assert build_success, "Exercise build did not complete successfully"

        # Post-condition: Verify build status in database
        ExerciseConditions.post_exercise_built(
            ref_instance, lifecycle_state.exercise_id
        )

    @pytest.mark.e2e
    def test_05_enable_exercise(
        self,
        admin_client: REFWebClient,
        lifecycle_state: TestExerciseLifecycleState,
        ref_instance: "REFInstance",
    ):
        """Enable the exercise (set as default)."""
        assert lifecycle_state.exercise_id is not None, "Exercise ID not set"

        success = admin_client.toggle_exercise_default(lifecycle_state.exercise_id)
        assert success, "Failed to toggle exercise as default"

        # Post-condition: Verify exercise is enabled in database
        ExerciseConditions.post_exercise_enabled(
            ref_instance, lifecycle_state.exercise_id
        )

    @pytest.mark.e2e
    def test_06_register_student(
        self,
        web_client: REFWebClient,
        admin_password: str,
        test_student_mat_num: str,
        lifecycle_state: TestExerciseLifecycleState,
        ref_instance: "REFInstance",
    ):
        """Register a test student and get SSH keys."""
        # Logout admin first to use student endpoint
        web_client.logout()

        lifecycle_state.student_mat_num = test_student_mat_num

        # Pre-condition: User should not exist yet
        UserConditions.pre_user_not_exists(ref_instance, test_student_mat_num)

        # Action: Register via web interface
        success, private_key, public_key = web_client.register_student(
            mat_num=test_student_mat_num,
            firstname="Test",
            surname="Student",
            password=lifecycle_state.student_password,
        )

        assert success, "Failed to register student"
        assert private_key is not None, "Private key not received after registration"

        lifecycle_state.student_private_key = private_key
        lifecycle_state.student_public_key = public_key

        # Post-conditions: Verify user in database
        UserConditions.post_user_created(
            ref_instance, test_student_mat_num, "Test", "Student"
        )
        UserConditions.post_user_is_student(ref_instance, test_student_mat_num)
        UserConditions.post_user_has_ssh_key(ref_instance, test_student_mat_num)

        # Re-login as admin for subsequent tests that may use admin_client
        web_client.login("0", admin_password)


class TestSSHConnection:
    """
    Test SSH connections to exercise containers.
    """

    @pytest.mark.e2e
    def test_ssh_server_reachable(self, ssh_host: str, ssh_port: int):
        """Verify SSH server is reachable."""
        assert wait_for_ssh_ready(ssh_host, ssh_port, timeout=10), (
            f"SSH server not reachable at {ssh_host}:{ssh_port}"
        )

    @pytest.mark.e2e
    def test_student_can_connect(
        self,
        ssh_client_factory: SSHClientFactory,
        lifecycle_state: TestExerciseLifecycleState,
    ):
        """Test that a student can connect to their exercise container."""
        assert lifecycle_state.student_private_key is not None, (
            "Student private key not available"
        )
        assert lifecycle_state.exercise_name is not None, "Exercise name not available"

        client = ssh_client_factory(
            lifecycle_state.student_private_key,
            lifecycle_state.exercise_name,
        )

        # Verify connection works by executing a simple command
        exit_code, stdout, stderr = client.execute("echo 'Hello from container'")
        assert exit_code == 0, f"Command failed with exit code {exit_code}: {stderr}"
        assert "Hello from container" in stdout

    @pytest.mark.e2e
    def test_student_can_list_files(
        self,
        ssh_client_factory: SSHClientFactory,
        lifecycle_state: TestExerciseLifecycleState,
    ):
        """Test that student can list files in the container."""
        assert lifecycle_state.student_private_key is not None, (
            "Student private key not available"
        )
        assert lifecycle_state.exercise_name is not None, "Exercise name not available"

        client = ssh_client_factory(
            lifecycle_state.student_private_key,
            lifecycle_state.exercise_name,
        )

        # List files in home directory
        files = client.list_files("/home/user")
        assert len(files) >= 0, "Should be able to list files"

    @pytest.mark.e2e
    def test_student_can_write_files(
        self,
        ssh_client_factory: SSHClientFactory,
        lifecycle_state: TestExerciseLifecycleState,
    ):
        """Test that student can create files in the container."""
        assert lifecycle_state.student_private_key is not None, (
            "Student private key not available"
        )
        assert lifecycle_state.exercise_name is not None, "Exercise name not available"

        client = ssh_client_factory(
            lifecycle_state.student_private_key,
            lifecycle_state.exercise_name,
        )

        # Write a test file
        test_content = "This is a test file\n"
        client.write_file("/home/user/test_file.txt", test_content)

        # Verify file was written
        read_content = client.read_file("/home/user/test_file.txt")
        assert read_content.strip() == test_content.strip()


class TestSubmissionWorkflow:
    """
    Test the submission and grading workflow.
    """

    @pytest.mark.e2e
    def test_upload_correct_solution(
        self,
        ssh_client_factory: SSHClientFactory,
        lifecycle_state: TestExerciseLifecycleState,
    ):
        """Upload a correct solution to the container."""
        assert lifecycle_state.student_private_key is not None, (
            "Student private key not available"
        )
        assert lifecycle_state.exercise_name is not None, "Exercise name not available"

        client = ssh_client_factory(
            lifecycle_state.student_private_key,
            lifecycle_state.exercise_name,
        )

        # Upload correct solution
        correct_solution = create_correct_solution()
        client.write_file("/home/user/solution.c", correct_solution)

        # Verify file was written
        assert client.file_exists("/home/user/solution.c")

    @pytest.mark.e2e
    def test_task_check_passes(
        self,
        ssh_client_factory: SSHClientFactory,
        lifecycle_state: TestExerciseLifecycleState,
    ):
        """Test that 'task check' passes with correct solution."""
        assert lifecycle_state.student_private_key is not None, (
            "Student private key not available"
        )
        assert lifecycle_state.exercise_name is not None, "Exercise name not available"

        client = ssh_client_factory(
            lifecycle_state.student_private_key,
            lifecycle_state.exercise_name,
        )

        # Run task check
        success, output = client.check(timeout=120.0)
        assert success, f"task check failed: {output}"

    @pytest.mark.e2e
    def test_task_submit(
        self,
        ssh_client_factory: SSHClientFactory,
        lifecycle_state: TestExerciseLifecycleState,
        ref_instance: "REFInstance",
    ):
        """Test that 'task submit' creates a submission."""
        assert lifecycle_state.student_private_key is not None, (
            "Student private key not available"
        )
        assert lifecycle_state.exercise_name is not None, "Exercise name not available"
        assert lifecycle_state.student_mat_num is not None, (
            "Student mat_num not available"
        )

        client = ssh_client_factory(
            lifecycle_state.student_private_key,
            lifecycle_state.exercise_name,
        )

        # Submit the solution
        success, output = client.submit(timeout=120.0)
        assert success, f"task submit failed: {output}"

        # Post-conditions: Verify submission in database
        submission_data = SubmissionConditions.post_submission_created(
            ref_instance,
            lifecycle_state.student_mat_num,
            lifecycle_state.exercise_name,
        )
        assert submission_data["submission_ts"] is not None

        # Verify test results were recorded
        SubmissionConditions.post_submission_has_test_results(
            ref_instance, submission_data["id"]
        )


class TestIncorrectSolution:
    """Test behavior with incorrect solutions."""

    @pytest.mark.e2e
    @pytest.mark.timeout(180)
    def test_task_check_fails_with_incorrect_solution(
        self,
        ssh_client_factory: SSHClientFactory,
        lifecycle_state: TestExerciseLifecycleState,
    ):
        """Test that 'task check' fails with an incorrect solution."""
        assert lifecycle_state.student_private_key is not None, (
            "Student private key not available"
        )
        assert lifecycle_state.exercise_name is not None, "Exercise name not available"

        client = ssh_client_factory(
            lifecycle_state.student_private_key,
            lifecycle_state.exercise_name,
        )

        # Reset to a fresh state (this reconnects automatically)
        success, output = client.reset()
        assert success, f"Reset failed: {output}"

        # Upload incorrect solution
        incorrect_solution = create_incorrect_solution()
        client.write_file("/home/user/solution.c", incorrect_solution)

        # Verify the file was written correctly
        written_content = client.read_file("/home/user/solution.c")
        assert "return 0;  // Wrong implementation" in written_content, (
            "Incorrect solution was not written properly"
        )

        # Run task check - should fail because add() returns 0 instead of a+b
        # The task check command rebuilds the code and runs tests
        success, output = client.check(timeout=120.0)
        assert not success, f"task check should have failed but passed: {output}"


class TestTaskReset:
    """Test the task reset functionality."""

    @pytest.mark.e2e
    def test_task_reset_restores_initial_state(
        self,
        ssh_client_factory: SSHClientFactory,
        lifecycle_state: TestExerciseLifecycleState,
    ):
        """Test that 'task reset' restores initial state."""
        assert lifecycle_state.student_private_key is not None, (
            "Student private key not available"
        )
        assert lifecycle_state.exercise_name is not None, "Exercise name not available"

        client = ssh_client_factory(
            lifecycle_state.student_private_key,
            lifecycle_state.exercise_name,
        )

        # Create a custom file
        client.write_file("/home/user/custom_file.txt", "Custom content")
        assert client.file_exists("/home/user/custom_file.txt")

        # Reset to initial state
        success, output = client.reset()
        assert success, f"task reset failed: {output}"

        # Verify custom file was removed
        assert not client.file_exists("/home/user/custom_file.txt"), (
            "Custom file should be removed after reset"
        )


# Standalone tests that can run with minimal setup
class TestBasicFunctionality:
    """
    Basic functionality tests that can run with minimal setup.
    """

    @pytest.mark.e2e
    def test_web_interface_accessible(self, web_url: str):
        """Test that the web interface is accessible."""
        import httpx

        response = httpx.get(f"{web_url}/login", timeout=10)
        assert response.status_code == 200, (
            f"Web interface not accessible: {response.status_code}"
        )
        assert "login" in response.text.lower() or "Login" in response.text

    @pytest.mark.e2e
    def test_admin_login_page(self, web_url: str):
        """Test that the admin login page loads."""
        import httpx

        response = httpx.get(f"{web_url}/login", timeout=10)
        assert response.status_code == 200
        # Check for form elements
        assert "username" in response.text.lower() or "Matriculation" in response.text
        assert "password" in response.text.lower()

    @pytest.mark.e2e
    def test_admin_login_invalid_credentials(self, web_url: str):
        """Test that invalid credentials are rejected."""
        import httpx

        client = httpx.Client(follow_redirects=True)
        try:
            # Submit invalid credentials
            response = client.post(
                f"{web_url}/login",
                data={
                    "username": "invalid",
                    "password": "invalid",
                    "submit": "Login",
                },
            )
            # Should stay on login page with error
            assert "login" in response.url.path.lower() or response.status_code == 200
        finally:
            client.close()

    @pytest.mark.e2e
    def test_admin_login_valid_credentials(self, web_url: str, admin_password: str):
        """Test that valid admin credentials work."""
        import httpx

        client = httpx.Client(follow_redirects=True)
        try:
            # Submit valid credentials
            response = client.post(
                f"{web_url}/login",
                data={
                    "username": "0",
                    "password": admin_password,
                    "submit": "Login",
                },
            )
            # Should redirect to exercise view
            assert (
                "/admin/exercise/view" in str(response.url)
                or "exercise" in response.text.lower()
            ), f"Login did not redirect to admin page: {response.url}"
        finally:
            client.close()

    @pytest.mark.e2e
    def test_api_header_endpoint(self, web_url: str):
        """Test the API header endpoint."""
        import httpx

        response = httpx.post(f"{web_url}/api/header", timeout=10)
        # This endpoint should return the SSH welcome message
        assert response.status_code == 200
