"""
E2E Test: SSH welcome banner

The banner the SSH reverse proxy prints at login reports per-instance
state (last submission, deadline). It must describe the state at the
moment the session starts, not the state at the moment the TCP
connection was authenticated:

- OpenSSH connection sharing (``ControlMaster``/``ControlPersist``, used
  by VS Code Remote-SSH among others) authenticates once and runs every
  later session over the same transport.
- A student who submits and then opens a new session must see their
  submission, whether or not a new connection was established.

These tests drive the real ``ssh`` binary, because the banner is only
sent for sessions that requested a PTY.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any, Generator

import pytest

from helpers.exercise_factory import create_correct_solution, create_sample_exercise
from helpers.method_exec import create_user, enable_exercise
from helpers.web_client import REFWebClient

NO_SUBMISSION = "No submission found"
HAS_SUBMISSION = "Last submitted"


@pytest.fixture(scope="module")
def banner_exercise(
    ref_instance: Any,
    admin_client: REFWebClient,
    exercises_path: Path,
) -> Generator[str, None, None]:
    """Build and enable an exercise with a deadline.

    A deadline is required: the banner only reports submission state for
    graded exercises.
    """
    import shutil

    short_name = f"banner_{uuid.uuid4().hex[:6]}"
    exercise_dir = exercises_path / short_name
    if exercise_dir.exists():
        shutil.rmtree(exercise_dir)

    create_sample_exercise(
        exercise_dir,
        short_name=short_name,
        version=1,
        category="Welcome Banner Tests",
        has_deadline=True,
        has_submission_test=True,
        grading_points=10,
    )

    assert admin_client.import_exercise(str(exercise_dir)), "Failed to import exercise"
    exercise = admin_client.get_exercise_by_name(short_name)
    assert exercise is not None, f"Exercise {short_name} not found after import"
    exercise_id = exercise["id"]

    assert admin_client.build_exercise(exercise_id), "Failed to start exercise build"
    assert admin_client.wait_for_build(exercise_id, timeout=600.0), "Build failed"
    assert enable_exercise(ref_instance, exercise_id), "Failed to enable exercise"

    yield short_name

    if exercise_dir.exists():
        shutil.rmtree(exercise_dir)


@pytest.fixture
def student_key(ref_instance: Any) -> Generator[str, None, None]:
    """Create a student and yield the path to their private key."""
    user = create_user(
        ref_instance,
        mat_num=str(uuid.uuid4().int)[:8],
        first_name="Banner",
        surname="Student",
        password="TestPassword123!",
    )
    private_key = user["private_key"]
    assert private_key, "No private key generated for student"

    tmpdir = tempfile.mkdtemp()
    key_path = os.path.join(tmpdir, "id")
    with open(key_path, "w") as f:
        f.write(private_key if private_key.endswith("\n") else private_key + "\n")
    os.chmod(key_path, 0o600)

    yield key_path

    import shutil

    shutil.rmtree(tmpdir, ignore_errors=True)


def _ssh_base(port: int, key_path: str) -> list[str]:
    return [
        "ssh",
        "-p",
        str(port),
        "-i",
        key_path,
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "LogLevel=ERROR",
    ]


def _interactive_session(
    host: str,
    port: int,
    key_path: str,
    exercise: str,
    control_path: str | None = None,
    control_master: bool = False,
    timeout: float = 180.0,
) -> str:
    """Open an interactive (PTY) session and return everything it printed."""
    cmd = _ssh_base(port, key_path) + ["-tt"]
    if control_path is not None:
        if control_master:
            cmd += ["-o", "ControlMaster=yes", "-o", "ControlPersist=180"]
        cmd += ["-o", f"ControlPath={control_path}"]
    cmd.append(f"{exercise}@{host}")

    proc = subprocess.run(
        cmd, input="exit\n", capture_output=True, text=True, timeout=timeout
    )
    return proc.stdout + proc.stderr


def _run(
    host: str,
    port: int,
    key_path: str,
    exercise: str,
    command: str,
    control_path: str | None = None,
    timeout: float = 300.0,
) -> str:
    """Run one command over SSH and return its output."""
    cmd = _ssh_base(port, key_path)
    if control_path is not None:
        cmd += ["-o", f"ControlPath={control_path}"]
    cmd += [f"{exercise}@{host}", command]

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return proc.stdout + proc.stderr


def _close_master(host: str, port: int, control_path: str, exercise: str) -> None:
    subprocess.run(
        ["ssh", "-O", "exit", "-p", str(port), "-o", f"ControlPath={control_path}"]
        + [f"{exercise}@{host}"],
        capture_output=True,
    )


class TestWelcomeBanner:
    """The banner must reflect the state at session start."""

    @pytest.mark.e2e
    def test_banner_reports_submission_on_a_new_connection(
        self,
        ssh_host: str,
        ssh_port: int,
        student_key: str,
        banner_exercise: str,
    ):
        """A fresh login after submitting reports the submission."""
        before = _interactive_session(ssh_host, ssh_port, student_key, banner_exercise)
        assert NO_SUBMISSION in before, (
            f"Expected a pristine instance to report no submission:\n{before}"
        )

        _run(
            ssh_host,
            ssh_port,
            student_key,
            banner_exercise,
            f"cat > /home/user/solution.c <<'EOF'\n{create_correct_solution()}\nEOF",
        )
        submit = _run(
            ssh_host, ssh_port, student_key, banner_exercise, "task submit -y"
        )
        assert "successfully created" in submit, f"task submit failed:\n{submit}"

        after = _interactive_session(ssh_host, ssh_port, student_key, banner_exercise)
        assert NO_SUBMISSION not in after, f"Submission not reported:\n{after}"
        assert HAS_SUBMISSION in after, f"Submission not reported:\n{after}"

    @pytest.mark.e2e
    def test_banner_reports_submission_on_a_shared_connection(
        self,
        ssh_host: str,
        ssh_port: int,
        student_key: str,
        banner_exercise: str,
    ):
        """A submission shows up in later sessions of a shared connection.

        With connection sharing the proxy authenticates once, so a banner
        captured at authentication time would stay stale for as long as
        the master connection lives.
        """
        tmpdir = tempfile.mkdtemp()
        control_path = os.path.join(tmpdir, "cm")
        try:
            before = _interactive_session(
                ssh_host,
                ssh_port,
                student_key,
                banner_exercise,
                control_path=control_path,
                control_master=True,
            )
            assert NO_SUBMISSION in before, (
                f"Expected a pristine instance to report no submission:\n{before}"
            )

            _run(
                ssh_host,
                ssh_port,
                student_key,
                banner_exercise,
                f"cat > /home/user/solution.c <<'EOF'\n{create_correct_solution()}\nEOF",
                control_path=control_path,
            )
            submit = _run(
                ssh_host,
                ssh_port,
                student_key,
                banner_exercise,
                "task submit -y",
                control_path=control_path,
            )
            assert "successfully created" in submit, f"task submit failed:\n{submit}"

            after = _interactive_session(
                ssh_host,
                ssh_port,
                student_key,
                banner_exercise,
                control_path=control_path,
            )
            assert NO_SUBMISSION not in after, (
                f"Banner on the shared connection is stale:\n{after}"
            )
            assert HAS_SUBMISSION in after, (
                f"Banner on the shared connection is stale:\n{after}"
            )
        finally:
            _close_master(ssh_host, ssh_port, control_path, banner_exercise)
            import shutil

            shutil.rmtree(tmpdir, ignore_errors=True)


class TestPtyRequest:
    """`pty-req` is sent with want_reply, so it has to be answered."""

    # Session setup is a handful of round trips; anything beyond this means
    # the client is waiting for a reply that is not coming.
    SETUP_BUDGET_S = 30.0

    @pytest.mark.e2e
    def test_pty_request_is_answered(
        self,
        ssh_host: str,
        ssh_port: int,
        student_key: str,
        banner_exercise: str,
    ):
        """A client that waits for the `pty-req` reply gets a shell.

        paramiko blocks in `get_pty()` until the server answers, with no
        timeout of its own, so the setup runs in a worker thread and the
        test fails on the budget instead of hanging.
        """
        import io
        import threading
        import time

        import paramiko

        with open(student_key) as f:
            pkey = paramiko.RSAKey.from_private_key(io.StringIO(f.read()))

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=ssh_host,
            port=ssh_port,
            username=banner_exercise,
            pkey=pkey,
            timeout=60,
            allow_agent=False,
            look_for_keys=False,
        )

        output: bytes = b""
        failure: list[BaseException] = []
        done = threading.Event()

        def open_interactive_session() -> None:
            nonlocal output
            try:
                transport = client.get_transport()
                assert transport is not None
                channel = transport.open_session(timeout=self.SETUP_BUDGET_S)
                # Blocks until the server replies to pty-req.
                channel.get_pty(term="xterm", width=80, height=24)
                channel.invoke_shell()

                deadline = time.time() + self.SETUP_BUDGET_S
                while time.time() < deadline and b"Hello" not in output:
                    if channel.recv_ready():
                        output += channel.recv(65536)
                    else:
                        time.sleep(0.2)
                channel.close()
            except BaseException as e:  # noqa: BLE001 - reported below
                failure.append(e)
            finally:
                done.set()

        worker = threading.Thread(target=open_interactive_session, daemon=True)
        worker.start()
        try:
            answered = done.wait(timeout=self.SETUP_BUDGET_S * 2)
        finally:
            # Tearing down the transport releases a thread still waiting
            # for a channel request reply.
            client.close()

        assert answered, (
            f"No answer to the interactive session requests within "
            f"{self.SETUP_BUDGET_S * 2:.0f}s — the server is not replying to "
            f"pty-req/shell"
        )
        assert not failure, f"Interactive session failed: {failure[0]!r}"

        text = output.decode(errors="replace")
        assert "Hello" in text, f"No welcome banner on the PTY session:\n{text}"
