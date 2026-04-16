"""
Unit Tests for security utilities.

These tests verify the path sanitization functions work correctly,
including protection against path traversal attacks.
"""

import pytest
from pathlib import Path
import tempfile
import os

from ref.core.security import sanitize_path_is_subdir


@pytest.mark.offline
class TestSanitizePathIsSubdir:
    """Test the sanitize_path_is_subdir function."""

    def test_valid_subdirectory(self):
        """Test that valid subdirectories are accepted."""
        with tempfile.TemporaryDirectory() as parent:
            child = os.path.join(parent, "subdir", "file.txt")
            os.makedirs(os.path.dirname(child), exist_ok=True)
            Path(child).touch()

            assert sanitize_path_is_subdir(parent, child) is True

    def test_same_directory(self):
        """Test that the same directory returns True."""
        with tempfile.TemporaryDirectory() as parent:
            assert sanitize_path_is_subdir(parent, parent) is True

    def test_parent_directory_rejected(self):
        """Test that parent directories are rejected."""
        with tempfile.TemporaryDirectory() as parent:
            child = os.path.join(parent, "subdir")
            os.makedirs(child, exist_ok=True)

            # Trying to access parent from child should fail
            assert sanitize_path_is_subdir(child, parent) is False

    def test_sibling_directory_rejected(self):
        """Test that sibling directories are rejected."""
        with tempfile.TemporaryDirectory() as base:
            dir_a = os.path.join(base, "dir_a")
            dir_b = os.path.join(base, "dir_b")
            os.makedirs(dir_a)
            os.makedirs(dir_b)

            assert sanitize_path_is_subdir(dir_a, dir_b) is False

    def test_path_traversal_with_dotdot(self):
        """Test that .. path traversal is blocked."""
        with tempfile.TemporaryDirectory() as base:
            parent = os.path.join(base, "parent")
            os.makedirs(parent)

            # Try to escape using ../
            traversal_path = os.path.join(parent, "..", "other")
            assert sanitize_path_is_subdir(parent, traversal_path) is False

    def test_prefix_attack_blocked(self):
        """
        Test that prefix-based path traversal is blocked.

        This is a critical security test. The old implementation used
        startswith() which would incorrectly match:
        - parent: /home/ex
        - child: /home/exercises_backdoor/file.txt

        Because '/home/exercises_backdoor'.startswith('/home/ex') is True!
        """
        with tempfile.TemporaryDirectory() as base:
            # Create two directories where one name is a prefix of the other
            short_name = os.path.join(base, "ex")
            long_name = os.path.join(base, "exercises_backdoor")
            os.makedirs(short_name)
            os.makedirs(long_name)

            malicious_file = os.path.join(long_name, "file.txt")
            Path(malicious_file).touch()

            # This MUST return False - the malicious file is NOT under short_name
            assert sanitize_path_is_subdir(short_name, malicious_file) is False

    def test_prefix_attack_real_world_scenario(self):
        """
        Test real-world prefix attack scenario with exercises path.

        Simulates the exact vulnerability: /home/exercises vs /home/exercises_backdoor
        """
        with tempfile.TemporaryDirectory() as base:
            exercises = os.path.join(base, "exercises")
            exercises_backdoor = os.path.join(base, "exercises_backdoor")
            os.makedirs(exercises)
            os.makedirs(exercises_backdoor)

            secret_file = os.path.join(exercises_backdoor, "secret.txt")
            Path(secret_file).touch()

            # This MUST return False
            assert sanitize_path_is_subdir(exercises, secret_file) is False

    def test_accepts_string_paths(self):
        """Test that string paths are accepted."""
        with tempfile.TemporaryDirectory() as parent:
            child = os.path.join(parent, "subdir")
            os.makedirs(child)

            # Both as strings
            assert sanitize_path_is_subdir(parent, child) is True

    def test_accepts_path_objects(self):
        """Test that Path objects are accepted."""
        with tempfile.TemporaryDirectory() as parent:
            child = os.path.join(parent, "subdir")
            os.makedirs(child)

            # Both as Path objects
            assert sanitize_path_is_subdir(Path(parent), Path(child)) is True

    def test_accepts_mixed_path_types(self):
        """Test that mixed path types are accepted."""
        with tempfile.TemporaryDirectory() as parent:
            child = os.path.join(parent, "subdir")
            os.makedirs(child)

            # Mixed types
            assert sanitize_path_is_subdir(parent, Path(child)) is True
            assert sanitize_path_is_subdir(Path(parent), child) is True

    def test_nonexistent_path_returns_true_for_subdir(self):
        """Test that non-existent paths under parent return True."""
        with tempfile.TemporaryDirectory() as parent:
            nonexistent = os.path.join(parent, "does_not_exist", "file.txt")

            # Non-existent paths should still work (resolve() handles them)
            # Non-existent subdirectory should still be considered a valid subdir
            result = sanitize_path_is_subdir(parent, nonexistent)
            assert result is True

    def test_symlink_escape_blocked(self):
        """Test that symlink escape attempts are blocked."""
        with tempfile.TemporaryDirectory() as base:
            parent = os.path.join(base, "parent")
            outside = os.path.join(base, "outside")
            os.makedirs(parent)
            os.makedirs(outside)

            # Create a file outside the parent
            outside_file = os.path.join(outside, "secret.txt")
            Path(outside_file).touch()

            # Create a symlink inside parent pointing to outside
            symlink = os.path.join(parent, "escape_link")
            os.symlink(outside_file, symlink)

            # resolve() follows symlinks, so this should return False
            assert sanitize_path_is_subdir(parent, symlink) is False
