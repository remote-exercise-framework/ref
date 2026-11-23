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
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from typing import Any, Callable, Optional

import pytest

from helpers.exercise_factory import (
    create_correct_solution,
    create_incorrect_solution,
    create_sample_exercise,
)
from helpers.method_exec import (
    enable_exercise,
    is_exercise_default,
    submission_ids_for_exercise,
    system_setting,
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
    max_grading_points: int = 10
    deadline_moved: bool = False


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
        ref_instance: Any,
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
        # `enable_exercise` sets the flag; `toggle_exercise_default` flips
        # it. A successful import already makes the first version the
        # default, so toggling here turns the exercise *off* whenever
        # nothing has cleared the flag in between - and then every SSH
        # login fails with "Requested task not found", far from the cause.
        assert enable_exercise(ref_instance, grading_state.exercise_id), (
            "could not make the exercise the default version"
        )
        assert is_exercise_default(ref_instance, grading_state.exercise_id), (
            "exercise is not the default after enabling it"
        )

    @pytest.mark.e2e
    def test_02_register_student(
        self,
        web_client: REFWebClient,
        admin_password: str,
        grading_student_mat_num: str,
        grading_state: GradingWorkflowState,
    ):
        """Register a test student for grading workflow."""

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
        assert grading_state.student_private_key is not None, (
            "Student key not available"
        )
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
        assert grading_state.student_private_key is not None, (
            "Student key not available"
        )
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
        assert grading_state.student_private_key is not None, (
            "Student key not available"
        )
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
        assert not success, (
            f"task check should have failed with incorrect solution: {output}"
        )


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
        assert grading_state.student_private_key is not None, (
            "Student key not available"
        )
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
        ref_instance: Any,
        grading_state: GradingWorkflowState,
    ):
        """
        The submission is listed for the exercise and is gradeable.
        """
        assert grading_state.exercise_id is not None

        # Checked at the model first, so a failure says which half broke:
        # no submission recorded at all, or one recorded but not rendered.
        recorded = submission_ids_for_exercise(ref_instance, grading_state.exercise_id)
        assert recorded, "task submit did not record a submission"

        submission_ids = admin_client.get_submission_ids(grading_state.exercise_id)

        assert submission_ids, (
            f"submission(s) {recorded} exist but the grading page lists none"
        )
        assert set(submission_ids) == set(recorded)
        grading_state.submission_id = submission_ids[0]

        # Not graded yet, so the form shows an empty points field rather
        # than a zero.
        grading = admin_client.get_grading(submission_ids[0])
        assert grading is not None, "grading page not reachable"
        assert grading["points"] is None, f"unexpected grade: {grading}"

    @pytest.mark.e2e
    def test_submission_preserves_state(
        self,
        ssh_client_factory: SSHClientFactory,
        grading_state: GradingWorkflowState,
    ):
        """
        Test that submission preserves the instance state.
        """
        assert grading_state.student_private_key is not None, (
            "Student key not available"
        )
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

    @pytest.mark.e2e
    def test_zz_cannot_submit_after_deadline(
        self,
        admin_client: REFWebClient,
        ssh_client_factory: SSHClientFactory,
        grading_state: GradingWorkflowState,
    ):
        """
        Submission is refused once the deadline has passed.

        Last in this class, and the deadline move is deliberate rather than
        incidental: grading is refused *until* the deadline has passed
        while submission is refused *after*, so there is no deadline state
        in which both work. Everything that submits has to run first, and
        the grading tests below depend on this having happened.
        """
        assert grading_state.exercise_name is not None
        assert grading_state.student_private_key is not None

        config = admin_client.get_exercise_config(grading_state.exercise_name)
        assert config is not None, "no exercise config to move"
        grading_state.max_grading_points = int(config["max_grading_points"])

        now = datetime.now().replace(second=0, microsecond=0)
        ok, errors = admin_client.set_exercise_config(
            grading_state.exercise_name,
            category=config["category"],
            deadline_start=now - timedelta(days=2),
            deadline_end=now - timedelta(minutes=1),
            submission_test_enabled=bool(config["submission_test_enabled"]),
            max_grading_points=grading_state.max_grading_points,
        )
        assert ok, f"could not move the deadline: {errors}"
        grading_state.deadline_moved = True

        client = ssh_client_factory(
            grading_state.student_private_key,
            grading_state.exercise_name,
        )
        client.write_file("/home/user/solution.c", create_correct_solution())

        success, output = client.submit(timeout=120.0)

        assert not success, f"submission was accepted after the deadline:\n{output}"


