"""Unit tests for ref/core/scoring.py.

Covers the scoring policy transform, the policy validator, the ranking
strategy and view resolvers, and team_identity's group-aware behavior.
"""

from unittest.mock import MagicMock, patch

import pytest

from ref.core.scoring import (
    DEFAULT_RANKING_STRATEGY,
    DEFAULT_SCOREBOARD_VIEW,
    RANKING_STRATEGIES,
    SCOREBOARD_VIEWS,
    apply_scoring,
    resolve_ranking_mode,
    resolve_scoreboard_view,
    team_identity,
    validate_scoring_policy,
)


@pytest.mark.offline
class TestApplyScoring:
    def test_none_policy_passes_through(self):
        assert apply_scoring(0.42, None) == pytest.approx(0.42)

    def test_empty_policy_passes_through(self):
        assert apply_scoring(0.42, {}) == pytest.approx(0.42)

    def test_none_score_becomes_zero(self):
        assert apply_scoring(None, {"mode": "linear", "max_points": 100}) == 0.0

    def test_mode_none_passes_through(self):
        assert apply_scoring(0.5, {"mode": "none"}) == pytest.approx(0.5)

    def test_linear_scales_raw_score(self):
        policy = {"mode": "linear", "max_points": 100}
        assert apply_scoring(0.0, policy) == 0.0
        assert apply_scoring(0.5, policy) == pytest.approx(50.0)
        assert apply_scoring(1.0, policy) == pytest.approx(100.0)

    def test_linear_clamps_to_unit_interval(self):
        policy = {"mode": "linear", "max_points": 100}
        assert apply_scoring(-0.1, policy) == 0.0
        assert apply_scoring(1.5, policy) == pytest.approx(100.0)

    def test_linear_respects_custom_lower_bound(self):
        policy = {"mode": "linear", "max_points": 100, "min_raw": 0.2}
        # below the lower bound → zero points
        assert apply_scoring(0.1, policy) == 0.0
        assert apply_scoring(0.2, policy) == 0.0
        # halfway between lower bound and upper default (0.6) → 50 points
        assert apply_scoring(0.6, policy) == pytest.approx(50.0)
        # at the upper bound → full points
        assert apply_scoring(1.0, policy) == pytest.approx(100.0)

    def test_linear_respects_custom_upper_bound(self):
        policy = {
            "mode": "linear",
            "max_points": 100,
            "min_raw": 0.1,
            "max_raw": 0.6,
        }
        assert apply_scoring(0.1, policy) == 0.0
        assert apply_scoring(0.35, policy) == pytest.approx(50.0)
        assert apply_scoring(0.6, policy) == pytest.approx(100.0)
        # above upper bound clamps to full points
        assert apply_scoring(0.9, policy) == pytest.approx(100.0)

    def test_threshold_binary(self):
        policy = {"mode": "threshold", "threshold": 0.5, "points": 100}
        assert apply_scoring(0.49, policy) == 0.0
        assert apply_scoring(0.50, policy) == pytest.approx(100.0)
        assert apply_scoring(0.99, policy) == pytest.approx(100.0)

    def test_tiered_picks_highest_met(self):
        policy = {
            "mode": "tiered",
            "tiers": [
                {"above": 0.3, "points": 25},
                {"above": 0.6, "points": 50},
                {"above": 0.9, "points": 100},
            ],
        }
        assert apply_scoring(0.2, policy) == 0.0
        assert apply_scoring(0.35, policy) == pytest.approx(25.0)
        assert apply_scoring(0.70, policy) == pytest.approx(50.0)
        assert apply_scoring(0.95, policy) == pytest.approx(100.0)

    def test_tiered_ignores_malformed_entries(self):
        policy = {
            "mode": "tiered",
            "tiers": [
                {"above": 0.3, "points": 25},
                {"oops": True},
                {"above": "not-a-number", "points": 9999},
            ],
        }
        assert apply_scoring(0.5, policy) == pytest.approx(25.0)

    def test_baseline_field_ignored_by_transform(self):
        policy = {"mode": "linear", "max_points": 10, "baseline": 0.013}
        assert apply_scoring(0.5, policy) == pytest.approx(5.0)

    def test_unknown_mode_passes_through(self):
        assert apply_scoring(0.7, {"mode": "bogus"}) == pytest.approx(0.7)


