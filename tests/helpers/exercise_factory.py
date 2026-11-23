"""
REF Exercise Factory

Creates sample exercises for E2E testing.

Two things to know before adding a builder here.

`ExerciseConfig` is keyed by `short_name` and shared across versions, and
on import an existing config row wins: the YAML's admin values (category,
deadline, grading points) only take effect on the *first* import of a given
`short_name`. Two test modules that reuse a name therefore silently share
one config, and whichever ran first decides it. Mint names with
`unique_short_name()` and nothing has to coordinate.

`ExerciseManager._from_yaml` rejects any key it does not know, so a typo in
a settings dict fails the import rather than being ignored. The accepted
keys are `short-name`, `version`, `entry`, `services`, plus the deprecated
`category`, `deadline`, `submission-test` and `grading-points`.
`grading-points` and `deadline` must both be present or both absent.
"""

import os
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Optional

import yaml

# Path to template files
TEMPLATES_DIR = Path(__file__).parent / "templates"

# Mirrors the webapp's own validation, so a bad name fails here with a
# readable message instead of inside remote_exec.
SHORT_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def unique_short_name(stem: str) -> str:
    """
    Mint a `short_name` no other test will use.

    The only sanctioned way to name an exercise. See the module docstring
    for why a shared name is a problem rather than a style preference.
    """
    suffix = uuid.uuid4().hex[:6]
    name = f"{stem}_{suffix}"
    if not SHORT_NAME_RE.match(name):
        raise ValueError(
            f"{name!r} is not a usable short-name; the stem may only contain "
            "letters, digits, underscores and hyphens"
        )
    return name


def write_exercise(
    exercise_dir: Path,
    settings: Mapping[str, Any],
    files: Optional[Mapping[str, str]] = None,
    submission_tests: Optional[str] = None,
) -> Path:
    """
    Write one exercise definition to disk: `settings.yml`, any payload
    files, and an executable `submission_tests`.

    The single primitive every builder goes through, so the short-name
    validation and the executable bit are applied in one place.

    Args:
        exercise_dir: created if absent; an existing directory is reused
            rather than cleared, so two builders can share a parent.
        settings: the `settings.yml` contents.
        files: filename -> contents, written next to `settings.yml`.
        submission_tests: contents of the `submission_tests` script. Must
            be given when `settings` sets `submission-test: True`.

    Returns:
        The exercise directory.
    """
    short_name = settings.get("short-name")
    if not isinstance(short_name, str) or not SHORT_NAME_RE.match(short_name):
        raise ValueError(
            f"short-name {short_name!r} is missing or invalid; use unique_short_name()"
        )
    if settings.get("submission-test") and submission_tests is None:
        raise ValueError(
            f"{short_name}: submission-test is set but no submission_tests "
            "script was given; the import would fail inside the webapp"
        )

    exercise_dir = Path(exercise_dir)
    exercise_dir.mkdir(parents=True, exist_ok=True)

    with open(exercise_dir / "settings.yml", "w") as f:
        yaml.dump(dict(settings), f, default_flow_style=False)

    for name, contents in (files or {}).items():
        (exercise_dir / name).write_text(contents)

    if submission_tests is not None:
        path = exercise_dir / "submission_tests"
        path.write_text(submission_tests)
        os.chmod(path, 0o755)

    return exercise_dir


def deadline_block(
    start_offset: timedelta = timedelta(days=-1),
    end_offset: timedelta = timedelta(days=30),
) -> dict[str, Any]:
    """
    A `deadline:` mapping offset from now.

    Dates are `datetime.date` objects and times ISO strings, which is what
    the webapp's parser expects after YAML round-tripping.

    The default window is open: submission is refused once the deadline has
    passed, while grading is refused until it has, so a test that needs
    both has to submit first and move the deadline afterwards.
    """
    start = datetime.now() + start_offset
    end = datetime.now() + end_offset
    return {
        "start": {"date": start.date(), "time": start.strftime("%H:%M:%S")},
        "end": {"date": end.date(), "time": end.strftime("%H:%M:%S")},
    }


def create_sample_exercise(
    exercise_dir: Path,
    short_name: str,
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
        short_name: Short name for the exercise (used for SSH). Required,
            and should come from unique_short_name() — see the module
            docstring on ExerciseConfig sharing.
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
        "entry": {
            "files": ["solution.c", "Makefile"],
            "build-cmd": ["chown user:user solution.c"],
        },
    }

    # grading-points and deadline must both be set or neither (webapp validation)
    if has_deadline:
        settings["grading-points"] = grading_points
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
    solution_c = """\
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
"""
    solution_path = exercise_dir / "solution.c"
    with open(solution_path, "w") as f:
        f.write(solution_c)

    # Create Makefile
    makefile = """\
CC = gcc
CFLAGS = -Wall -Wextra -g

all: solution

solution: solution.c
\t$(CC) $(CFLAGS) -o solution solution.c

clean:
\trm -f solution

.PHONY: all clean
"""
    makefile_path = exercise_dir / "Makefile"
    with open(makefile_path, "w") as f:
        f.write(makefile)

    # Create submission_tests if needed
    if has_submission_test:
        submission_tests_template = TEMPLATES_DIR / "submission_tests.py"
        submission_tests = submission_tests_template.read_text()
        submission_tests_path = exercise_dir / "submission_tests"
        submission_tests_path.write_text(submission_tests)
        os.chmod(submission_tests_path, 0o755)

    return exercise_dir


