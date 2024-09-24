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

The automated tests to run are described as a Python file called `submission_tests`. An exemplary file looks like this:

```Python
#!/usr/bin/env python3

# custom imports for this task
from pathlib import Path
from typing import List, Optional

import subprocess


# REQUIRED IMPORTS
import ref_utils as rf
rf.ref_util_install_global_exception_hook()
from ref_utils import print_ok, print_warn, print_err, assert_is_file, assert_is_exec, add_environment_test, add_submission_test, drop_privileges




################################################################

TARGET_BIN = Path("/home/user/shellcode")

@add_environment_test() # type: ignore
def test_environment() -> bool:
    """
    Test whether all files that should be submitted are in place.
    """
    tests_passed = True
    tests_passed &= assert_is_exec(TARGET_BIN)
    return tests_passed


@add_submission_test() # type: ignore
def test_submission() -> bool:
    """
    Test if the submitted code successfully solves the exercise.
    """
    ret, out = rf.run_with_payload(['make', '-B'])
    if ret != 0:
        print_err(f'[!] Failed to build! {out}')
        return False

    (_, _) = rf.run_with_payload([TARGET_BIN], b'ps -p "$$"\n', b'dash', check=True, check_signal=True)

    return True

rf.run_tests()

```

There's a lot going on, so let's dissect this step-by-step. The Python file needs to import ref_utils, which provides two types of tests and various convenience functions.

Functions are converted into either an `environment test` or a `submission test` by using the respective decorator, which registers them. Conceptually, these two types are similar. When testing a submission, first all environment tests are run. If one fails, testing is aborted (and the user informed about the failure). In our example code above, the environment test merely checks whether the student created an executable called `shellcode`. Once all environment tests pass, the submission test(s) will be executed. This two-stage design enables to first test whether all prerequisites are in-place (for example, specific binaries have been compiled) via the environment tests before then checking whether their behavior matches the expected one via the submission tests. A failure in any test will abort the execution of subsequent ones.

When needed, both decorators accept an optional `group: str` argument (e.g., `@add_submission_test(group="task_part_one")`) by which specific tests can be grouped. Grouping allows to run multiple, independent test groups; in particular, a failure in test group "task_part_one" will not abort the running of "task_part_two".


Finally, `submission_tests` needs to call `rf.run_tests()` to execute all registered tests. To avoid leaking critical information (when hitting unexpected conditions in the submission tests themselves), `ref_utils` suppresses error output using `rf.ref_util_install_global_exception_hook()`. The `ref_utils` module provides various convenience functions, such as colored printing (print_err, print_warn, print_ok) or executing binaries with a specific payload (rf.run_with_payload(..)).




## Creating a new exercise

Creating a new exercise is simple. Create a new directory and place a `settings.yml` in it. The `short-name` must be unique (and all other values probably need adapting as well). Place all files that should be copied into the Docker container in your new directory as well. If desired, write `submission_tests`. Et voila, you have created a new exercise than can be imported/built in REF's web interface. Don't forget to bump the version if you change something in the exercise after building it in REF (and then rebuild the exercise).
