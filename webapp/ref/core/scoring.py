"""Scoring helpers for the public scoreboard.

Two concerns live here:

1. `apply_scoring()` — transforms a raw per-submission score into scoreboard
   points according to an `ExerciseConfig.scoring_policy` dict. Supported
   modes: `linear`, `threshold`, `tiered`. The optional `baseline` field is
   accepted (frontend reference line) but has no effect on the transformed
   score.

2. `RANKING_STRATEGIES` — the single source of truth for which ranking
   strategies exist. Both the admin system-settings form and the
   `/api/scoreboard/config` endpoint import from here, so adding a new
   frontend ranking strategy is one dict entry plus one JS file.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from ref.core.logging import get_logger

if TYPE_CHECKING:
    from ref.model import User

log = get_logger(__name__)


RANKING_STRATEGIES: dict[str, str] = {
    "f1_time_weighted": "Formula 1 (time-weighted)",
    "best_sum": "Sum of best per challenge",
}
DEFAULT_RANKING_STRATEGY = "f1_time_weighted"
RANKING_STRATEGY_CHOICES: list[tuple[str, str]] = list(RANKING_STRATEGIES.items())


# Visual presentations of the scoreboard. Each view is a
# (templates/scoreboard/<id>.html, static/js/scoreboard/<id>.js) pair and is
# independent of the ranking strategy — views share utils.js and the
# ranking/*.js modules. Adding a new view is one dict entry + two files.
SCOREBOARD_VIEWS: dict[str, str] = {
    "default": "Default (waves, charts, badges)",
    "minimal": "Minimal (ranking table only)",
}
DEFAULT_SCOREBOARD_VIEW = "default"
SCOREBOARD_VIEW_CHOICES: list[tuple[str, str]] = list(SCOREBOARD_VIEWS.items())


def resolve_scoreboard_view(raw: Optional[str]) -> str:
    """Return `raw` if it names a known view, otherwise the default."""
    if raw and raw in SCOREBOARD_VIEWS:
        return raw
    return DEFAULT_SCOREBOARD_VIEW


def resolve_ranking_mode(raw: Optional[str]) -> str:
    """Return `raw` if it names a known strategy, otherwise the default."""
    if raw and raw in RANKING_STRATEGIES:
        return raw
    return DEFAULT_RANKING_STRATEGY


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


def validate_scoring_policy(policy: Optional[dict[str, Any]]) -> list[str]:
    """Return a list of human-readable errors; empty list means valid."""
    if not policy:
        return []

    errors: list[str] = []
    mode = policy.get("mode")

    if mode in (None, "", "none"):
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
