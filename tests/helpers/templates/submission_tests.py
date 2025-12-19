#!/usr/bin/env python3
"""
Submission tests for the test exercise.

This file is used as a template by exercise_factory.py.
It gets copied into generated test exercises.
"""

from pathlib import Path

import ref_utils as rf

rf.ref_util_install_global_exception_hook()
from ref_utils import (  # noqa: E402
    assert_is_exec,
    environment_test,
    print_err,
    print_ok,
    submission_test,
)

TARGET_BIN = Path("/home/user/solution")


@environment_test()
def test_environment() -> bool:
    """Test whether all required files are in place."""
    return assert_is_exec(TARGET_BIN)


@submission_test()
def test_addition() -> bool:
    """Test addition functionality."""
    # Build the solution
    ret, out = rf.run_with_payload(["make", "-B"])
    if ret != 0:
        print_err(f"[!] Failed to build! {out}")
        return False

    # Test: 2 + 3 = 5
    ret, out = rf.run_with_payload([str(TARGET_BIN), "2", "3"])
    if ret != 0:
        print_err(f"[!] Program returned non-zero exit code: {ret}")
        return False

    if "Result: 5" not in out.decode():
        print_err(f'[!] Expected "Result: 5" but got: {out.decode()}')
        return False

    print_ok("[+] Addition test passed!")
    return True


rf.run_tests()
