"""Public scoreboard JSON consumed by the Vue frontend.

Two endpoints. ``/api/scoreboard/config`` describes every assignment +
challenge. ``/api/scoreboard/submissions`` returns team-grouped,
scoring-policy-transformed submission scores with a per-task breakdown.

Both are gated behind ``SYSTEM_SETTING.SCOREBOARD_ENABLED`` and return 404
when the scoreboard is turned off (avoids leaking the feature's existence).
"""

import typing as ty
from collections import defaultdict

from flask import abort, jsonify
from sqlalchemy.orm import selectinload

from ref import db, limiter, refbp
from ref.core import (
    datetime_to_string,
    score_submission,
    team_identity,
)
from ref.core.logging import get_logger
from ref.model import Exercise, ExerciseConfig, Submission, SystemSettingsManager
from ref.model.enums import ExerciseBuildStatus

log = get_logger(__name__)


def _scoreboard_enabled_or_abort() -> None:
    if not SystemSettingsManager.SCOREBOARD_ENABLED.value:
        abort(404)


def _single_policy_max_points(policy: ty.Optional[dict]) -> ty.Optional[float]:
    """Biggest transformed score a single task policy can award, or None."""
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


def _per_task_max_points(
    per_task_policies: ty.Optional[dict],
) -> ty.Optional[float]:
    """Sum per-task maxima across every configured policy, or None.

    Tasks without a policy (pass-through) or whose policy has no computable
    upper bound don't contribute. Returns None if nothing is computable at
    all — the frontend then falls back to data-driven axis scaling.
    """
    if not per_task_policies:
        return None
    total: float = 0.0
    any_known = False
    for policy in per_task_policies.values():
        maybe = _single_policy_max_points(policy)
        if maybe is not None:
            total += maybe
            any_known = True
    return total if any_known else None


@refbp.route("/api/scoreboard/config", methods=("GET",))
@limiter.limit("120 per minute")
def api_scoreboard_config():
    """Metadata for every assignment/challenge.

    Response shape::

        {
          "course_name": "...",
          "assignments": {
            "<assignment name>": {
              "<short_name>": {
                "start": "DD/MM/YYYY HH:MM:SS",
                "end":   "DD/MM/YYYY HH:MM:SS",
                "per_task_scoring_policies": {
                  "<task_name>": { ... policy dict ... },
                  ...
                },
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
        per_task = cfg.per_task_scoring_policies or {}
        assignments[cfg.category][cfg.short_name] = {
            "start": datetime_to_string(cfg.submission_deadline_start),
            "end": datetime_to_string(cfg.submission_deadline_end),
            "per_task_scoring_policies": per_task,
            "max_points": _per_task_max_points(per_task),
        }

    # Prune assignments that ended up with zero online challenges.
    assignments = {name: ch for name, ch in assignments.items() if ch}

    return jsonify(
        {
            "course_name": SystemSettingsManager.COURSE_NAME.value,
            "assignments": assignments,
        }
    )


def _collect_submissions(*, include_admins: bool) -> dict:
    """Build the challenge -> team -> entries mapping.

    When *include_admins* is ``False``, submissions by admin users are
    silently skipped and submissions before the assignment start time
    are excluded so the public scoreboard only shows student work
    within the configured window.
    """
    scores: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))

    submissions = Submission.query.options(
        selectinload(Submission.submission_test_results)
    ).all()

    for submission in submissions:
        instance = submission.origin_instance
        if instance is None:
            continue
        user = instance.user
        if user is None:
            continue
        if not include_admins and user.is_admin:
            continue
        exercise = instance.exercise
        if exercise is None:
            continue
        cfg = exercise.config
        if cfg is None or cfg.category is None:
            continue

        if not include_admins and cfg.submission_deadline_start:
            if submission.submission_ts < cfg.submission_deadline_start:
                continue

        if not submission.submission_test_results:
            continue

        total, breakdown = score_submission(
            submission.submission_test_results,
            cfg.per_task_scoring_policies,
        )
        if not breakdown:
            continue
        team = team_identity(user)
        scores[exercise.short_name][team].append(
            {
                "ts": datetime_to_string(submission.submission_ts),
                "score": total,
                "tasks": breakdown,
            }
        )

    for challenge in scores.values():
        for entries in challenge.values():
            entries.sort(key=lambda e: e["ts"])

    return scores


@refbp.route("/api/scoreboard/submissions", methods=("GET",))
@limiter.limit("120 per minute")
def api_scoreboard_submissions():
    """Team-grouped submission scores with per-task breakdown.

    Response shape::

        {
          "<short_name>": {
            "<team label>": [
              {
                "ts": "DD/MM/YYYY HH:MM:SS",
                "score": <float>,
                "tasks": {"<task_name>": <float | null>, ...}
              },
              ...
            ]
          }
        }

    ``tasks`` values are ``null`` for tasks whose underlying raw score was
    ``None`` (bool-returning tests). Such tasks contribute 0 to ``score``.

    Submissions by admin users are excluded from the public scoreboard.
    """
    _scoreboard_enabled_or_abort()
    return jsonify(_collect_submissions(include_admins=False))


@refbp.route("/api/scoreboard/submissions/admin", methods=("GET",))
@limiter.limit("120 per minute")
def api_scoreboard_submissions_admin():
    """Admin variant: includes submissions by admin users.

    Requires an authenticated admin session; returns 403 otherwise.
    Same response shape as the public endpoint.
    """
    from flask_login import current_user

    _scoreboard_enabled_or_abort()

    if not current_user.is_authenticated or not current_user.is_admin:
        abort(403)

    return jsonify(_collect_submissions(include_admins=True))
