"""
REF Exercise Factory

Creates sample exercises for E2E testing.
"""

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml


def create_sample_exercise(
    exercise_dir: Path,
    short_name: str = "test_exercise",
    version: int = 1,
    category: str = "Test Category",
    has_deadline: bool = True,
    has_submission_test: bool = True,
    grading_points: int = 10,
) -> Path:
    """
    Create a sample exercise for testing.

    Args:
        exercise_dir: Directory to create the exercise in
        short_name: Short name for the exercise (used for SSH)
        version: Exercise version number
        category: Exercise category
        has_deadline: Whether to set a deadline
        has_submission_test: Whether to include submission tests
        grading_points: Maximum grading points

    Returns:
        Path to the exercise directory
    """
    exercise_dir = Path(exercise_dir)
    exercise_dir.mkdir(parents=True, exist_ok=True)

    # Calculate deadline dates (use date objects, not strings, for YAML serialization)
    start_date = (datetime.now() - timedelta(days=1)).date()
    end_date = (datetime.now() + timedelta(days=30)).date()

    # Create settings.yml
    settings: dict[str, Any] = {
        "short-name": short_name,
        "version": version,
        "category": category,
        "submission-test": has_submission_test,
        "grading-points": grading_points,
        "entry": {
            "files": ["solution.c", "Makefile"],
            "build-cmd": ["chown user:user solution.c"],
        },
    }

    if has_deadline:
        settings["deadline"] = {
            "start": {
                "date": start_date,  # datetime.date object for proper YAML serialization
                "time": "00:00:00",  # ISO format string (webapp converts via fromisoformat)
            },
            "end": {
                "date": end_date,  # datetime.date object
                "time": "23:59:59",  # ISO format string
            },
        }

    settings_path = exercise_dir / "settings.yml"
    with open(settings_path, "w") as f:
        yaml.dump(settings, f, default_flow_style=False)

    # Create solution.c template
    solution_c = '''\
/*
 * Test Exercise Solution
 *
 * Complete the function below to pass the tests.
 */

#include <stdio.h>
#include <stdlib.h>

int add(int a, int b) {
    // TODO: Implement this function
    return 0;
}

int main(int argc, char *argv[]) {
    if (argc != 3) {
        printf("Usage: %s <a> <b>\\n", argv[0]);
        return 1;
    }

    int a = atoi(argv[1]);
    int b = atoi(argv[2]);

    printf("Result: %d\\n", add(a, b));
    return 0;
}
'''
    solution_path = exercise_dir / "solution.c"
    with open(solution_path, "w") as f:
        f.write(solution_c)

    # Create Makefile
    makefile = '''\
CC = gcc
CFLAGS = -Wall -Wextra -g

all: solution

solution: solution.c
\t$(CC) $(CFLAGS) -o solution solution.c

clean:
\trm -f solution

.PHONY: all clean
'''
    makefile_path = exercise_dir / "Makefile"
    with open(makefile_path, "w") as f:
        f.write(makefile)

    # Create submission_tests if needed
    if has_submission_test:
        submission_tests = '''\
#!/usr/bin/env python3
"""
Submission tests for the test exercise.
"""

from pathlib import Path

import ref_utils as rf
rf.ref_util_install_global_exception_hook()
from ref_utils import (
    print_ok, print_err,
    assert_is_exec,
    environment_test, submission_test
)

TARGET_BIN = Path("/home/user/solution")


@environment_test
def test_environment() -> bool:
    """Test whether all required files are in place."""
    return assert_is_exec(TARGET_BIN)


@submission_test
def test_addition() -> bool:
    """Test addition functionality."""
    # Build the solution
    ret, out = rf.run_with_payload(['make', '-B'])
    if ret != 0:
        print_err(f'[!] Failed to build! {out}')
        return False

    # Test: 2 + 3 = 5
    ret, out = rf.run_with_payload([str(TARGET_BIN), '2', '3'])
    if ret != 0:
        print_err(f'[!] Program returned non-zero exit code: {ret}')
        return False

    if 'Result: 5' not in out.decode():
        print_err(f'[!] Expected "Result: 5" but got: {out.decode()}')
        return False

    print_ok('[+] Addition test passed!')
    return True


rf.run_tests()
'''
        submission_tests_path = exercise_dir / "submission_tests"
        with open(submission_tests_path, "w") as f:
            f.write(submission_tests)
        os.chmod(submission_tests_path, 0o755)

    return exercise_dir


def create_correct_solution() -> str:
    """
    Return a correct solution for the test exercise.

    Returns:
        C source code that passes all tests
    """
    return '''\
#include <stdio.h>
#include <stdlib.h>

int add(int a, int b) {
    return a + b;
}

int main(int argc, char *argv[]) {
    if (argc != 3) {
        printf("Usage: %s <a> <b>\\n", argv[0]);
        return 1;
    }

    int a = atoi(argv[1]);
    int b = atoi(argv[2]);

    printf("Result: %d\\n", add(a, b));
    return 0;
}
'''


def create_incorrect_solution() -> str:
    """
    Return an incorrect solution for the test exercise.

    Returns:
        C source code that fails the tests
    """
    return '''\
#include <stdio.h>
#include <stdlib.h>

int add(int a, int b) {
    return 0;  // Wrong implementation
}

int main(int argc, char *argv[]) {
    if (argc != 3) {
        printf("Usage: %s <a> <b>\\n", argv[0]);
        return 1;
    }

    int a = atoi(argv[1]);
    int b = atoi(argv[2]);

    printf("Result: %d\\n", add(a, b));
    return 0;
}
'''
