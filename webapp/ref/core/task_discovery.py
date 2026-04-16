"""AST-based discovery of submission-test task names.

Exercises ship a `submission_tests` Python file at
`<exercise.template_path>/submission_tests` that registers test functions
via `@submission_test`, `@environment_test`, and `@extended_submission_test`
decorators from `ref_utils`. Each decorator takes an optional `task_name`
argument (positional or keyword); omitting it defaults to `"default"`
(`ref_utils.decorator.DEFAULT_TASK_NAME`).

This module extracts the set of task names by parsing the file's AST —
no import, no execution, no container spin-up. Used by the exercise
config edit view to populate the per-task scoring policy UI.
"""

from __future__ import annotations

import ast
from pathlib import Path

from ref.core.logging import get_logger

log = get_logger(__name__)


# Decorator callables that register tasks. Includes the deprecated `add_*`
# aliases still present in older exercises (e.g. exercises/02_hello_x86).
_RECOGNIZED_DECORATORS: frozenset[str] = frozenset(
    {
        "submission_test",
        "environment_test",
        "extended_submission_test",
        "add_submission_test",
        "add_environment_test",
        "add_extended_submission_test",
    }
)

# Matches DEFAULT_TASK_NAME in ref-docker-base/ref-utils/ref_utils/decorator.py.
_DEFAULT_TASK_NAME = "default"


def extract_task_names_from_submission_tests(path: Path) -> list[str]:
    """Return the sorted list of task names declared in a submission_tests file.

    Returns an empty list when the file is missing, fails to parse, or
    defines no recognized decorators. Decorators without an explicit
    `task_name` contribute the default name `"default"`. Non-literal
    `task_name` arguments (f-strings, variables, expressions) are skipped
    with a warning — they can't be evaluated statically.
    """
    try:
        source = path.read_text()
    except FileNotFoundError:
        log.info("submission_tests not found at %s", path)
        return []
    except OSError as exc:
        log.warning("Failed to read %s: %s", path, exc)
        return []

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        log.warning("Failed to parse %s: %s", path, exc)
        return []

    task_names: set[str] = set()
    found_any_decorator = False

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if _decorator_name(decorator) not in _RECOGNIZED_DECORATORS:
                continue
            found_any_decorator = True
            if not isinstance(decorator, ast.Call):
                # Bare `@submission_test` (no parens) → default task
                task_names.add(_DEFAULT_TASK_NAME)
                continue
            literal = _literal_task_name(decorator)
            if literal is not None:
                task_names.add(literal)
                continue
            has_task_arg = bool(decorator.args) or any(
                kw.arg == "task_name" for kw in decorator.keywords
            )
            if not has_task_arg:
                # `@submission_test()` with no args → default task
                task_names.add(_DEFAULT_TASK_NAME)
            else:
                log.warning(
                    "Non-literal task_name in decorator at %s:%d — skipping",
                    path,
                    node.lineno,
                )

    if not found_any_decorator:
        return []
    return sorted(task_names)


def _decorator_name(decorator: ast.expr) -> str | None:
    """Return the callable's shortest name for a decorator expression."""
    func = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _literal_task_name(call: ast.Call) -> str | None:
    """Return the literal string `task_name` from a decorator call, or None.

    Returns None both when no `task_name` is given *and* when it's given
    but non-literal. The caller disambiguates using `call.args` / `keywords`.
    """
    if call.args:
        first = call.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return first.value
        return None
    for kw in call.keywords:
        if kw.arg == "task_name":
            if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                return kw.value.value
            return None
    return None
