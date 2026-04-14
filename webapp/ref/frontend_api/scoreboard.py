"""Public scoreboard JSON consumed by the Vue frontend.

Two endpoints. ``/api/scoreboard/config`` describes every assignment +
challenge and the active ranking strategy. ``/api/scoreboard/submissions``
returns team-grouped, scoring-policy-transformed submission scores.

Both are gated behind ``SYSTEM_SETTING.SCOREBOARD_ENABLED`` and return 404
when the scoreboard is turned off (avoids leaking the feature's existence).
"""

import typing as ty
from collections import defaultdict

from flask import abort, jsonify

from ref import db, limiter, refbp
from ref.core import (
    apply_scoring,
    datetime_to_string,
    resolve_ranking_mode,
    team_identity,
)
from ref.core.logging import get_logger
from ref.model import Exercise, ExerciseConfig, Submission, SystemSettingsManager
from ref.model.enums import ExerciseBuildStatus

log = get_logger(__name__)


def _scoreboard_enabled_or_abort() -> None:
    if not SystemSettingsManager.SCOREBOARD_ENABLED.value:
        abort(404)


def _policy_max_points(policy: ty.Optional[dict]) -> ty.Optional[float]:
    """Best-effort "biggest transformed score this policy can award".

    Used by the frontend for axis scaling; falls back to None when the
    policy doesn't expose an obvious upper bound.
    """
    if not policy:
        return None
    mode = policy.get("mode")
    if mode == "linear":
        try:
            return float(policy.get("max_points", 0))
        except (TypeError, ValueError):
            return None
    if mode == "threshold":
        try:
            return float(policy.get("points", 0))
        except (TypeError, ValueError):
            return None
    if mode == "tiered":
        best: float = 0.0
        for tier in policy.get("tiers") or []:
            try:
                pts = float(tier["points"])
            except (KeyError, TypeError, ValueError):
                continue
            if pts > best:
                best = pts
        return best
    return None


@refbp.route("/api/scoreboard/config", methods=("GET",))
@limiter.limit("120 per minute")
def api_scoreboard_config():
    """Metadata for every assignment/challenge plus the active ranking strategy.

    Response shape::

        {
          "ranking_mode": "f1_time_weighted",
          "assignments": {
            "<assignment name>": {
              "<short_name>": {
                "start": "DD/MM/YYYY HH:MM:SS",
                "end":   "DD/MM/YYYY HH:MM:SS",
                "scoring": { ... raw policy dict ... },
                "max_points": <float or null>
              }
            }
          }
        }
    """
    _scoreboard_enabled_or_abort()

    # An ExerciseConfig can exist before any actual Exercise has been
    # imported and made default. Only include "online" exercises —
    # those with a built, default Exercise row that students can
    # actually receive an instance of.
    online_short_names = {
        row[0]
        for row in db.session.query(Exercise.short_name)
        .filter(
            Exercise.build_job_status == ExerciseBuildStatus.FINISHED,
            Exercise.is_default.is_(True),
        )
        .distinct()
        .all()
    }

    # The outer grouping key is `ExerciseConfig.category` — whatever label
    # the admin chose in the exercise config edit form (e.g. "Assignment 1"
    # or "Phase A"). Rendered verbatim by the frontend.
    assignments: dict[str, dict[str, dict]] = defaultdict(dict)
    configs = ExerciseConfig.query.filter(
        ExerciseConfig.category.isnot(None),
    ).all()

    for cfg in configs:
        if not cfg.submission_deadline_start or not cfg.submission_deadline_end:
            continue
        if cfg.short_name not in online_short_names:
            continue
        policy = cfg.scoring_policy or {}
        assignments[cfg.category][cfg.short_name] = {
            "start": datetime_to_string(cfg.submission_deadline_start),
            "end": datetime_to_string(cfg.submission_deadline_end),
            "scoring": policy,
            "max_points": _policy_max_points(policy),
        }

    # Prune assignments that ended up with zero online challenges.
    assignments = {name: ch for name, ch in assignments.items() if ch}

    return jsonify(
        {
            "course_name": SystemSettingsManager.COURSE_NAME.value,
            "ranking_mode": resolve_ranking_mode(
                SystemSettingsManager.SCOREBOARD_RANKING_MODE.value
            ),
            "assignments": assignments,
        }
    )


@refbp.route("/api/scoreboard/submissions", methods=("GET",))
@limiter.limit("20 per minute")
def api_scoreboard_submissions():
    """Team-grouped, scoring-policy-transformed submission scores.

    Response shape::

        {
          "<short_name>": {
            "<team label>": [["DD/MM/YYYY HH:MM:SS", <float>], ...]
          }
        }
    """
    _scoreboard_enabled_or_abort()

    scores: dict[str, dict[str, list[list]]] = defaultdict(lambda: defaultdict(list))

    for submission in Submission.all():
        instance = submission.origin_instance
        if instance is None:
            continue
        exercise = instance.exercise
        if exercise is None:
            continue
        cfg = exercise.config
        if cfg is None or cfg.category is None:
            continue

        test_results = submission.submission_test_results
        if len(test_results) != 1:
            log.warning(
                "Skipping submission %s with %d test results on scoreboard",
                submission.id,
                len(test_results),
            )
            continue

        raw = test_results[0].score
        transformed = apply_scoring(raw, cfg.scoring_policy)
        team = team_identity(instance.user)
        scores[exercise.short_name][team].append(
            [datetime_to_string(submission.submission_ts), transformed]
        )

    for challenge in scores.values():
        for entries in challenge.values():
            entries.sort(key=lambda e: e[0])

    return jsonify(scores)
