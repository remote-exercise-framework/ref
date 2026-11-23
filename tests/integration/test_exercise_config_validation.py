"""
Integration Test: what the exercise config parser accepts and refuses.

`ExerciseManager._from_yaml` is the gate every exercise definition passes
through, and it is strict on purpose: an unknown key is an error rather
than something silently ignored, so a typo in a `settings.yml` cannot
quietly disable a limit an exercise was relying on.

None of this needs a docker build. `ExerciseManager.from_template()` parses
the definition and neither copies it nor adds it to the session, so an
invalid definition leaves no trace and a valid one is discarded — which is
what makes a table of nineteen broken configs cheap to run.

Settings are written here rather than through `helpers.exercise_factory`,
because the factory deliberately refuses some of these shapes itself.
Those guards are tested separately at the bottom of this file.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest
import yaml

from helpers.exercise_factory import deadline_block
from helpers.method_exec import (
    max_peripheral_services,
    parse_exercise_template,
    template_warnings,
)
from helpers.ref_instance import REFInstance

# Exercises are bind-mounted here inside the web container.
CONTAINER_EXERCISES_DIR = "/exercises"

# A minimal definition that parses. Every invalid variant below is this
# with one thing changed, so a failure points at that one thing.
MINIMAL_ENTRY: Dict[str, Any] = {"files": ["solution.py"]}


def _write(exercises_path: Path, settings: Dict[str, Any], **files: str) -> str:
    """
    Write a settings.yml (plus any extra files) to a fresh directory.

    Returns the path *inside the container*, which is what the parser is
    given.
    """
    name = f"cfgval_{uuid.uuid4().hex[:8]}"
    directory = exercises_path / name
    directory.mkdir(parents=True)
    with open(directory / "settings.yml", "w") as f:
        yaml.dump(settings, f, default_flow_style=False)
    for filename, contents in files.items():
        (directory / filename).write_text(contents)
    return f"{CONTAINER_EXERCISES_DIR}/{name}"


def _base(**overrides: Any) -> Dict[str, Any]:
    """The minimal valid settings, with top-level keys replaced."""
    settings: Dict[str, Any] = {
        "short-name": f"cfgval_{uuid.uuid4().hex[:6]}",
        "version": 1,
        "entry": dict(MINIMAL_ENTRY),
    }
    settings.update(overrides)
    return settings


def _entry(**overrides: Any) -> Dict[str, Any]:
    """The minimal valid settings with keys added to the entry section."""
    settings = _base()
    settings["entry"] = {**MINIMAL_ENTRY, **overrides}
    return settings


class TestValidBaseline:
    """
    The baseline has to parse, or every rejection below could be passing
    for the wrong reason.
    """

    def test_minimal_config_parses(
        self, ref_instance: REFInstance, exercises_path: Path
    ) -> None:
        settings = _base()
        path = _write(exercises_path, settings, **{"solution.py": "print(1)\n"})

        ok, message = parse_exercise_template(ref_instance, path)

        assert ok, f"the baseline must parse, got: {message}"
        assert message == settings["short-name"]

    def test_a_dot_is_allowed_in_a_short_name(
        self, ref_instance: REFInstance, exercises_path: Path
    ) -> None:
        # The regex is ([a-zA-Z0-9._])*, so a dot is fine and a hyphen is
        # not. Worth pinning, because it is the opposite of what the
        # service-name rule allows.
        settings = _base(**{"short-name": "cfgval.dotted"})
        path = _write(exercises_path, settings)

        ok, message = parse_exercise_template(ref_instance, path)

        assert ok, message

    def test_the_deprecated_admin_keys_parse_with_a_warning(
        self, ref_instance: REFInstance, exercises_path: Path
    ) -> None:
        # category/deadline/submission-test/grading-points moved to the web
        # interface. They still work on a first import, and say so.
        settings = _base(
            category="Validation",
            deadline=deadline_block(),
            **{"grading-points": 10},
        )
        path = _write(exercises_path, settings)

        warnings = template_warnings(ref_instance, path)

        assert any("deprecated" in w for w in warnings), warnings
        combined = " ".join(warnings)
        for key in ("category", "deadline", "grading-points"):
            assert key in combined, f"{key} not named in {warnings}"


def _invalid_variants(service_cap: int) -> List[Tuple[str, Dict[str, Any], str]]:
    """
    Every rejection, as (name, settings, expected message fragment).

    Built as a function rather than a module constant because the
    peripheral-service cap is read from the webapp.
    """
    too_many_services = {
        f"svc{i}": {"cmd": ["/bin/sleep", "infinity"]} for i in range(service_cap + 1)
    }

    past = deadline_block()
    inverted = {"start": past["end"], "end": past["start"]}

    return [
        # --- top level ---
        (
            "unknown top-level key",
            _base(**{"not-a-real-key": True}),
            "Unknown attribute(s)",
        ),
        (
            "hyphen in short-name",
            _base(**{"short-name": "cfgval-hyphen"}),
            "is invalid",
        ),
        (
            "missing version",
            {k: v for k, v in _base().items() if k != "version"},
            'Missing required attribute "version"',
        ),
        (
            "version is not an integer",
            _base(version="1"),
            'Type of attribute "version"',
        ),
        (
            "no entry section",
            {k: v for k, v in _base().items() if k != "entry"},
            'An exercise must have exactly one "entry" section',
        ),
        # --- deprecated admin keys, which must stay consistent ---
        (
            "grading-points without a deadline",
            _base(**{"grading-points": 10}),
            'Either both or none of "grading-points" and "deadline" must be set',
        ),
        (
            "deadline without grading-points",
            _base(deadline=deadline_block()),
            'Either both or none of "grading-points" and "deadline" must be set',
        ),
        (
            "deadline missing its end",
            _base(
                deadline={"start": deadline_block()["start"]},
                **{"grading-points": 10},
            ),
            'Missing "start:" or "end:" in deadline entry!',
        ),
        (
            "deadline start after its end",
            _base(deadline=inverted, **{"grading-points": 10}),
            "Deadline start must be smaller then deadline end.",
        ),
        (
            "submission-test enabled with no script",
            _base(**{"submission-test": True}),
            "Missing submission_tests file!",
        ),
        # --- entry service ---
        (
            "deprecated disable-aslr",
            _entry(**{"disable-aslr": True}),
            '"disable-aslr" attribute is deprecated',
        ),
        (
            "read-only alongside a persistance path",
            # No persistance-path is given: it defaults to /home/user, so
            # read-only alone is already a contradiction.
            _entry(**{"read-only": True}),
            "persistance-path and readonly are mutually exclusive",
        ),
        (
            "unknown key in the entry section",
            _entry(**{"nonsense": 1}),
            "Unknown attribute(s) in entry service configuration",
        ),
        (
            "files is not a list of strings",
            _entry(files=[1]),
            "files must be a list of strings",
        ),
        # --- resource limits ---
        (
            "phys-mem below the floor",
            _entry(limits={"phys-mem": "32MiB"}),
            "Memory limits must be greater or equal to 64 MiB.",
        ),
        (
            "phys-mem in MB rather than MiB",
            _entry(limits={"phys-mem": "512MB"}),
            'Please use "GiB" or "MiB" as suffix!',
        ),
        (
            "cpu-cnt-max with too many decimals",
            _entry(limits={"cpu-cnt-max": 1.234}),
            "No more than 2 decimal places are supported.",
        ),
        (
            "unknown key in the limits section",
            _entry(limits={"phys-mem": "128MiB", "ram": "lots"}),
            "Unknown attribute(s) in limits configuration",
        ),
        # --- peripheral services ---
        (
            "more services than the subnet allows",
            _base(services=too_many_services),
            "Too many peripheral services",
        ),
        (
            "service without a cmd",
            _base(services={"helper": {"files": ["x"]}}),
            'Missing required attribute "cmd"',
        ),
        (
            "dot in a service name",
            _base(services={"my.helper": {"cmd": ["/bin/true"]}}),
            "is invalid",
        ),
    ]


class TestInvalidConfigs:
    """
    One test, looping the table. A loop rather than `parametrize` because
    this module stays runnable whole alongside the e2e files, whose
    collection guard rejects a `::` selector.
    """

    def test_every_invalid_config_is_refused(
        self, ref_instance: REFInstance, exercises_path: Path
    ) -> None:
        cap = max_peripheral_services(ref_instance)
        assert cap > 0, "the webapp reported a nonsensical service cap"

        failures: List[str] = []
        for name, settings, expected in _invalid_variants(cap):
            path = _write(exercises_path, settings)
            ok, message = parse_exercise_template(ref_instance, path)

            if ok:
                failures.append(f"{name}: accepted, expected {expected!r}")
            elif expected not in message:
                failures.append(f"{name}: expected {expected!r}, got {message!r}")

        assert not failures, "Config validation gaps:\n  " + "\n  ".join(failures)


class TestFactoryGuards:
    """
    The test factory refuses two shapes before they ever reach the webapp,
    so a broken definition fails locally with a readable message rather
    than inside remote_exec.
    """

    def test_a_hyphenated_short_name_is_refused_locally(
        self, exercises_path: Path
    ) -> None:
        from helpers.exercise_factory import write_exercise

        with pytest.raises(ValueError, match="short-name"):
            write_exercise(
                exercises_path / f"guard_{uuid.uuid4().hex[:6]}",
                _base(**{"short-name": "has-a-hyphen"}),
            )

    def test_submission_test_without_a_script_is_refused_locally(
        self, exercises_path: Path
    ) -> None:
        from helpers.exercise_factory import write_exercise

        with pytest.raises(ValueError, match="submission_tests"):
            write_exercise(
                exercises_path / f"guard_{uuid.uuid4().hex[:6]}",
                _base(**{"submission-test": True}),
            )