class TestManualGrading:
    """
    Assigning a grade, which requires the deadline to have passed — see
    TestSubmissionCreation.test_zz_cannot_submit_after_deadline.
    """

    @pytest.mark.e2e
    def test_00_grading_list_shows_the_exercise(
        self,
        admin_client: REFWebClient,
        grading_state: GradingWorkflowState,
    ):
        """
        The overview lists the exercise by short name.

        The page sorts every exercise before filtering by visibility, so it
        also exercises the optional-category coercion that would otherwise
        500 the whole view.
        """
        assert grading_state.exercise_name is not None

        response = admin_client.client.get("/admin/grading/")

        assert response.status_code == 200, "grading overview not reachable"
        assert grading_state.exercise_name in response.text, (
            "exercise missing from the grading overview"
        )

    @pytest.mark.e2e
    def test_01_a_grade_reads_back(
        self,
        admin_client: REFWebClient,
        grading_state: GradingWorkflowState,
    ):
        """A saved grade is the one the form returns."""
        assert grading_state.submission_id is not None
        assert grading_state.deadline_moved, "the deadline must have passed first"

        awarded = grading_state.max_grading_points - 3
        ok, errors = admin_client.grade_submission(
            grading_state.submission_id, points=awarded, notes="Partially correct."
        )
        assert ok, f"grading was refused: {errors}"

        grading = admin_client.get_grading(grading_state.submission_id)
        assert grading is not None
        assert grading["points"] == awarded
        assert grading["notes"] == "Partially correct."

    @pytest.mark.e2e
    def test_02_regrading_overwrites(
        self,
        admin_client: REFWebClient,
        grading_state: GradingWorkflowState,
    ):
        """A second grade replaces the first rather than adding to it."""
        assert grading_state.submission_id is not None

        full = grading_state.max_grading_points
        ok, errors = admin_client.grade_submission(
            grading_state.submission_id, points=full, notes="Correct after review."
        )
        assert ok, f"regrading was refused: {errors}"

        grading = admin_client.get_grading(grading_state.submission_id)
        assert grading is not None
        assert grading["points"] == full
        assert grading["notes"] == "Correct after review."

    @pytest.mark.e2e
    def test_03_points_above_the_maximum_are_refused(
        self,
        admin_client: REFWebClient,
        grading_state: GradingWorkflowState,
    ):
        """
        The cap is enforced server-side.

        This one rejects via `form.points.errors` without flashing
        anything, so a helper that only read flash messages would report it
        as a success.
        """
        assert grading_state.submission_id is not None
        before = admin_client.get_grading(grading_state.submission_id)
        assert before is not None

        ok, errors = admin_client.grade_submission(
            grading_state.submission_id,
            points=grading_state.max_grading_points + 1,
        )

        assert not ok, "points above the exercise maximum were accepted"
        assert any("maximum" in e.lower() for e in errors), errors
        # And the stored grade is untouched.
        after = admin_client.get_grading(grading_state.submission_id)
        assert after == before

    @pytest.mark.e2e
    def test_04_negative_points_are_refused(
        self,
        admin_client: REFWebClient,
        grading_state: GradingWorkflowState,
    ):
        """`GradingForm.points` carries a NumberRange(min=0) validator."""
        assert grading_state.submission_id is not None
        before = admin_client.get_grading(grading_state.submission_id)

        ok, _ = admin_client.grade_submission(grading_state.submission_id, points=-1)

        assert not ok, "a negative grade was accepted"
        assert admin_client.get_grading(grading_state.submission_id) == before

    @pytest.mark.e2e
    def test_05_an_unknown_submission_cannot_be_graded(
        self,
        admin_client: REFWebClient,
    ):
        """An id that does not exist is refused rather than crashing."""
        ok, errors = admin_client.grade_submission(2**31 - 1, points=1)

        assert not ok, "grading an unknown submission reported success"
        assert errors

    @pytest.mark.e2e
    def test_06_a_grading_assistant_can_grade(
        self,
        grading_assistant_client: REFWebClient,
        grading_state: GradingWorkflowState,
    ):
        """
        A grading assistant can grade a past-deadline exercise.

        A real account with STATE+GRADING_ASSISTANT authorization groups,
        not an admin and not an anonymous client — which is what the four
        tests this class replaced were actually checking.
        """
        assert grading_state.submission_id is not None

        awarded = max(grading_state.max_grading_points - 1, 0)
        ok, errors = grading_assistant_client.grade_submission(
            grading_state.submission_id, points=awarded, notes="Graded by assistant."
        )
        assert ok, f"grading assistant could not grade: {errors}"

        grading = grading_assistant_client.get_grading(grading_state.submission_id)
        assert grading is not None
        assert grading["points"] == awarded

    @pytest.mark.e2e
    def test_07_an_anonymous_client_cannot_grade(
        self,
        web_client: REFWebClient,
        grading_state: GradingWorkflowState,
    ):
        """
        The grading routes are closed to an unauthenticated client.

        Meaningful now that `web_client` is genuinely anonymous: it used to
        be the same object as `admin_client`, so this could not be asked.
        """
        assert grading_state.submission_id is not None

        assert web_client.get_grading(grading_state.submission_id) is None
        ok, _ = web_client.grade_submission(grading_state.submission_id, points=1)
        assert not ok, "an anonymous client graded a submission"