def create_correct_solution() -> str:
    """
    Return a correct solution for the test exercise.

    Returns:
        C source code that passes all tests
    """
    return """\
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
"""


def create_incorrect_solution() -> str:
    """
    Return an incorrect solution for the test exercise.

    Returns:
        C source code that fails the tests
    """
    return """\
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
"""


# =============================================================================
# Multi-task exercise
# =============================================================================

# The stub the student receives: deliberately wrong, so an un-edited
# instance scores zero on both tasks and a test can tell "submitted a
# solution" apart from "submitted the skeleton".
MULTI_TASK_STUB = '''#!/usr/bin/env python3
"""Print the sum of the integers from 1 to N, where N is argv[1]."""

import sys


def triangular(n: int) -> int:
    # TODO: implement
    return 0


if __name__ == "__main__":
    print(triangular(int(sys.argv[1])))
'''

MULTI_TASK_SOLUTION = '''#!/usr/bin/env python3
"""Print the sum of the integers from 1 to N, where N is argv[1]."""

import sys


def triangular(n: int) -> int:
    return n * (n + 1) // 2


if __name__ == "__main__":
    print(triangular(int(sys.argv[1])))
'''

# Only partially correct: right for n <= 4, and prints "None" beyond. That
# gives a first submission something to improve on — it scores part marks
# on `correctness` and nothing on `performance`, because a non-numeric line
# does not count as a handled row.
MULTI_TASK_PARTIAL_SOLUTION = '''#!/usr/bin/env python3
"""Print the sum of the integers from 1 to N, where N is argv[1]."""

import sys

LOOKUP = {1: 1, 2: 3, 3: 6, 4: 10}


def triangular(n: int):
    return LOOKUP.get(n)


if __name__ == "__main__":
    print(triangular(int(sys.argv[1])))
'''

# Rows the `performance` task iterates over. Kept small: each row is one
# subprocess inside the instance container.
MULTI_TASK_DATA = "5\n7\n12\n"

# Raw per-task maxima, matching CORRECTNESS_MAX and PERFORMANCE_MAX in
# templates/submission_tests_multi_task.py. Tests derive expected points
# from these rather than hardcoding numbers, so changing the template
# cannot leave an assertion quietly wrong.
MULTI_TASK_CORRECTNESS_MAX = 60.0
MULTI_TASK_PERFORMANCE_MAX = 40.0
MULTI_TASK_MAX_SCORE = MULTI_TASK_CORRECTNESS_MAX + MULTI_TASK_PERFORMANCE_MAX

# Raw correctness score the partial solution reaches: 4 of 5 cases.
MULTI_TASK_PARTIAL_CORRECTNESS = MULTI_TASK_CORRECTNESS_MAX * 4 / 5

MULTI_TASK_TASK_NAMES = ("correctness", "performance")


def create_multi_task_exercise(
    exercise_dir: Path,
    short_name: str,
    version: int = 1,
    category: str = "Scoring",
    grading_points: int = 10,
    start_offset: timedelta = timedelta(days=-1),
    end_offset: timedelta = timedelta(days=30),
) -> Path:
    """
    An exercise with two independently scored tasks, `correctness` and
    `performance`.

    This is the only builder whose submissions can reach the scoreboard: it
    returns numeric `TestResult` scores, and a submission whose total is 0
    is filtered out of the ranking. See
    templates/submission_tests_multi_task.py for the scoring.

    The payload is Python with a `chown` build step, so it also covers a
    non-C exercise and a `build-cmd` that compiles nothing.

    The deadline window is open by default and starts in the past, which
    `/api/scoreboard/config` requires — it needs both timestamps, and
    submissions made before the window opens are dropped from the public
    submissions endpoint.

    Per-task scoring policies cannot be expressed in YAML at all. Set them
    afterwards with `REFWebClient.set_exercise_config`, after the build and
    after the version has been made default — task names are discovered
    from the `submission_tests` file of the default version, so an earlier
    call finds nothing and silently skips validation.
    """
    settings: dict[str, Any] = {
        "short-name": short_name,
        "version": version,
        "category": category,
        "submission-test": True,
        "grading-points": grading_points,
        "deadline": deadline_block(start_offset, end_offset),
        "entry": {
            "files": ["solution.py", "data.txt"],
            "build-cmd": ["chown user:user solution.py data.txt"],
        },
    }

    template = TEMPLATES_DIR / "submission_tests_multi_task.py"
    return write_exercise(
        exercise_dir,
        settings,
        files={
            "solution.py": MULTI_TASK_STUB,
            "data.txt": MULTI_TASK_DATA,
        },
        submission_tests=template.read_text(),
    )