@pytest.mark.offline
class TestValidateScoringPolicy:
    def test_none_is_valid(self):
        assert validate_scoring_policy(None) == []

    def test_empty_is_valid(self):
        assert validate_scoring_policy({}) == []

    def test_mode_none_is_valid(self):
        assert validate_scoring_policy({"mode": "none"}) == []

    def test_linear_requires_max_points(self):
        errs = validate_scoring_policy({"mode": "linear"})
        assert any("max_points" in e for e in errs)

    def test_linear_max_points_must_be_positive(self):
        assert validate_scoring_policy({"mode": "linear", "max_points": 0})
        assert validate_scoring_policy({"mode": "linear", "max_points": -1})
        assert validate_scoring_policy({"mode": "linear", "max_points": 10}) == []

    def test_linear_max_points_must_be_numeric(self):
        errs = validate_scoring_policy({"mode": "linear", "max_points": "foo"})
        assert any("number" in e for e in errs)

    def test_threshold_requires_both_fields(self):
        errs = validate_scoring_policy({"mode": "threshold", "threshold": 0.5})
        assert any("points" in e for e in errs)
        errs = validate_scoring_policy({"mode": "threshold", "points": 10})
        assert any("threshold" in e for e in errs)
        assert (
            validate_scoring_policy(
                {"mode": "threshold", "threshold": 0.5, "points": 10}
            )
            == []
        )

    def test_tiered_requires_non_empty_list(self):
        assert validate_scoring_policy({"mode": "tiered"})
        assert validate_scoring_policy({"mode": "tiered", "tiers": []})

    def test_tiered_validates_each_entry(self):
        errs = validate_scoring_policy({"mode": "tiered", "tiers": [{"above": 0.3}]})
        assert any("points" in e for e in errs)
        errs = validate_scoring_policy(
            {
                "mode": "tiered",
                "tiers": [{"above": "bad", "points": 10}],
            }
        )
        assert any("number" in e for e in errs)
        assert (
            validate_scoring_policy(
                {
                    "mode": "tiered",
                    "tiers": [
                        {"above": 0.3, "points": 25},
                        {"above": 0.9, "points": 100},
                    ],
                }
            )
            == []
        )

    def test_unknown_mode(self):
        errs = validate_scoring_policy({"mode": "bogus"})
        assert any("unknown" in e for e in errs)

    def test_baseline_must_be_numeric(self):
        errs = validate_scoring_policy({"mode": "none", "baseline": "foo"})
        assert any("baseline" in e for e in errs)
        assert validate_scoring_policy({"mode": "none", "baseline": 0.5}) == []


@pytest.mark.offline
class TestResolveMode:
    def test_resolve_ranking_mode_valid(self):
        for key in RANKING_STRATEGIES:
            assert resolve_ranking_mode(key) == key

    def test_resolve_ranking_mode_invalid_falls_back(self):
        assert resolve_ranking_mode(None) == DEFAULT_RANKING_STRATEGY
        assert resolve_ranking_mode("") == DEFAULT_RANKING_STRATEGY
        assert resolve_ranking_mode("nope") == DEFAULT_RANKING_STRATEGY

    def test_resolve_scoreboard_view_valid(self):
        for key in SCOREBOARD_VIEWS:
            assert resolve_scoreboard_view(key) == key

    def test_resolve_scoreboard_view_invalid_falls_back(self):
        assert resolve_scoreboard_view(None) == DEFAULT_SCOREBOARD_VIEW
        assert resolve_scoreboard_view("what") == DEFAULT_SCOREBOARD_VIEW


@pytest.mark.offline
class TestTeamIdentity:
    @staticmethod
    def _make_user(first, last, group_name):
        user = MagicMock()
        user.first_name = first
        user.surname = last
        if group_name is None:
            user.group = None
        else:
            user.group = MagicMock()
            user.group.name = group_name
        return user

    def test_fallback_to_full_name_when_groups_disabled(self):
        user = self._make_user("Ada", "Lovelace", "Analysts")
        with patch("ref.model.SystemSettingsManager") as ssm:
            ssm.GROUPS_ENABLED.value = False
            assert team_identity(user) == "Ada Lovelace"

    def test_uses_group_name_when_enabled(self):
        user = self._make_user("Ada", "Lovelace", "Analysts")
        with patch("ref.model.SystemSettingsManager") as ssm:
            ssm.GROUPS_ENABLED.value = True
            assert team_identity(user) == "Analysts"

    def test_groups_on_but_no_group_falls_back_to_name(self):
        user = self._make_user("Ada", "Lovelace", None)
        with patch("ref.model.SystemSettingsManager") as ssm:
            ssm.GROUPS_ENABLED.value = True
            assert team_identity(user) == "Ada Lovelace"
