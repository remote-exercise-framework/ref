"""
Admin API Security Tests

Tests for /admin/* endpoints permission verification.

Security focus:
- admin_required decorator enforcement
- grading_assistant_required decorator enforcement
- Unauthenticated access rejection
- Parameter validation
"""

from __future__ import annotations

import urllib.parse

import httpx
import pytest


@pytest.mark.api
@pytest.mark.security
class TestAdminExerciseEndpoints:
    """
    Tests for /admin/exercise/* endpoints.

    These endpoints require admin authentication.
    """

    def test_view_exercises_unauthenticated(self, raw_client: httpx.Client) -> None:
        """Unauthenticated access to exercise view should redirect to login."""
        response = raw_client.get("/admin/exercise/view")
        assert response.status_code in [302, 303, 307]
        assert "login" in response.headers.get("location", "").lower()

    def test_build_exercise_unauthenticated(self, raw_client: httpx.Client) -> None:
        """Unauthenticated access to exercise build should redirect to login."""
        response = raw_client.get("/admin/exercise/build/1")
        assert response.status_code in [302, 303, 307]
        assert "login" in response.headers.get("location", "").lower()

    def test_import_exercise_unauthenticated(self, raw_client: httpx.Client) -> None:
        """Unauthenticated access to exercise import should redirect to login."""
        response = raw_client.get("/admin/exercise/import/test")
        assert response.status_code in [302, 303, 307]
        assert "login" in response.headers.get("location", "").lower()

    def test_delete_exercise_unauthenticated(self, raw_client: httpx.Client) -> None:
        """Unauthenticated access to exercise delete should redirect to login."""
        response = raw_client.get("/admin/exercise/1/delete")
        assert response.status_code in [302, 303, 307]
        assert "login" in response.headers.get("location", "").lower()

    def test_view_single_exercise_unauthenticated(
        self, raw_client: httpx.Client
    ) -> None:
        """Unauthenticated access to single exercise view should redirect."""
        response = raw_client.get("/admin/exercise/view/1")
        assert response.status_code in [302, 303, 307]
        assert "login" in response.headers.get("location", "").lower()

    def test_exercise_diff_unauthenticated(self, raw_client: httpx.Client) -> None:
        """Unauthenticated access to exercise diff should redirect."""
        response = raw_client.get("/admin/exercise/diff?path_a=/test")
        assert response.status_code in [302, 303, 307]

    def test_view_exercises_authenticated(self, admin_session: httpx.Client) -> None:
        """Authenticated admin should access exercise view."""
        response = admin_session.get("/admin/exercise/view")
        assert response.status_code == 200

    def test_build_nonexistent_exercise(self, admin_session: httpx.Client) -> None:
        """Building non-existent exercise should handle gracefully."""
        response = admin_session.get("/admin/exercise/build/99999")
        # Should return error, not crash
        assert response.status_code in [200, 302, 400, 404]

    def test_exercise_id_injection(self, admin_session: httpx.Client) -> None:
        """SQL injection in exercise ID should be handled safely."""
        injection_ids = [
            "1; DROP TABLE exercises;--",
            "1 OR 1=1",
            "1' OR '1'='1",
            "<script>alert(1)</script>",
        ]
        for injection_id in injection_ids:
            response = admin_session.get(f"/admin/exercise/view/{injection_id}")
            # Should not crash or execute injection
            assert response.status_code in [200, 400, 404]


@pytest.mark.api
@pytest.mark.security
class TestAdminStudentEndpoints:
    """
    Tests for /admin/student/* endpoints.

    These endpoints require admin authentication.
    """

    def test_view_students_unauthenticated(self, raw_client: httpx.Client) -> None:
        """Unauthenticated access to student view should redirect."""
        response = raw_client.get("/admin/student/view")
        assert response.status_code in [302, 303, 307]

    def test_view_single_student_unauthenticated(
        self, raw_client: httpx.Client
    ) -> None:
        """Unauthenticated access to single student should redirect."""
        response = raw_client.get("/admin/student/view/1")
        assert response.status_code in [302, 303, 307]

    def test_edit_student_unauthenticated(self, raw_client: httpx.Client) -> None:
        """Unauthenticated access to student edit should redirect."""
        response = raw_client.get("/admin/student/edit/1")
        assert response.status_code in [302, 303, 307]

    def test_delete_student_unauthenticated(self, raw_client: httpx.Client) -> None:
        """Unauthenticated access to student delete should redirect."""
        response = raw_client.get("/admin/student/delete/1")
        assert response.status_code in [302, 303, 307]

    def test_student_id_injection(self, admin_session: httpx.Client) -> None:
        """SQL injection in student ID should be handled safely."""
        injection_ids = [
            "1; DROP TABLE users;--",
            "1 OR 1=1",
        ]
        for injection_id in injection_ids:
            response = admin_session.get(f"/admin/student/view/{injection_id}")
            assert response.status_code in [200, 400, 404]


