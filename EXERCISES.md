# Exercises

Exercises (or _tasks_) describe the task students should work on. From the students' point of view, it is the Docker container the connect to work on a specific task. From the framework's point of view, it is a folder living in the [exercises](./exercises) folder. This folder describes how to generate Docker containers, which files to provide to the students, and what commands to run initially.



## Overview / Configuring an exercise

What an exercise is or how to use it can be best described by taking a look at the mandatory `settings.yml` file specifingy its metadata.

```yml
# This name is used by the students to connect to REF, e.g., ssh example@REFSERVER
short-name: "example"

# Current version of the configuration file (and thus, the exercise)
# IMPORTANT: This version must be bumped whenver a file is changed. REF only allows to build newer versions to
# track whether students are upgraded correctly.
version: 3

# The deadline describes the submission period (after the deadline, students can no longer submit)
# - start should be some date before the exercise goes live
# - end should correspond to the desired submission deadline
deadline:
    start:
        date: 2023-11-01
        time: "11:59:59"
    end:
        date: 2023-11-28
        time: "23:59:59"

# Category can be used to group tasks by specific assignments, e.g., the first week of the course may contain
# four exercises that should be grouped in the UI under "Assignment 1"
category: "Assignment 1"
# Whether automated tests exists that verify the solution of students
# CAUTION: Setting this to True requires to create a Python file `submission_tests`
submission-test: True
# How many points a student can obtain by successfully solving this exercise. Points are visible to grading
# assistants when using the REF web interface for grading
grading-points: 8

# The following data describes the files placed in the user's home directory (when connecting to their container)
# and the setup process
entry:
    # Files to copy into the container during creation (to /home/user). This example expects a user to write C code in solution.c, a
    # template provided to them, and provides a makefile to build their code.
    files:
        - solution.c
        - Makefile

    # Commands to run during building the Docker container (after copying files into the container). Working directory is /home/user.
    # Files are by default owned by root. Thus, in this example, we wish to give the user access to solution.c and chown it.
    build-cmd:
        - chown user:user solution.c

    # For executables listed here, ASLR is disabled, even if its a setuid binary.
    # This feature only works if the custom kernel (see README.md) is used.
    no-randomize:
        solution

    # TODO: Document ressource_limit, flag, 
```

## Automated Solution Checking

To ease your work and aid the students during solving the exercises, REF allows to configure automated solution checking, called `submission_tests`.

> [!NOTE]
> Automated solution checking requires to set `submission-test: True` in `settings.yml`

The automated tests to run are described as a Python file called `submission_tests`. The simplest form returns a boolean indicating pass/fail:

```Python
#!/usr/bin/env python3

from pathlib import Path
import ref_utils as rf

rf.ref_util_install_global_exception_hook()
from ref_utils import print_ok, print_err, assert_is_file, assert_is_exec, environment_test, submission_test

################################################################

TARGET_BIN = Path("/home/user/shellcode")

@environment_test()  # type: ignore
def test_environment() -> bool:
    """Check whether all required files are in place."""
    tests_passed = True
    tests_passed &= assert_is_exec(TARGET_BIN)
    return tests_passed


@submission_test()  # type: ignore
def test_submission() -> bool:
    """Check if the submitted code successfully solves the exercise."""
    ret, out = rf.run_with_payload(['make', '-B'])
    if ret != 0:
        print_err(f'[!] Failed to build! {out}')
        return False

    (_, _) = rf.run_with_payload([TARGET_BIN], b'ps -p "$$"\n', b'dash', check=True, check_signal=True)

    return True

rf.run_tests()
```

The Python file imports `ref_utils`, which provides two types of tests and various convenience functions.

Functions are converted into either an `environment test` or a `submission test` by using the respective decorator, which registers them. When testing a submission, first all environment tests are run. If one fails, testing is aborted (and the student informed about the failure). In the example above, the environment test checks whether an executable called `shellcode` exists. Once all environment tests pass, the submission test is executed. This two-stage design lets you first verify prerequisites (e.g., that specific binaries have been compiled) before checking whether their behavior matches the expected one.

When needed, both decorators accept an optional `task_name` argument (e.g., `@submission_test(task_name="part_one")`) by which specific tests can be grouped into independent tasks. A failure in task `"part_one"` will not abort the running of `"part_two"`. Each task can have multiple `@environment_test` functions but only one `@submission_test`.

