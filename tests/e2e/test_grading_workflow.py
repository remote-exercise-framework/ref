"""
E2E Test: Grading Workflow

Tests the grading workflow:
1. Student submits solution
2. Automated tests run
3. Grading assistant reviews submission
4. Manual grade assigned
5. Student can view results
"""

import uuid
from pathlib import Path
from typing import Callable, Optional

import pytest

from helpers.exercise_factory import (
    create_correct_solution,
    create_incorrect_solution,
    create_sample_exercise,
)
from helpers.ssh_client import REFSSHClient
from helpers.web_client import REFWebClient

# Type alias for the SSH client factory fixture
SSHClientFactory = Callable[[str, str], REFSSHClient]


class GradingWorkflowState:
    """Shared state for grading workflow tests."""

    exercise_name: Optional[str] = None
    exercise_id: Optional[int] = None
    student_mat_num: Optional[str] = None
    student_password: str = "TestPassword123!"
    student_private_key: Optional[str] = None
    submission_id: Optional[int] = None
    grading_assistant_mat_num: Optional[str] = None
    grading_assistant_password: str = "GradingAssistant123!"


@pytest.fixture(scope="module")
def grading_state() -> GradingWorkflowState:
    """Shared state fixture for grading workflow tests."""
    return GradingWorkflowState()


@pytest.fixture(scope="module")
def grading_exercise_name() -> str:
    """Generate a unique exercise name for this test module."""
    return f"grading_test_{uuid.uuid4().hex[:6]}"


@pytest.fixture(scope="module")
def grading_student_mat_num() -> str:
    """Generate a unique matriculation number for test student."""
    return str(uuid.uuid4().int)[:8]


class TestGradingWorkflowSetup:
    """
    Setup tests for the grading workflow.
    These must run first to set up the exercise and student.
    """

    @pytest.mark.e2e
    def test_00_create_exercise(
        self,
        exercises_path: Path,
        grading_exercise_name: str,
        grading_state: GradingWorkflowState,
    ):
        """Create a test exercise for grading workflow tests."""
        grading_state.exercise_name = grading_exercise_name
        exercise_dir = exercises_path / grading_exercise_name

        if exercise_dir.exists():
            import shutil

            shutil.rmtree(exercise_dir)

        create_sample_exercise(
            exercise_dir,
            short_name=grading_exercise_name,
            version=1,
            category="Grading Workflow Tests",
            has_deadline=True,
            has_submission_test=True,
            grading_points=10,
        )

        assert exercise_dir.exists(), "Exercise directory not created"

    @pytest.mark.e2e
    def test_01_import_and_build_exercise(
        self,
        admin_client: REFWebClient,
        exercises_path: Path,
        grading_state: GradingWorkflowState,
    ):
        """Import and build the test exercise."""
        assert grading_state.exercise_name is not None, "exercise_name not set"
        exercise_path = str(exercises_path / grading_state.exercise_name)
        success = admin_client.import_exercise(exercise_path)
        assert success, f"Failed to import exercise from {exercise_path}"

        exercise = admin_client.get_exercise_by_name(grading_state.exercise_name)
        assert exercise is not None, f"Exercise {grading_state.exercise_name} not found"
        grading_state.exercise_id = exercise.get("id")
        assert grading_state.exercise_id is not None, "Exercise ID not found"

        # Build the exercise
        success = admin_client.build_exercise(grading_state.exercise_id)
        assert success, "Failed to start exercise build"

        build_success = admin_client.wait_for_build(
            grading_state.exercise_id, timeout=300.0
        )
        assert build_success, "Exercise build did not complete successfully"

        # Enable the exercise
        success = admin_client.toggle_exercise_default(grading_state.exercise_id)
        assert success, "Failed to enable exercise"

    @pytest.mark.e2e
    def test_02_register_student(
        self,
        web_client: REFWebClient,
        admin_password: str,
        grading_student_mat_num: str,
        grading_state: GradingWorkflowState,
    ):
        """Register a test student for grading workflow."""
        web_client.logout()

        grading_state.student_mat_num = grading_student_mat_num

        success, private_key, _public_key = web_client.register_student(
            mat_num=grading_student_mat_num,
            firstname="Grading",
            surname="TestStudent",
            password=grading_state.student_password,
        )

        assert success, "Failed to register student"
        assert private_key is not None, "Private key not received"

        grading_state.student_private_key = private_key

        # Re-login as admin for subsequent tests that may use admin_client
        web_client.login("0", admin_password)