@pytest.mark.api
@pytest.mark.security
class TestAdminInstanceEndpoints:
    """
    Tests for /admin/instances/* endpoints.

    These endpoints require admin authentication.
    """

    def test_view_instances_unauthenticated(self, raw_client: httpx.Client) -> None:
        """Unauthenticated access to instances view should redirect."""
        response = raw_client.get("/admin/instances/view")
        assert response.status_code in [302, 303, 307]

    def test_view_single_instance_unauthenticated(
        self, raw_client: httpx.Client
    ) -> None:
        """Unauthenticated access to single instance should redirect."""
        response = raw_client.get("/admin/instances/view/1")
        assert response.status_code in [302, 303, 307]

    def test_stop_instance_unauthenticated(self, raw_client: httpx.Client) -> None:
        """Unauthenticated access to instance stop should redirect."""
        response = raw_client.get("/admin/instances/stop/1")
        assert response.status_code in [302, 303, 307]

    def test_delete_instance_unauthenticated(self, raw_client: httpx.Client) -> None:
        """Unauthenticated access to instance delete should redirect."""
        response = raw_client.get("/admin/instances/delete/1")
        assert response.status_code in [302, 303, 307]

    def test_view_by_user_unauthenticated(self, raw_client: httpx.Client) -> None:
        """Unauthenticated access to instances by user should redirect."""
        response = raw_client.get("/admin/instances/view/by-user/1")
        assert response.status_code in [302, 303, 307]

    def test_view_by_exercise_unauthenticated(self, raw_client: httpx.Client) -> None:
        """Unauthenticated access to instances by exercise should redirect."""
        response = raw_client.get("/admin/instances/view/by-exercise/test")
        assert response.status_code in [302, 303, 307]


@pytest.mark.api
@pytest.mark.security
class TestAdminSubmissionEndpoints:
    """
    Tests for /admin/submissions/* endpoints.

    These endpoints require admin authentication.
    """

    def test_view_submissions_unauthenticated(self, raw_client: httpx.Client) -> None:
        """Unauthenticated access to submissions should redirect."""
        response = raw_client.get("/admin/submissions")
        assert response.status_code in [302, 303, 307]

    def test_delete_submission_unauthenticated(self, raw_client: httpx.Client) -> None:
        """Unauthenticated access to submission delete should redirect."""
        response = raw_client.get("/admin/submissions/delete/1")
        assert response.status_code in [302, 303, 307]

    def test_by_instance_unauthenticated(self, raw_client: httpx.Client) -> None:
        """Unauthenticated access to submissions by instance should redirect."""
        response = raw_client.get("/admin/submissions/by-instance/1")
        assert response.status_code in [302, 303, 307]


@pytest.mark.api
@pytest.mark.security
class TestAdminGradingEndpoints:
    """
    Tests for /admin/grading/* endpoints.

    These endpoints require grading_assistant or higher.
    """

    def test_grading_view_unauthenticated(self, raw_client: httpx.Client) -> None:
        """Unauthenticated access to grading view should redirect."""
        response = raw_client.get("/admin/grading/")
        assert response.status_code in [302, 303, 307]

    def test_grading_exercise_unauthenticated(self, raw_client: httpx.Client) -> None:
        """Unauthenticated access to exercise grading should redirect."""
        response = raw_client.get("/admin/grading/1")
        assert response.status_code in [302, 303, 307]

    def test_grade_submission_unauthenticated(self, raw_client: httpx.Client) -> None:
        """Unauthenticated access to grade submission should redirect."""
        response = raw_client.get("/admin/grading/grade/1")
        assert response.status_code in [302, 303, 307]

    def test_grading_search_unauthenticated(self, raw_client: httpx.Client) -> None:
        """Unauthenticated access to grading search should redirect."""
        response = raw_client.get("/admin/grading/search")
        assert response.status_code in [302, 303, 307]


