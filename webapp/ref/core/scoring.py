"""Scoring helpers for the public scoreboard.

Two concerns live here:

1. `apply_scoring()` — transforms a single raw task score into scoreboard
   points according to a policy dict. Supported modes: `linear`,
   `threshold`, `tiered`. The optional `baseline` field is accepted
   (frontend reference line) but has no effect on the transformed score.

2. `score_submission()` — applies `apply_scoring()` to each task result
   in a submission using an `ExerciseConfig.per_task_scoring_policies`
   lookup, returning both the total and a per-task breakdown.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional, Sequence

from ref.core.logging import get_logger

if TYPE_CHECKING:
    from ref.model import User
    from ref.model.instance import SubmissionTestResult

log = get_logger(__name__)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def apply_scoring(
    raw_score: Optional[float], policy: Optional[dict[str, Any]]
) -> float:
    """Transform a raw submission score into scoreboard points.

    Pass-through (`raw_score or 0.0`) when no policy is configured, so an
    exercise without a scoring policy simply shows its raw score. Unknown
    modes also pass through with a warning — the scoreboard should never
    crash on a typo in the admin UI.
    """
    raw = float(raw_score) if raw_score is not None else 0.0
    if not policy:
        return raw

    mode = policy.get("mode")
    if mode in (None, "", "none"):
        return raw
    if mode == "discard":
        return 0.0

    if mode == "linear":
        max_points = float(policy.get("max_points", 0))
        lo = float(policy.get("min_raw", 0.0))
        hi = float(policy.get("max_raw", 1.0))
        if hi <= lo:
            return 0.0
        if raw <= lo:
            return 0.0
        return _clamp((raw - lo) / (hi - lo), 0.0, 1.0) * max_points

    if mode == "threshold":
        threshold = float(policy.get("threshold", 0))
        points = float(policy.get("points", 0))
        return points if raw >= threshold else 0.0

    if mode == "tiered":
        tiers = policy.get("tiers") or []
        best = 0.0
        for tier in tiers:
            try:
                above = float(tier["above"])
                tier_points = float(tier["points"])
            except (KeyError, TypeError, ValueError):
                continue
            if raw >= above and tier_points > best:
                best = tier_points
        return best

    log.warning("Unknown scoring mode %r; passing raw score through", mode)
    return raw


def score_submission(
    results: Sequence["SubmissionTestResult"],
    per_task_policies: Optional[dict[str, dict[str, Any]]],
) -> tuple[float, dict[str, Optional[float]]]:
    """Score a submission by applying per-task scoring policies.

    For each `SubmissionTestResult`:
      - The task name is looked up in `per_task_policies`; the matched
        policy (or `None`) is passed to `apply_scoring` together with the
        raw score.
      - Tasks whose raw `score` is `None` (bool-returning tests that
        weren't graded) appear in the breakdown as `None` so consumers
        can distinguish "untested" from "scored 0". They contribute 0
        to the total.
      - Tasks whose policy has `mode == "discard"` are omitted entirely:
        they don't appear in the breakdown and contribute 0 to the
        total. Use this to suppress a task from scoring (e.g. a broken
        or deprecated task) without deleting it from the submission
        test.

    Returns `(total, breakdown)` where `breakdown` maps `task_name` to a
    transformed float or `None`.
    """
    policies = per_task_policies or {}
    total = 0.0
    breakdown: dict[str, Optional[float]] = {}
    for r in results:
        policy = policies.get(r.task_name)
        if policy and policy.get("mode") == "discard":
            continue
        if r.score is None:
            breakdown[r.task_name] = None
            continue
        transformed = apply_scoring(r.score, policy)
        breakdown[r.task_name] = transformed
        total += transformed
    return total, breakdown


def validate_scoring_policy(policy: Optional[dict[str, Any]]) -> list[str]:
    """Return a list of human-readable errors; empty list means valid."""
    if not policy:
        return []

    errors: list[str] = []
    mode = policy.get("mode")

    if mode in (None, "", "none"):
        pass
    elif mode == "discard":
        pass
    elif mode == "linear":
        if "max_points" not in policy:
            errors.append("linear mode requires `max_points`.")
        else:
            try:
                if float(policy["max_points"]) <= 0:
                    errors.append("`max_points` must be > 0.")
            except (TypeError, ValueError):
                errors.append("`max_points` must be a number.")
        lo_raw = policy.get("min_raw", 0.0)
        hi_raw = policy.get("max_raw", 1.0)
        try:
            lo = float(lo_raw)
            hi = float(hi_raw)
        except (TypeError, ValueError):
            errors.append("`min_raw` / `max_raw` must be numbers.")
        else:
            if hi <= lo:
                errors.append("`max_raw` must be greater than `min_raw`.")
    elif mode == "threshold":
        for key in ("threshold", "points"):
            if key not in policy:
                errors.append(f"threshold mode requires `{key}`.")
                continue
            try:
                float(policy[key])
            except (TypeError, ValueError):
                errors.append(f"`{key}` must be a number.")
    elif mode == "tiered":
        tiers = policy.get("tiers")
        if not isinstance(tiers, list) or not tiers:
            errors.append("tiered mode requires a non-empty `tiers` list.")
        else:
            for idx, tier in enumerate(tiers):
                if not isinstance(tier, dict):
                    errors.append(f"tier #{idx + 1} must be an object.")
                    continue
                for key in ("above", "points"):
                    if key not in tier:
                        errors.append(f"tier #{idx + 1} missing `{key}`.")
                        continue
                    try:
                        float(tier[key])
                    except (TypeError, ValueError):
                        errors.append(f"tier #{idx + 1} `{key}` must be a number.")
    else:
        errors.append(f"unknown scoring mode {mode!r}.")

    if "baseline" in policy:
        try:
            float(policy["baseline"])
        except (TypeError, ValueError):
            errors.append("`baseline` must be a number.")

    return errors


def team_identity(user: "User") -> str:
    """Return the label to display in the scoreboard for `user`.

    Uses the user's group name when groups are enabled and the user has
    one, otherwise falls back to their full name. Imported lazily to
    avoid a circular import between `ref.core` and `ref.model`.
    """
    from ref.model import SystemSettingsManager

    if SystemSettingsManager.GROUPS_ENABLED.value and user.group is not None:
        return user.group.name
    return f"{user.first_name} {user.surname}"
