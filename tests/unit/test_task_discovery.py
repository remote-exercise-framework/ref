"""Unit tests for ref.core.task_discovery.

Covers AST-based extraction of submission-test task names across every
decorator variant found in real exercises (`exercises/*/submission_tests`),
plus pathological inputs (missing file, syntax errors, non-literal args).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ref.core.task_discovery import extract_task_names_from_submission_tests


def _write(tmp_path: Path, source: str) -> Path:
    path = tmp_path / "submission_tests"
    path.write_text(source)
    return path


@pytest.mark.offline
class TestSingleTaskDefault:
    def test_bare_decorator_no_call(self, tmp_path: Path) -> None:
        """`@submission_test` with no parens → default task."""
        path = _write(
            tmp_path,
            """
@submission_test
def f():
    pass
""",
        )
        assert extract_task_names_from_submission_tests(path) == ["default"]

    def test_call_with_no_args(self, tmp_path: Path) -> None:
        """`@submission_test()` with no args → default task."""
        path = _write(
            tmp_path,
            """
@submission_test()
def f():
    pass
""",
        )
        assert extract_task_names_from_submission_tests(path) == ["default"]

    def test_environment_test_counts_as_task(self, tmp_path: Path) -> None:
        """`@environment_test` also registers a task name."""
        path = _write(
            tmp_path,
            """
@environment_test()
def f():
    pass
""",
        )
        assert extract_task_names_from_submission_tests(path) == ["default"]


@pytest.mark.offline
class TestExplicitTaskName:
    def test_positional_string_literal(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            """
@submission_test("coverage")
def f():
    pass
""",
        )
        assert extract_task_names_from_submission_tests(path) == ["coverage"]

    def test_keyword_string_literal(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            """
@submission_test(task_name="coverage")
def f():
    pass
""",
        )
        assert extract_task_names_from_submission_tests(path) == ["coverage"]

    def test_multiple_tasks_sorted_unique(self, tmp_path: Path) -> None:
        """Real exercises/02_mutations shape: two tasks registered via two
        decorated functions. Output must be sorted and deduplicated."""
        path = _write(
            tmp_path,
            """
@environment_test("coverage")
def env_cov():
    pass

@environment_test("crashes")
def env_crash():
    pass

@submission_test("coverage")
def sub_cov():
    pass

@submission_test("crashes")
def sub_crash():
    pass
""",
        )
        assert extract_task_names_from_submission_tests(path) == [
            "coverage",
            "crashes",
        ]

    def test_extended_submission_test_recognized(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            """
@extended_submission_test("bonus")
def f():
    pass
""",
        )
        assert extract_task_names_from_submission_tests(path) == ["bonus"]

    def test_deprecated_add_aliases(self, tmp_path: Path) -> None:
        """Older exercises (e.g. exercises/02_hello_x86) use the deprecated
        `@add_submission_test` / `@add_environment_test` aliases."""
        path = _write(
            tmp_path,
            """
@add_environment_test()
def env():
    pass

@add_submission_test("legacy")
def sub():
    pass
""",
        )
        assert extract_task_names_from_submission_tests(path) == [
            "default",
            "legacy",
        ]

    def test_mixed_default_and_named(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            """
@environment_test()
def env():
    pass

@submission_test("graded")
def sub():
    pass
""",
        )
        assert extract_task_names_from_submission_tests(path) == ["default", "graded"]


@pytest.mark.offline
class TestNonLiteralArgs:
    def test_positional_variable_skipped(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            """
TASK = "dynamic"

@submission_test(TASK)
def f():
    pass
""",
        )
        # Non-literal arg → skip with warning; but since at least one
        # recognized decorator was found, we still return a list — just
        # without this particular task name.
        assert extract_task_names_from_submission_tests(path) == []

    def test_keyword_variable_skipped(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            """
NAME = "x"

@submission_test(task_name=NAME)
def f():
    pass
""",
        )
        assert extract_task_names_from_submission_tests(path) == []

    def test_fstring_skipped(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            """
i = 1

@submission_test(f"task_{i}")
def f():
    pass
""",
        )
        assert extract_task_names_from_submission_tests(path) == []

    def test_mixed_literal_and_non_literal(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            """
NAME = "x"

@submission_test("ok")
def good():
    pass

@submission_test(task_name=NAME)
def bad():
    pass
""",
        )
        assert extract_task_names_from_submission_tests(path) == ["ok"]


@pytest.mark.offline
class TestPathologicalInputs:
    def test_missing_file(self, tmp_path: Path) -> None:
        path = tmp_path / "does_not_exist"
        assert extract_task_names_from_submission_tests(path) == []

    def test_syntax_error(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "def broken(:")
        assert extract_task_names_from_submission_tests(path) == []

    def test_no_decorators_at_all(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            """
def not_a_test():
    return 42
""",
        )
        assert extract_task_names_from_submission_tests(path) == []

    def test_unrelated_decorators_ignored(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            """
@staticmethod
@classmethod
def f():
    pass
""",
        )
        assert extract_task_names_from_submission_tests(path) == []

    def test_async_function(self, tmp_path: Path) -> None:
        """Async test functions should also be picked up."""
        path = _write(
            tmp_path,
            """
@submission_test("async_task")
async def f():
    pass
""",
        )
        assert extract_task_names_from_submission_tests(path) == ["async_task"]


@pytest.mark.offline
class TestAgainstRealExercises:
    """Smoke tests against the real submission_tests files in exercises/."""

    def test_sqlite_generator_single_default(self) -> None:
        path = (
            Path(__file__).resolve().parents[2]
            / "exercises"
            / "01_sqlite_generator"
            / "submission_tests"
        )
        if not path.exists():
            pytest.skip(f"Real exercise fixture not available: {path}")
        assert extract_task_names_from_submission_tests(path) == ["default"]

    def test_mutations_multi_task(self) -> None:
        path = (
            Path(__file__).resolve().parents[2]
            / "exercises"
            / "02_mutations"
            / "submission_tests"
        )
        if not path.exists():
            pytest.skip(f"Real exercise fixture not available: {path}")
        assert extract_task_names_from_submission_tests(path) == [
            "coverage",
            "crashes",
        ]
