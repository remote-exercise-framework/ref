"""
E2E Test: Docker Resource Prefix Verification

Tests that Docker resources (images, containers, networks) created during tests
have the correct test-specific prefix, enabling proper cleanup and isolation.

This test validates that the fix for the prefix override bug is working:
- The DOCKER_RESSOURCE_PREFIX environment variable is passed to the web container
- The Flask app respects this environment variable instead of using the installation ID
"""

import subprocess
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from helpers.exercise_factory import create_sample_exercise
from helpers.web_client import REFWebClient

if TYPE_CHECKING:
    from helpers.ref_instance import REFInstance


class TestResourcePrefix:
    """Test that Docker resources use the correct test prefix."""

    @pytest.mark.e2e
    def test_exercise_image_has_test_prefix(
        self,
        ref_instance: "REFInstance",
        admin_client: REFWebClient,
        exercises_path: Path,
    ) -> None:
        """
        Verify that built exercise images have the test prefix.

        The prefix should match the ref_instance's config prefix,
        NOT the installation ID stored in the database.
        """
        # Get expected prefix from the test instance
        expected_prefix = f"{ref_instance.config.prefix}-"

        # Create a unique exercise for this test
        exercise_name = f"prefix_test_{uuid.uuid4().hex[:6]}"
        exercise_dir = exercises_path / exercise_name

        try:
            # Create the exercise
            create_sample_exercise(
                exercise_dir,
                short_name=exercise_name,
                version=1,
                category="Prefix Test",
                has_deadline=False,
                has_submission_test=False,
            )

            # Import the exercise
            success = admin_client.import_exercise(str(exercise_dir))
            assert success, f"Failed to import exercise from {exercise_dir}"

            # Get exercise ID
            exercise = admin_client.get_exercise_by_name(exercise_name)
            assert exercise is not None, f"Exercise {exercise_name} not found"
            exercise_id = exercise.get("id")
            assert exercise_id is not None, "Exercise ID not found"
            assert isinstance(exercise_id, int), "Exercise ID must be an integer"

            # Build the exercise
            success = admin_client.build_exercise(exercise_id)
            assert success, "Failed to start exercise build"

            build_success = admin_client.wait_for_build(exercise_id, timeout=300.0)
            assert build_success, "Exercise build did not complete successfully"

            # Query Docker for images
            result = subprocess.run(
                ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
                capture_output=True,
                text=True,
                check=True,
            )
            images = result.stdout.strip().split("\n")

            # Find the exercise image with the expected prefix
            exercise_images = [
                img for img in images if expected_prefix in img and exercise_name in img
            ]

            assert len(exercise_images) > 0, (
                f"Exercise image for '{exercise_name}' not found with prefix "
                f"'{expected_prefix}'. All images containing exercise name: "
                f"{[img for img in images if exercise_name in img]}"
            )

            # Verify the image name format
            for img in exercise_images:
                assert img.startswith(expected_prefix), (
                    f"Image '{img}' does not start with expected prefix "
                    f"'{expected_prefix}'"
                )

        finally:
            # Cleanup: Remove exercise directory
            if exercise_dir.exists():
                import shutil

                shutil.rmtree(exercise_dir)

    @pytest.mark.e2e
    def test_cleanup_removes_prefixed_resources(
        self,
        ref_instance: "REFInstance",
    ) -> None:
        """
        Verify cleanup correctly identifies and removes resources with test prefix.

        This test creates a dummy container with the test prefix and verifies
        that cleanup_docker_resources_by_prefix can remove it.
        """
        from helpers.ref_instance import cleanup_docker_resources_by_prefix

        expected_prefix = f"{ref_instance.config.prefix}-"

        # Create a test container with our prefix
        test_container_name = f"{expected_prefix}cleanup-test-{uuid.uuid4().hex[:6]}"

        try:
            # Create a simple container
            subprocess.run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    test_container_name,
                    "alpine:latest",
                    "sleep",
                    "3600",
                ],
                capture_output=True,
                check=True,
            )

            # Verify it exists
            result = subprocess.run(
                ["docker", "ps", "-a", "--format", "{{.Names}}"],
                capture_output=True,
                text=True,
                check=True,
            )
            assert test_container_name in result.stdout, (
                "Test container was not created"
            )

            # Run cleanup
            cleanup_docker_resources_by_prefix(expected_prefix)

            # Verify container is gone
            result = subprocess.run(
                ["docker", "ps", "-a", "--format", "{{.Names}}"],
                capture_output=True,
                text=True,
                check=True,
            )
            assert test_container_name not in result.stdout, (
                f"Container '{test_container_name}' still exists after cleanup"
            )

        except subprocess.CalledProcessError:
            # If container creation failed, try to clean up anyway
            subprocess.run(
                ["docker", "rm", "-f", test_container_name],
                capture_output=True,
            )
            raise