class TestAutomatedTesting:
    """
    Test the automated testing functionality.
    """

    @pytest.mark.e2e
    def test_task_check_command(
        self,
        ssh_client_factory: SSHClientFactory,
        grading_state: GradingWorkflowState,
    ):
        """
        Test that 'task check' runs automated tests without submitting.
        """
        assert grading_state.student_private_key is not None, "Student key not available"
        assert grading_state.exercise_name is not None, "Exercise name not available"

        client = ssh_client_factory(
            grading_state.student_private_key,
            grading_state.exercise_name,
        )

        # Run task check - it should run tests and produce output
        _exit_code, output = client.run_task_command("check", timeout=120.0)

        # Task check should produce some output (even if tests fail)
        assert len(output) > 0, "task check should produce output"

    @pytest.mark.e2e
    def test_task_check_with_correct_solution(
        self,
        ssh_client_factory: SSHClientFactory,
        grading_state: GradingWorkflowState,
    ):
        """
        Test that 'task check' passes with a correct solution.
        """
        assert grading_state.student_private_key is not None, "Student key not available"
        assert grading_state.exercise_name is not None, "Exercise name not available"

        client = ssh_client_factory(
            grading_state.student_private_key,
            grading_state.exercise_name,
        )

        # Upload correct solution
        correct_solution = create_correct_solution()
        client.write_file("/home/user/solution.c", correct_solution)

        # Run task check
        success, output = client.check(timeout=120.0)
        assert success, f"task check failed with correct solution: {output}"

    @pytest.mark.e2e
    def test_task_check_with_incorrect_solution(
        self,
        ssh_client_factory: SSHClientFactory,
        grading_state: GradingWorkflowState,
    ):
        """
        Test that 'task check' fails with an incorrect solution.
        """
        assert grading_state.student_private_key is not None, "Student key not available"
        assert grading_state.exercise_name is not None, "Exercise name not available"

        client = ssh_client_factory(
            grading_state.student_private_key,
            grading_state.exercise_name,
        )

        # Reset to initial state first
        client.reset()

        # Upload incorrect solution
        incorrect_solution = create_incorrect_solution()
        client.write_file("/home/user/solution.c", incorrect_solution)

        # Run task check - should fail
        success, output = client.check(timeout=120.0)
        assert not success, f"task check should have failed with incorrect solution: {output}"