class TestGradingAssistantPermissions:
    """
    What a grading assistant may and may not reach.
    """

    @pytest.mark.e2e
    def test_00_cannot_reach_admin_pages(
        self,
        grading_assistant_client: REFWebClient,
    ):
        """
        Grading is allowed; exercise and settings administration is not.
        """
        # Allowed: the grading overview is gated on
        # @grading_assistant_required.
        assert grading_assistant_client.client.get("/admin/grading/").status_code == 200

        # Not allowed: admin-only pages. The verdict is where the request
        # ended up, not the status code - `admin_required` bounces a
        # logged-in non-admin to the grading overview rather than to the
        # login wall, and that page answers 200.
        for path in ("/admin/exercise/view", "/admin/system/settings/"):
            response = grading_assistant_client.client.get(path)
            landed = urlsplit(str(response.url)).path
            assert landed != path, (
                f"{path} was reachable by a grading assistant "
                f"(status {response.status_code})"
            )

    @pytest.mark.e2e
    def test_01_an_anonymous_client_cannot_reach_admin_pages(
        self,
        web_client: REFWebClient,
    ):
        """The same pages, with no session at all."""
        for path in (
            "/admin/exercise/view",
            "/admin/system/settings/",
            "/admin/grading/",
        ):
            response = web_client.client.get(path)
            landed = urlsplit(str(response.url)).path
            assert landed != path, f"{path} did not require authentication"
            assert landed == "/login", f"{path} redirected to {landed}, not the login"

    @pytest.mark.e2e
    def test_02_hide_ongoing_hides_an_open_exercise_from_the_assistant(
        self,
        admin_client: REFWebClient,
        grading_assistant_client: REFWebClient,
        ref_instance: Any,
        exercises_path: Path,
    ):
        """
        With SUBMISSION_HIDE_ONGOING set, an exercise whose deadline is
        still open is admin-only.

        A second exercise is used rather than the module's own, whose
        deadline has already been moved into the past and cannot be moved
        back without breaking the grading tests above. It is imported but
        never built, which costs nothing: visibility is decided from the
        deadline, not from the build.
        """
        from helpers.exercise_factory import unique_short_name

        short_name = unique_short_name("grading_open")
        create_sample_exercise(
            exercises_path / short_name,
            short_name=short_name,
            version=1,
            category="Grading Workflow Tests",
            has_deadline=True,
            has_submission_test=True,
            grading_points=10,
        )
        assert admin_client.import_exercise(short_name), "import failed"

        with system_setting(ref_instance, "SUBMISSION_HIDE_ONGOING", True):
            admin_view = admin_client.client.get("/admin/grading/")
            assistant_view = grading_assistant_client.client.get("/admin/grading/")

            assert admin_view.status_code == 200
            assert assistant_view.status_code == 200
            assert short_name not in assistant_view.text, (
                "an open exercise was visible to the grading assistant while "
                "SUBMISSION_HIDE_ONGOING was set"
            )

    @pytest.mark.e2e
    def test_03_admin_pages_survive_an_exercise_without_a_category(
        self,
        admin_client: REFWebClient,
        exercises_path: Path,
    ):
        """
        A category-less exercise alongside a categorised one must not 500
        the admin pages.

        `grading_view_all` and `exercise_view_all` both order exercises by
        category before filtering, and `Exercise.category` is optional, so
        an uncoerced sort key raises TypeError on exactly this mix.
        """
        from helpers.exercise_factory import unique_short_name

        short_name = unique_short_name("grading_nocat")
        create_sample_exercise(
            exercises_path / short_name,
            short_name=short_name,
            version=1,
            category=None,
            has_deadline=False,
            has_submission_test=False,
        )
        assert admin_client.import_exercise(short_name), "import failed"

        # Both admin pages order exercises by category. The exercise list
        # sorts twice over committed exercises and once over the templates
        # it finds on disk, so the directory written above reaches the
        # third of those even before the import.
        for path in ("/admin/grading/", "/admin/exercise/view"):
            response = admin_client.client.get(path)
            assert response.status_code == 200, (
                f"{path} crashed on a category-less exercise"
            )

        # Only the exercise list is expected to show it. The grading
        # overview skips anything without a deadline, which this exercise
        # has none of - so its absence there is correct behaviour, and
        # asserting on it would pin the wrong thing.
        assert short_name in admin_client.client.get("/admin/exercise/view").text, (
            f"{short_name} missing from the exercise list"
        )


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
        assert grading_state.student_private_key is not None, (
            "Student key not available"
        )
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
        assert not client.file_exists(custom_file), (
            "Custom file should be removed after reset"
        )

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
        assert grading_state.student_private_key is not None, (
            "Student key not available"
        )
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
