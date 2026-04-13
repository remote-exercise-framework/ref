"""
Unit Tests: group-aware helpers on the Exercise model.

These test the pure-Python helpers introduced for group-based grading,
without touching the database.
"""

from types import SimpleNamespace

import pytest

from ref.model.exercise import Exercise


def _user(user_id: int, group_id: int | None) -> SimpleNamespace:
    return SimpleNamespace(id=user_id, group_id=group_id)


@pytest.mark.offline
class TestGroupKey:
    def test_user_with_group_uses_group_bucket(self):
        key = Exercise._group_key(_user(user_id=1, group_id=42))
        assert key == ("g", 42)

    def test_user_without_group_uses_user_bucket(self):
        key = Exercise._group_key(_user(user_id=7, group_id=None))
        assert key == ("u", 7)

    def test_two_users_same_group_share_bucket(self):
        a = Exercise._group_key(_user(user_id=1, group_id=5))
        b = Exercise._group_key(_user(user_id=2, group_id=5))
        assert a == b

    def test_two_users_different_groups_distinct_buckets(self):
        a = Exercise._group_key(_user(user_id=1, group_id=5))
        b = Exercise._group_key(_user(user_id=2, group_id=6))
        assert a != b

    def test_two_ungrouped_users_have_distinct_buckets(self):
        a = Exercise._group_key(_user(user_id=1, group_id=None))
        b = Exercise._group_key(_user(user_id=2, group_id=None))
        assert a != b

    def test_ungrouped_user_not_confused_with_grouped_same_id(self):
        grouped = Exercise._group_key(_user(user_id=3, group_id=3))
        ungrouped = Exercise._group_key(_user(user_id=3, group_id=None))
        assert grouped != ungrouped