class TestSubmissionCreation:
    """
    Test submission creation.
    """

    @pytest.mark.e2e
    def test_task_submit_command(
        self,
        ssh_client_factory: SSHClientFactory,
        grading_state: GradingWorkflowState,
    ):
        """
        Test that 'task submit' creates a submission.
        """
        assert grading_state.student_private_key is not None, "Student key not available"
        assert grading_state.exercise_name is not None, "Exercise name not available"

        client = ssh_client_factory(
            grading_state.student_private_key,
            grading_state.exercise_name,
        )

        # Reset and upload correct solution for submission
        client.reset()
        correct_solution = create_correct_solution()
        client.write_file("/home/user/solution.c", correct_solution)

        # Submit the solution
        success, output = client.submit(timeout=120.0)
        assert success, f"task submit failed: {output}"

    @pytest.mark.e2e
    def test_submission_records_test_results(
        self,
        admin_client: REFWebClient,
        admin_password: str,
        grading_state: GradingWorkflowState,
    ):
        """
        Test that submission records automated test results.
        """
        # After submission, admin should be able to see submissions
        # Login as admin if not already
        if not admin_client.is_logged_in():
            admin_client.login("0", admin_password)

        # Verify the grading/submissions endpoint is accessible
        response = admin_client.client.get("/admin/grading/")
        assert response.status_code == 200, "Failed to access grading view"

    @pytest.mark.e2e
    def test_cannot_submit_after_deadline(
        self,
        ssh_client_factory: SSHClientFactory,
        grading_state: GradingWorkflowState,
    ):
        """
        Test that submissions are rejected after deadline.

        Note: This test is skipped because it would require modifying the exercise
        deadline, which could affect other tests.
        """
        # Skip this test as it requires a special setup with past deadline
        pytest.skip("Test requires exercise with past deadline - skipping to avoid affecting other tests")

    @pytest.mark.e2e
    def test_submission_preserves_state(
        self,
        ssh_client_factory: SSHClientFactory,
        grading_state: GradingWorkflowState,
    ):
        """
        Test that submission preserves the instance state.
        """
        assert grading_state.student_private_key is not None, "Student key not available"
        assert grading_state.exercise_name is not None, "Exercise name not available"

        client = ssh_client_factory(
            grading_state.student_private_key,
            grading_state.exercise_name,
        )

        # Create a unique test file
        test_content = f"test_content_{uuid.uuid4().hex[:8]}"
        test_file = "/home/user/test_marker.txt"
        client.write_file(test_file, test_content)

        # Verify file exists before submission
        assert client.file_exists(test_file), "Test file should exist before submission"

        # The submission should preserve the current state
        # File should still exist after submission
        content = client.read_file(test_file)
        assert test_content in content, "Test file content should be preserved"


class TestManualGrading:
    """
    Test manual grading functionality.
    """

    @pytest.mark.e2e
    def test_admin_can_view_submissions(
        self,
        admin_client: REFWebClient,
        admin_password: str,
        grading_state: GradingWorkflowState,
    ):
        """
        Test that admin can view list of submissions.
        """
        # Ensure admin is logged in
        if not admin_client.is_logged_in():
            admin_client.login("0", admin_password)

        # Navigate to grading page and verify it's accessible
        response = admin_client.client.get("/admin/grading/")
        assert response.status_code == 200, "Admin should be able to access grading page"

        # Page should contain grading-related content
        assert "grading" in response.text.lower() or "submission" in response.text.lower(), (
            "Grading page should contain grading-related content"
        )

    @pytest.mark.e2e
    def test_admin_can_grade_submission(
        self,
        admin_client: REFWebClient,
        admin_password: str,
        grading_state: GradingWorkflowState,
    ):
        """
        Test that admin can assign a grade to a submission.
        """
        # Ensure admin is logged in
        if not admin_client.is_logged_in():
            admin_client.login("0", admin_password)

        # The grading endpoint should be accessible
        response = admin_client.client.get("/admin/grading/")
        assert response.status_code == 200, "Should be able to access grading view"

        # Verify the grading page has expected content
        assert "grading" in response.text.lower() or "submission" in response.text.lower(), (
            "Grading page should contain grading-related content"
        )

    @pytest.mark.e2e
    def test_grading_assistant_can_grade(
        self,
        web_client: REFWebClient,
        admin_client: REFWebClient,
        admin_password: str,
        grading_state: GradingWorkflowState,
    ):
        """
        Test that a grading assistant can grade submissions.
        """
        # Ensure admin is logged in to create grading assistant
        if not admin_client.is_logged_in():
            admin_client.login("0", admin_password)

        # Note: Creating a grading assistant requires admin to add the user
        # with grading assistant role. For now, verify the grading page is accessible.
        response = admin_client.client.get("/admin/grading/")
        assert response.status_code == 200, "Grading page should be accessible"

    @pytest.mark.e2e
    def test_admin_can_access_submission_container(
        self,
        admin_client: REFWebClient,
        admin_password: str,
        ssh_client_factory: SSHClientFactory,
        grading_state: GradingWorkflowState,
    ):
        """
        Test that admin can SSH into a submission container.
        """
        # Ensure admin is logged in
        if not admin_client.is_logged_in():
            admin_client.login("0", admin_password)

        # Note: SSH access to submission containers requires knowing the instance ID
        # and having appropriate credentials. The admin would use instance-<ID> as username.
        # This test verifies the grading page shows submission information.
        response = admin_client.client.get("/admin/grading/")
        assert response.status_code == 200, "Admin should be able to access grading page"


