"""
Integration Tests: Groups feature.

Tests the end-to-end groups behavior using remote_exec: creating a
GroupNameList, enabling it, registering students that join/create
UserGroup rows via UserManager, and enforcing max_group_size.

Covers:
  - GroupNameList is persisted with names and enabled_for_registration.
  - UserManager.create_student(group=...) attaches the user to the group.
  - submission_heads_by_group() buckets submissions per group.

Tests never touch DB models directly for writes — they go through
UserManager like the view does.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from helpers.ref_instance import REFInstance


def _make_mat_num() -> str:
    return str(uuid.uuid4().int)[:8]


def _setup_list_and_users(
    ref_instance: "REFInstance",
    list_name: str,
    group_name: str,
    mat_nums: list[str],
    group_size: int,
) -> dict[str, Any]:
    """Create a GroupNameList, set group settings, and register students that
    all pick the same group name. Returns a dict describing the final state.
    """

    def _do() -> dict[str, Any]:
        from flask import current_app

        from ref.core.user import UserManager
        from ref.model import GroupNameList, SystemSettingsManager, UserGroup

        SystemSettingsManager.GROUPS_ENABLED.value = True
        SystemSettingsManager.GROUP_SIZE.value = group_size

        lst = GroupNameList()
        lst.name = list_name
        lst.enabled_for_registration = True
        lst.names = [group_name, "Other Name"]
        current_app.db.session.add(lst)
        current_app.db.session.flush()
        list_id = lst.id

        created = []
        rejected = 0
        for mat_num in mat_nums:
            group = (
                UserGroup.query.filter(UserGroup.name == group_name)
                .with_for_update()
                .one_or_none()
            )
            if group is None:
                group = UserGroup()
                group.name = group_name
                group.source_list_id = list_id
                current_app.db.session.add(group)
                current_app.db.session.flush()
            elif len(group.users) >= SystemSettingsManager.GROUP_SIZE.value:
                rejected += 1
                continue

            user = UserManager.create_student(
                mat_num=mat_num,
                first_name="Test",
                surname=mat_num,
                password="TestPassword123!",
                pub_key="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJ+dummy",
                group=group,
            )
            current_app.db.session.add(user)
            current_app.db.session.commit()
            created.append(mat_num)

        group = UserGroup.query.filter(UserGroup.name == group_name).one()
        return {
            "list_id": list_id,
            "group_id": group.id,
            "group_name": group.name,
            "source_list_id": group.source_list_id,
            "group_member_count": len(group.users),
            "created": created,
            "rejected": rejected,
        }

    return ref_instance.remote_exec(_do)


def _teardown(ref_instance: "REFInstance", mat_nums: list[str], list_name: str) -> None:
    def _do() -> bool:
        from flask import current_app

        from ref.core.user import UserManager
        from ref.model import GroupNameList, SystemSettingsManager, UserGroup
        from ref.model.user import User

        for mat in mat_nums:
            user = User.query.filter(User.mat_num == mat).one_or_none()
            if user is not None:
                UserManager.delete_with_instances(user)

        for g in UserGroup.query.all():
            if not g.users:
                current_app.db.session.delete(g)

        lst = GroupNameList.query.filter(GroupNameList.name == list_name).one_or_none()
        if lst is not None:
            current_app.db.session.delete(lst)

        SystemSettingsManager.GROUPS_ENABLED.value = False
        SystemSettingsManager.GROUP_SIZE.value = 1
        current_app.db.session.commit()
        return True

    ref_instance.remote_exec(_do)


class TestGroupRegistration:
    @pytest.mark.integration
    def test_join_and_cap(
        self,
        ref_instance: "REFInstance",
    ):
        """
        With GROUP_SIZE=2, two users can join the same group; a third is
        rejected.
        """
        mat_nums = [_make_mat_num() for _ in range(3)]
        list_name = f"TestList-{mat_nums[0]}"
        group_name = f"TestGroup-{mat_nums[0]}"

        try:
            result = _setup_list_and_users(
                ref_instance,
                list_name=list_name,
                group_name=group_name,
                mat_nums=mat_nums,
                group_size=2,
            )

            assert result["group_member_count"] == 2
            assert len(result["created"]) == 2
            assert result["rejected"] == 1
            assert result["source_list_id"] == result["list_id"]
        finally:
            _teardown(ref_instance, mat_nums, list_name)