@pytest.mark.api
@pytest.mark.security
class TestAdminSystemEndpoints:
    """
    Tests for /system/* and /admin/system/* endpoints.

    These endpoints require admin authentication.
    """

    def test_gc_unauthenticated(self, raw_client: httpx.Client) -> None:
        """Unauthenticated access to GC should redirect."""
        response = raw_client.get("/system/gc")
        assert response.status_code in [302, 303, 307]

    def test_gc_delete_networks_unauthenticated(self, raw_client: httpx.Client) -> None:
        """Unauthenticated access to delete networks should redirect."""
        response = raw_client.get("/system/gc/delete_dangling_networks")
        assert response.status_code in [302, 303, 307]

    def test_system_settings_unauthenticated(self, raw_client: httpx.Client) -> None:
        """Unauthenticated access to system settings should redirect."""
        response = raw_client.get("/admin/system/settings/")
        assert response.status_code in [302, 303, 307]


@pytest.mark.api
@pytest.mark.security
class TestAdminGroupEndpoints:
    """
    Tests for /admin/group/* endpoints.

    These endpoints require admin authentication.
    """

    def test_view_groups_unauthenticated(self, raw_client: httpx.Client) -> None:
        """Unauthenticated access to groups should redirect."""
        response = raw_client.get("/admin/group/view/")
        assert response.status_code in [302, 303, 307]

    def test_delete_group_unauthenticated(self, raw_client: httpx.Client) -> None:
        """Unauthenticated access to group delete should redirect."""
        response = raw_client.get("/admin/group/delete/1")
        assert response.status_code in [302, 303, 307]


@pytest.mark.api
@pytest.mark.security
class TestAdminVisualizationEndpoints:
    """
    Tests for /admin/visualization/* endpoints.

    These endpoints require admin authentication.
    Note: These endpoints may not exist in all deployments (returns 404).
    """

    def test_containers_graph_unauthenticated(self, raw_client: httpx.Client) -> None:
        """Unauthenticated access to containers graph should redirect or 404."""
        response = raw_client.get("/admin/visualization/containers_and_networks_graph")
        # 302/303/307 = redirect to login, 404 = endpoint doesn't exist
        assert response.status_code in [302, 303, 307, 404]

    def test_graphs_unauthenticated(self, raw_client: httpx.Client) -> None:
        """Unauthenticated access to graphs should redirect or 404."""
        response = raw_client.get("/admin/visualization/graphs")
        # 302/303/307 = redirect to login, 404 = endpoint doesn't exist
        assert response.status_code in [302, 303, 307, 404]


@pytest.mark.api
@pytest.mark.security
class TestAdminPathTraversal:
    """
    Tests for path traversal in admin endpoints.
    """

    def test_exercise_import_path_traversal(self, admin_session: httpx.Client) -> None:
        """Path traversal in exercise import should be blocked."""
        traversal_paths = [
            "../../../etc/passwd",
            "..%2f..%2f..%2fetc%2fpasswd",
            "/etc/passwd",
            "....//....//etc/passwd",
        ]
        for path in traversal_paths:
            encoded_path = urllib.parse.quote(path, safe="")
            response = admin_session.get(f"/admin/exercise/import/{encoded_path}")
            # Should be blocked or not find the path
            # Should NOT return /etc/passwd content
            if response.status_code == 200:
                assert "root:" not in response.text  # /etc/passwd content

    def test_exercise_diff_path_traversal(self, admin_session: httpx.Client) -> None:
        """Path traversal in exercise diff should be blocked."""
        response = admin_session.get(
            "/admin/exercise/diff",
            params={"path_a": "../../../etc/passwd"},
        )
        # Should be blocked
        if response.status_code == 200:
            assert "root:" not in response.text

    def test_instance_by_exercise_injection(self, admin_session: httpx.Client) -> None:
        """SQL injection in exercise name should be handled safely."""
        injection_names = [
            "test'; DROP TABLE instances;--",
            "test<script>alert(1)</script>",
        ]
        for name in injection_names:
            encoded_name = urllib.parse.quote(name, safe="")
            response = admin_session.get(
                f"/admin/instances/view/by-exercise/{encoded_name}"
            )
            # Should not crash
            assert response.status_code in [200, 400, 404]