Finally, `submission_tests` needs to call `rf.run_tests()` to execute all registered tests. To avoid leaking critical information (when hitting unexpected conditions in the submission tests themselves), `ref_utils` suppresses error output using `rf.ref_util_install_global_exception_hook()`. The `ref_utils` module provides various convenience functions, such as colored printing (`print_err`, `print_warn`, `print_ok`) or executing binaries with a specific payload (`rf.run_with_payload(..)`).

### Scored Exercises

The example above uses a boolean return value — the submission either passes or fails. For exercises that need a numeric score (e.g., code coverage percentage, number of tests passed, performance benchmarks), the `@submission_test` function can return a `TestResult` instead of a `bool`.

A `TestResult` carries two fields:

- `success` (`bool`) — whether the submission is considered successful.
- `score` (`float | None`) — the numeric score achieved. This value is recorded per task and displayed on the scoreboard.

Here is a minimal scored example:

```Python
#!/usr/bin/env python3

from pathlib import Path
import ref_utils as rf

rf.ref_util_install_global_exception_hook()
from ref_utils import (
    print_ok,
    print_err,
    assert_is_file,
    environment_test,
    submission_test,
    TestResult,
)

################################################################

SO_PATH = Path("/home/user/libgenerator.so")

@environment_test()  # type: ignore
def test_environment() -> bool:
    return assert_is_file(SO_PATH)  # type: ignore


@submission_test()  # type: ignore
def test_submission() -> TestResult:
    coverage = run_coverage_measurement()  # your scoring logic here
    print_ok(f"[+] You got {coverage:.02f}% coverage")
    return TestResult(success=True, score=coverage)

rf.run_tests()
```

The key differences from a pass/fail test:

1. Import `TestResult` from `ref_utils`.
2. Annotate the `@submission_test` function to return `TestResult` instead of `bool`.
3. Return `TestResult(success=..., score=...)` where `score` is the raw numeric value.

The raw score is stored in the database and shown on the scoreboard. Admins can optionally configure per-task **scoring policies** in the web interface to transform raw scores into final points. The available scoring modes are:

| Mode | Description | Parameters |
|------|-------------|------------|
| `none` (default) | Pass raw score through unchanged | — |
| `linear` | Linearly map a raw score range to points: `(raw - min_raw) / (max_raw - min_raw) * max_points`, clamped to `[0, max_points]` | `min_raw`, `max_raw`, `max_points` |
| `threshold` | Award fixed points if raw score meets a threshold, otherwise 0 | `threshold`, `points` |
| `tiered` | Multiple threshold tiers; the highest matching tier's points are awarded | `tiers` (list of `{above, points}`) |
| `discard` | Omit the task from scoring entirely (contributes 0, hidden from breakdown) | — |

#### Adapting behavior based on check vs. submit

Students can run `task check` (quick feedback loop) or `task submit` (final graded submission). Use `rf.test_result_will_be_submitted()` to detect which mode the test is running in and adjust accordingly (e.g., run a shorter measurement during check, full measurement during submit):

```Python
@submission_test()  # type: ignore
def test_submission() -> TestResult:
    if rf.test_result_will_be_submitted():
        duration = 1800  # 30 minutes for final submission
    else:
        duration = 10  # quick check
    score = run_measurement(duration)
    return TestResult(success=True, score=score)
```

#### Multi-task scored exercises

Exercises with multiple independently scored parts combine `task_name` with `TestResult`:

```Python
@submission_test(task_name="correctness")  # type: ignore
def test_correctness() -> TestResult:
    passed = run_correctness_checks()
    return TestResult(success=passed > 0, score=passed)

@submission_test(task_name="performance")  # type: ignore
def test_performance() -> TestResult:
    throughput = measure_throughput()
    return TestResult(success=True, score=throughput)
```

Each task produces its own `TestResult` and can have its own scoring policy configured in the admin interface. Tasks are independent — a failure in one does not affect the others.




## Creating a new exercise

Creating a new exercise is simple. Create a new directory and place a `settings.yml` in it. The `short-name` must be unique (and all other values probably need adapting as well). Place all files that should be copied into the Docker container in your new directory as well. If desired, write `submission_tests`. Et voila, you have created a new exercise than can be imported/built in REF's web interface. Don't forget to bump the version if you change something in the exercise after building it in REF (and then rebuild the exercise).