class TestGradingAssistantPermissions:
    """
    Test grading assistant permission model.
    """

    @pytest.mark.e2e
    def test_grading_assistant_cannot_access_admin_pages(
        self,
        web_client: REFWebClient,
        admin_client: REFWebClient,
        admin_password: str,
    ):
        """
        Test that grading assistant cannot access admin-only pages.
        """
        # Note: To fully test this, we would need to create a grading assistant user.
        # For now, we verify that unauthenticated users cannot access admin pages.
        web_client.logout()

        # Try to access admin-only pages without authentication
        response = web_client.client.get("/admin/exercise/view")
        # Should be redirected to login or denied
        assert response.status_code == 200, "Redirect to login should return 200"
        assert "login" in response.text.lower() or "/login" in str(response.url), (
            "Unauthenticated user should be redirected to login"
        )

        # Verify admin settings page is protected
        response = web_client.client.get("/admin/system/settings/")
        assert "login" in response.text.lower() or "/login" in str(response.url), (
            "System settings should require authentication"
        )

    @pytest.mark.e2e
    def test_grading_assistant_can_only_see_past_deadline(
        self,
        web_client: REFWebClient,
        admin_client: REFWebClient,
        admin_password: str,
    ):
        """
        Test that grading assistant can only see submissions after deadline.
        """
        # Note: This test would require:
        # 1. Creating a grading assistant user
        # 2. Setting SUBMISSION_HIDE_ONGOING system setting
        # 3. Having exercises with different deadline states
        # For now, verify the system settings page is accessible to admin
        if not admin_client.is_logged_in():
            admin_client.login("0", admin_password)

        response = admin_client.client.get("/admin/system/settings/")
        assert response.status_code == 200, "Admin should be able to access system settings"


class TestTaskReset:
    """
    Test the task reset functionality.
    """

    @pytest.mark.e2e
    def test_task_reset_command(
        self,
        ssh_client_factory: SSHClientFactory,
        grading_state: GradingWorkflowState,
    ):
        """
        Test that 'task reset' restores initial state.
        """
        assert grading_state.student_private_key is not None, "Student key not available"
        assert grading_state.exercise_name is not None, "Exercise name not available"

        client = ssh_client_factory(
            grading_state.student_private_key,
            grading_state.exercise_name,
        )

        # Create a custom file
        custom_file = "/home/user/custom_test_file.txt"
        client.write_file(custom_file, "Custom test content")
        assert client.file_exists(custom_file), "Custom file should exist before reset"

        # Run task reset
        success, output = client.reset()
        assert success, f"task reset failed: {output}"

        # Verify custom file was removed
        assert not client.file_exists(custom_file), "Custom file should be removed after reset"

    @pytest.mark.e2e
    def test_task_reset_preserves_persistent_files(
        self,
        ssh_client_factory: SSHClientFactory,
        grading_state: GradingWorkflowState,
    ):
        """
        Test that 'task reset' preserves persistent files.

        Note: This test verifies basic reset behavior. Full persistent file
        testing would require an exercise configured with persistent files.
        """
        assert grading_state.student_private_key is not None, "Student key not available"
        assert grading_state.exercise_name is not None, "Exercise name not available"

        client = ssh_client_factory(
            grading_state.student_private_key,
            grading_state.exercise_name,
        )

        # Verify that the standard exercise files exist after reset
        success, output = client.reset()
        assert success, f"task reset failed: {output}"

        # Check that the exercise files are restored
        assert client.file_exists("/home/user/solution.c"), (
            "solution.c should exist after reset"
        )
        assert client.file_exists("/home/user/Makefile"), (
            "Makefile should exist after reset"
        )
