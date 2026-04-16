#!/usr/bin/env python3

import argparse
import importlib.machinery
import importlib.util
import logging
from logging.handlers import RotatingFileHandler
import os
import sys
import traceback
import typing as ty
import shutil
from pathlib import Path
from dataclasses import asdict

import requests
from itsdangerous import TimedSerializer

from ref_utils import (
    InstanceInfoError,
    TaskTestResult,
    get_instance_info,
    print_err,
    print_ok,
    print_warn,
)
from ref_utils.decorator import run_tests, suppress_run_tests

with open("/etc/key", "rb") as f:
    KEY = f.read()

with open("/etc/instance_id", "r") as f:  # type: ignore
    INSTANCE_ID = int(f.read())

IS_SUBMISSION = os.path.isfile("/etc/is_submission")
MAX_TEST_OUTPUT_LENGTH = 1024 * 64

_LOG_PATH = "/var/log/ref-task.log"


class _SecureRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler that enforces 0600 permissions on every file it creates."""

    def _open(self):
        old = os.umask(0o077)
        try:
            return super()._open()
        finally:
            os.umask(old)


_error_logger = logging.getLogger("ref.task")
_error_logger.setLevel(logging.ERROR)
_log_handler = _SecureRotatingFileHandler(
    _LOG_PATH, maxBytes=1024 * 1024, backupCount=1
)
_log_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
_error_logger.addHandler(_log_handler)


def finalize_request(req):
    signer = TimedSerializer(KEY, salt="from-container-to-web")
    req["instance_id"] = INSTANCE_ID
    req = signer.dumps(req)
    return req


def server_post(url: str, **kwargs) -> requests.Response:
    """POST to the submission server, handling connection errors gracefully."""
    try:
        return requests.post(url, **kwargs)
    except requests.exceptions.RequestException:
        _error_logger.error("Request to %s failed:\n%s", url, traceback.format_exc())
        print_err("[!] Failed to connect to the submission server.")
        print_err(
            "[!] Please try again later. If this problem persists, contact a supervisor."
        )
        exit(1)


def handle_response(resp, expected_status=(200,)) -> ty.Tuple[int, ty.Dict]:
    """
    Process a response of a "requests" request.
    If the response has a status code not in expected_status,
    the program is terminated and an error message is displayed
    to the user. If the status code is in expected_status and the
    response contains a JSON body, a tuple status_code, json_body
    is returned.
    """
    status_code = resp.status_code
    json = None

    json_error = None
    try:
        json = resp.json()
    except ValueError:
        json_error = f"[!] Missing JSON body (status={status_code})"
    except Exception:
        json_error = f"[!] Internal Error (status={status_code})"

    if json_error:
        # Answers always have to contain JSON
        print_err(json_error)
        exit(1)

    if status_code in expected_status:
        return status_code, json
    else:
        if "error" in json:
            print_err("[!]", json["error"])
        else:
            print_err("[!]", "Unknown error! Please contact the staff")
        exit(1)


def user_answered_yes(prompt=None):
    if prompt:
        print(prompt, end="")
    try:
        data = input()
    except EOFError:
        print_err("[!] No answer provided, exiting.")
        exit(1)
    data = data.lower()
    return data in ["y", "yes", "true"]


def cmd_reset(_):
    print_warn(
        "[!] This operation will revert all modifications.\n    All your data will be lost and you will have to start from scratch!\n    You have been warned."
    )
    print_warn("[!] Are you sure you want to continue? [y/n] ", end="")
    if not user_answered_yes():
        exit(0)

    print_ok(
        "[+] Resetting instance now. In case of success, you will be disconnected from the instance.",
        flush=True,
    )
    req = {}
    req = finalize_request(req)
    res = server_post("http://ssh-reverse-proxy:8000/api/instance/reset", json=req)
    handle_response(res)


def _load_submission_tests_module() -> ty.Any:
    """Load the submission_tests script as a Python module."""
    test_path = Path("/usr/local/bin/submission_tests")
    if not test_path.exists():
        return None

    # Use SourceFileLoader explicitly since the file doesn't have a .py extension
    # (spec_from_file_location returns None for files without Python extensions)
    loader = importlib.machinery.SourceFileLoader("submission_tests", str(test_path))
    spec = importlib.util.spec_from_loader("submission_tests", loader)
    if spec is None:
        return None

    module = importlib.util.module_from_spec(spec)
    sys.modules["submission_tests"] = module
    spec.loader.exec_module(module)
    return module


def _run_tests(
    *,
    result_will_be_submitted: bool = False,
    only_run_these_tasks: ty.Optional[ty.Sequence[str]] = None,
) -> ty.Tuple[str, ty.List[TaskTestResult]]:
    test_path = Path("/usr/local/bin/submission_tests")
    if not test_path.exists():
        print_warn("[+] No testsuite found! Skipping tests..")
        return "No testsuite found! Skipping tests..", []

    # Load submission_tests as a module (this registers tests via decorators).
    # Suppress run_tests() during import to prevent double execution, since
    # some scripts call rf.run_tests() at module level.
    suppress_run_tests(True)
    _load_submission_tests_module()
    suppress_run_tests(False)

    # Capture stdout/stderr during test execution
    from io import StringIO

    captured_output = StringIO()

    class TeeWriter:
        """Write to both stdout and a capture buffer."""

        def __init__(self, original: ty.TextIO, capture: StringIO):
            self.original = original
            self.capture = capture

        def write(self, text: str) -> int:
            self.original.write(text)
            self.capture.write(text)
            return len(text)

        def flush(self) -> None:
            self.original.flush()

    original_stdout = sys.stdout
    original_stderr = sys.stderr
    sys.stdout = TeeWriter(original_stdout, captured_output)  # type: ignore[assignment]
    sys.stderr = TeeWriter(original_stderr, captured_output)  # type: ignore[assignment]

    try:
        test_results = run_tests(
            result_will_be_submitted=result_will_be_submitted,
            only_run_these_tasks=only_run_these_tasks,
        )
    finally:
        sys.stdout = original_stdout
        sys.stderr = original_stderr

    return captured_output.getvalue(), test_results


def cmd_submit(args: argparse.Namespace):
    print_ok("[+] Submitting instance..", flush=True)

    test_output, test_results = _run_tests(result_will_be_submitted=True)
    any_test_failed = any([not t.success for t in test_results])

    if not args.yes:
        if any_test_failed:
            print_warn(
                "[!] Failing tests may indicate that your solution is erroneous or not complete yet."
            )
            print_warn("[!] Are you sure you want to submit? [y/n] ", end="")
            if not user_answered_yes():
                exit(0)
        else:
            print_ok("[+] Are you sure you want to submit? [y/n] ", end="")
            if not user_answered_yes():
                exit(0)

    if len(test_output) > MAX_TEST_OUTPUT_LENGTH:
        print_err(
            f"[!] Test output exceeded maximum length of {MAX_TEST_OUTPUT_LENGTH} characters."
        )
        print_err(
            "[!] Please remove or reduce any unnecessary output (e.g., debug prints) so that"
        )
        print_err(
            "[!] all output of your solution stays within the allowed limit, and try submitting again."
        )
        exit(0)

    print_ok("[+] Submitting now...", flush=True)

    req = {"output": test_output, "test_results": [asdict(e) for e in test_results]}

    req = finalize_request(req)
    res = server_post("http://ssh-reverse-proxy:8000/api/instance/submit", json=req)
    _, ret = handle_response(res)
    print_ok(ret)


def cmd_check(args: argparse.Namespace):
    """
    Run tests and exit with non-zero status if any test fails.
    """
    only_run_these_tasks = args.only_run_these_tasks
    _, test_results = _run_tests(only_run_these_tasks=only_run_these_tasks)
    any_test_failed = any(not t.success for t in test_results)
    if any_test_failed:
        sys.exit(1)


def cmd_id(_):
    print_ok("[+] If you need support, please provide this ID alongside your request.")
    print_ok(f"[+] Instance ID: {INSTANCE_ID}")


def cmd_info(_):
    try:
        info = get_instance_info()
    except InstanceInfoError as e:
        print_err(f"[!] {e}")
        exit(1)

    type_ = "Submission" if info.is_submission else "Instance"
    print(f"Type     : {type_}")
    print(f"User     : {info.user_full_name}")
    print(f"Exercise : {info.exercise_short_name}")
    print(f"Version  : {info.exercise_version}")


def main():
    parser = argparse.ArgumentParser(prog="task")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.required = True

    if not IS_SUBMISSION:
        # Copy the 'snapshotted' user environment stored at /tmp/.user_environ.
        # The `/tmp/.user_environ` file is created by `task-wrapper.c`
        # just before this script is executed.
        p = Path("/home/user/.user_environ")
        if p.exists():
            # Grant permission in case the user messed with `.user_environ`.
            p.chmod(0o777)
            p.unlink()
        shutil.copy("/tmp/.user_environ", "/home/user/.user_environ")

    reset_parser = subparsers.add_parser(
        "reset",
        help="Revert all modifications applied to your instance. WARNING: This cannot be undone; all user data will be lost permanently.",
    )
    reset_parser.set_defaults(func=cmd_reset)

    submit_parser = subparsers.add_parser(
        "submit",
        help="Submit the current state of your work for grading. Your whole instance is submitted.",
    )
    submit_parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip confirmation prompt and submit immediately.",
    )
    submit_parser.set_defaults(func=cmd_submit)

    check_parser = subparsers.add_parser(
        "check",
        help="Run various checks which verify whether your environment and submission match the solution.",
    )
    check_parser.add_argument(
        "only_run_these_tasks",
        metavar="task-name",
        nargs="*",
        help="Only run the checks for the passed `task-name`s",
    )
    check_parser.set_defaults(func=cmd_check)

    id_parser = subparsers.add_parser(
        "id", help="Get your instance ID. This ID is needed for all support requests."
    )
    id_parser.set_defaults(func=cmd_id)

    info_parser = subparsers.add_parser(
        "info", help="Get various details of this instance."
    )
    info_parser.set_defaults(func=cmd_info)

    # diff_parser = subparsers.add_parser('diff',
    #     help='Get your instance ID. This ID is needed for all support requests.'
    #     )
    # diff_parser.set_defaults(func=cmd_diff)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
