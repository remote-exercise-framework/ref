#!/usr/bin/env python3
"""
Submission tests with two independently scored tasks.

Template used by exercise_factory.create_multi_task_exercise(). Three
things here are deliberate and load-bearing for the tests that use it:

1. Each task returns `TestResult(success, score)` with a numeric score.
   A bool-returning task stores `score=None`, which contributes 0 to the
   submission total, and the SPA's ranking filters teams whose total is 0 —
   so a bool-returning exercise can never appear on the scoreboard.

2. The two tasks have separate environment tests. `performance` needs
   `data.txt`; deleting it must fail that task while `correctness` still
   passes, which is what makes task independence observable.

3. `correctness` does less work when the result is not going to be
   submitted, via `rf.test_result_will_be_submitted()`. That keeps
   `task check` quick and is otherwise untested.

Scores are derived from counting passed cases rather than from timing, so
a loaded test runner cannot change the result.
"""

from pathlib import Path

import ref_utils as rf

rf.ref_util_install_global_exception_hook()
from ref_utils import (  # noqa: E402
    TestResult,
    environment_test,
    print_err,
    print_ok,
    submission_test,
)

SOLUTION = Path("/home/user/solution.py")
DATA = Path("/home/user/data.txt")

# (argument, expected stdout). The quick set is the prefix used by
# `task check`; a submission runs all of them.
CASES = [
    ("1", "1"),
    ("2", "3"),
    ("3", "6"),
    ("4", "10"),
    ("10", "55"),
]
QUICK_CASE_COUNT = 2

# Points per task, so a fully correct submission scores
# CORRECTNESS_MAX + PERFORMANCE_MAX.
CORRECTNESS_MAX = 60.0
PERFORMANCE_MAX = 40.0


@environment_test(task_name="correctness")  # type: ignore[misc]
def test_correctness_environment() -> bool:
    """The solution script has to be there before anything can be run."""
    if not SOLUTION.exists():
        print_err(f"[!] Solution not found: {SOLUTION}")
        return False
    print_ok(f"[+] Solution found: {SOLUTION}")
    return True


@submission_test(task_name="correctness")  # type: ignore[misc]
def test_correctness() -> TestResult:
    """Score in proportion to how many cases produce the right answer."""
    cases = CASES if rf.test_result_will_be_submitted() else CASES[:QUICK_CASE_COUNT]
    if len(cases) < len(CASES):
        print_ok(f"[+] Quick check: running {len(cases)} of {len(CASES)} cases")

    passed = 0
    for arg, expected in cases:
        ret, out = rf.run_with_payload(["python3", str(SOLUTION), arg])
        if ret != 0:
            print_err(f"[!] solution.py exited {ret} for input {arg}")
            continue
        actual = out.decode().strip()
        if actual == expected:
            print_ok(f"[+] {arg} -> {actual}")
            passed += 1
        else:
            print_err(f"[!] {arg} -> expected {expected}, got {actual!r}")

    score = CORRECTNESS_MAX * passed / len(cases)
    print_ok(f"[+] correctness: {passed}/{len(cases)} cases, score {score:.2f}")
    return TestResult(success=passed == len(cases), score=score)


@environment_test(task_name="performance")  # type: ignore[misc]
def test_performance_environment() -> bool:
    """
    The data file is this task's own precondition. Removing it fails
    `performance` and leaves `correctness` untouched.
    """
    if not DATA.exists():
        print_err(f"[!] Data file not found: {DATA}")
        return False
    print_ok(f"[+] Data file found: {DATA}")
    return True


@submission_test(task_name="performance")  # type: ignore[misc]
def test_performance() -> TestResult:
    """Score on how many of the data file's rows the solution handles."""
    rows = [line.strip() for line in DATA.read_text().splitlines() if line.strip()]
    if not rows:
        print_err("[!] Data file is empty")
        return TestResult(success=False, score=0.0)

    handled = 0
    for row in rows:
        ret, out = rf.run_with_payload(["python3", str(SOLUTION), row])
        if ret == 0 and out.decode().strip().isdigit():
            handled += 1

    score = PERFORMANCE_MAX * handled / len(rows)
    print_ok(f"[+] performance: {handled}/{len(rows)} rows, score {score:.2f}")
    return TestResult(success=handled == len(rows), score=score)


# Do NOT call rf.run_tests() here; task.py loads this module and calls it.
