"""
E2E Test: environment of submission tests run by a grader

Programs that submission tests start through `ref_utils.run()` get the
environment of whoever called `task`. In a student's instance that is the
student. In a submission the caller is a grader, so `task check` uses the
environment the student's instance recorded in `/home/user/.user_environ`
instead, unless the grader passes `--caller-env`.

Flow covered here:
1. A student runs `task submit` with a marker variable set.
2. A grading assistant SSHes into the submission (`instance-<id>`) with a
   different value of the marker and runs `task check`.
3. The test program reports which value it saw.
"""

import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest

from helpers.exercise_factory import deadline_block, unique_short_name, write_exercise
from helpers.method_exec import (
    create_grading_assistant,
    enable_exercise,
    submission_ids_for_exercise,
    submitted_instance_id,
    system_setting,
)
from helpers.ssh_client import REFSSHClient
from helpers.web_client import REFWebClient

SSHClientFactory = Callable[[str, str], REFSSHClient]

MARKER = "REF_ENV_MARKER"

# Prints the marker as seen by a program started through `rf.run()`, which
# is the code path whose environment is under test.
SUBMISSION_TESTS = f"""\
#!/usr/bin/env python3
import subprocess

import ref_utils as rf

rf.ref_util_install_global_exception_hook()
from ref_utils import submission_test  # noqa: E402


@submission_test()  # type: ignore[misc]
def report_environment() -> bool:
    p = rf.run(["/usr/bin/printenv", "{MARKER}"], stdout=subprocess.PIPE)
    print("{MARKER} seen by test: <" + p.stdout.decode().strip() + ">")
    return True
"""

_SEEN_RE = re.compile(rf"{MARKER} seen by test: <([^>]*)>")


def _seen_marker(output: str) -> str:
    """The marker value the submission test reported in `output`."""
    match = _SEEN_RE.search(output)
    assert match, f"submission test did not report {MARKER}:\n{output}"
    return match.group(1)


@dataclass
class SubmissionSetup:
    student_marker: str
    submitted_instance_id: int
    grader_private_key: str


@pytest.fixture(scope="module")
def submission_setup(
    exercises_path: Path,
    admin_client: REFWebClient,
    web_client: REFWebClient,
    ref_instance: Any,
    ssh_host: str,
    ssh_port: int,
) -> Iterator[SubmissionSetup]:
    """
    Build an exercise, have a student submit it with a marker set, and
    create a grading assistant who may inspect the submission.
    """
    short_name = unique_short_name("submission_env")
    write_exercise(
        exercises_path / short_name,
        {
            "short-name": short_name,
            "version": 1,
            "category": "Submission Environment Tests",
            "submission-test": True,
            "grading-points": 1,
            "deadline": deadline_block(),
            "entry": {
                "files": ["notes.txt"],
                "build-cmd": ["chown user:user notes.txt"],
            },
        },
        files={"notes.txt": "Nothing to solve here.\n"},
        submission_tests=SUBMISSION_TESTS,
    )

    assert admin_client.import_exercise(str(exercises_path / short_name))
    exercise = admin_client.get_exercise_by_name(short_name)
    assert exercise is not None, f"exercise {short_name} not found after import"
    exercise_id = exercise["id"]
    assert admin_client.build_exercise(exercise_id)
    assert admin_client.wait_for_build(exercise_id, timeout=300.0), "build failed"
    assert enable_exercise(ref_instance, exercise_id)

    mat_num = str(uuid.uuid4().int)[:8]
    registered, student_key, _ = web_client.register_student(
        mat_num=mat_num,
        firstname="Env",
        surname="Student",
        password="TestPassword123!",
    )
    assert registered and student_key is not None, "student registration failed"

    # `task submit` is the student's last `task` run, so the snapshot it
    # writes is the one persisted into the submission.
    student_marker = f"student-{uuid.uuid4().hex[:8]}"
    student = REFSSHClient(ssh_host, ssh_port)
    student.connect(student_key, short_name)
    try:
        exit_code, stdout, stderr = student.execute_with_input(
            f"{MARKER}={student_marker} task submit", "y\n", timeout=120.0
        )
    finally:
        student.close()
    output = stdout + stderr
    assert exit_code == 0 and "successfully created" in output.lower(), output
    assert _seen_marker(output) == student_marker

    submission_ids = submission_ids_for_exercise(ref_instance, exercise_id)
    assert len(submission_ids) == 1, f"expected one submission: {submission_ids}"

    grader = create_grading_assistant(
        ref_instance,
        mat_num=str(uuid.uuid4().int)[:8],
        first_name="Env",
        surname="Grader",
        password="GradingAssistant123!",
    )

    # Pinned rather than relying on the defaults: a grading assistant may
    # only inspect a submission when introspection is on and ongoing
    # submissions are not hidden, and the deadline here is still open.
    with (
        system_setting(ref_instance, "INSTANCE_SSH_INTROSPECTION", True),
        system_setting(ref_instance, "SUBMISSION_HIDE_ONGOING", False),
    ):
        yield SubmissionSetup(
            student_marker=student_marker,
            submitted_instance_id=submitted_instance_id(
                ref_instance, submission_ids[0]
            ),
            grader_private_key=grader["private_key"],
        )


def _grader_task_check(
    ssh_client_factory: SSHClientFactory,
    setup: SubmissionSetup,
    grader_marker: str,
    extra_args: str = "",
) -> str:
    client = ssh_client_factory(
        setup.grader_private_key, f"instance-{setup.submitted_instance_id}"
    )
    exit_code, stdout, stderr = client.execute(
        f"{MARKER}={grader_marker} task check {extra_args}", timeout=120.0
    )
    output = stdout + stderr
    assert exit_code == 0, f"task check failed in the submission:\n{output}"
    return output


@pytest.mark.e2e
class TestGraderEnvironment:
    def test_caller_env_uses_grader_environment(
        self,
        ssh_client_factory: SSHClientFactory,
        submission_setup: SubmissionSetup,
    ):
        """`task check --caller-env` gives tests the grader's environment."""
        grader_marker = f"grader-{uuid.uuid4().hex[:8]}"
        output = _grader_task_check(
            ssh_client_factory, submission_setup, grader_marker, "--caller-env"
        )
        assert _seen_marker(output) == grader_marker

    def test_default_uses_student_environment(
        self,
        ssh_client_factory: SSHClientFactory,
        submission_setup: SubmissionSetup,
    ):
        """
        Plain `task check` in a submission gives tests the student's
        environment.

        Runs after the `--caller-env` test, so it also shows that a grader's
        `task` run does not overwrite the student's snapshot.
        """
        grader_marker = f"grader-{uuid.uuid4().hex[:8]}"
        output = _grader_task_check(ssh_client_factory, submission_setup, grader_marker)
        seen = _seen_marker(output)
        assert seen == submission_setup.student_marker
        assert seen != grader_marker
