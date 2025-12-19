"""
Unit Tests for ref/core/util.py

Tests for utility functions that don't require Flask/DB context.
"""

import pytest
from unittest.mock import MagicMock, patch
from colorama import Fore, Style

from ref.core.util import AnsiColorUtil, is_db_serialization_error, is_deadlock_error


@pytest.mark.offline
class TestAnsiColorUtil:
    """Test the AnsiColorUtil class for ANSI color formatting."""

    def test_green_wraps_string(self):
        """Test that green() wraps string with green color codes."""
        result = AnsiColorUtil.green("test")
        assert result.startswith(Fore.GREEN)
        assert result.endswith(Style.RESET_ALL)
        assert "test" in result

    def test_green_contains_original_text(self):
        """Test that green() preserves original text."""
        original = "hello world"
        result = AnsiColorUtil.green(original)
        assert original in result

    def test_yellow_wraps_string(self):
        """Test that yellow() wraps string with yellow color codes."""
        result = AnsiColorUtil.yellow("warning")
        assert result.startswith(Fore.YELLOW)
        assert result.endswith(Style.RESET_ALL)
        assert "warning" in result

    def test_yellow_contains_original_text(self):
        """Test that yellow() preserves original text."""
        original = "caution message"
        result = AnsiColorUtil.yellow(original)
        assert original in result

    def test_red_wraps_string(self):
        """Test that red() wraps string with red color codes."""
        result = AnsiColorUtil.red("error")
        assert result.startswith(Fore.RED)
        assert result.endswith(Style.RESET_ALL)
        assert "error" in result

    def test_red_contains_original_text(self):
        """Test that red() preserves original text."""
        original = "critical error"
        result = AnsiColorUtil.red(original)
        assert original in result

    def test_empty_string(self):
        """Test that empty strings are handled."""
        assert AnsiColorUtil.green("") == Fore.GREEN + "" + Style.RESET_ALL
        assert AnsiColorUtil.yellow("") == Fore.YELLOW + "" + Style.RESET_ALL
        assert AnsiColorUtil.red("") == Fore.RED + "" + Style.RESET_ALL

    def test_special_characters(self):
        """Test that special characters are preserved."""
        special = "Test\nWith\tSpecial\r\nChars!@#$%"
        result = AnsiColorUtil.green(special)
        assert special in result

    def test_unicode_characters(self):
        """Test that unicode characters are preserved."""
        unicode_str = "Test with émojis 🎉 and ünïcödé"
        result = AnsiColorUtil.red(unicode_str)
        assert unicode_str in result


@pytest.mark.offline
class TestIsDbSerializationError:
    """Test the is_db_serialization_error function."""

    def test_returns_true_for_serialization_error(self):
        """Test that function returns True for pgcode 40001."""
        mock_error = MagicMock()
        mock_error.orig = MagicMock()
        mock_error.orig.pgcode = "40001"

        result = is_db_serialization_error(mock_error)
        assert result is True

    def test_returns_false_for_other_pgcode(self):
        """Test that function returns False for other pgcodes."""
        mock_error = MagicMock()
        mock_error.orig = MagicMock()
        mock_error.orig.pgcode = "42000"

        result = is_db_serialization_error(mock_error)
        assert result is False

    def test_returns_false_when_no_pgcode(self):
        """Test that function returns False when pgcode is None."""
        mock_error = MagicMock()
        mock_error.orig = MagicMock()
        mock_error.orig.pgcode = None

        result = is_db_serialization_error(mock_error)
        assert result is False

    def test_returns_false_when_no_orig(self):
        """Test that function handles missing orig attribute."""
        mock_error = MagicMock()
        mock_error.orig = None

        result = is_db_serialization_error(mock_error)
        assert result is False

    def test_returns_false_when_orig_has_no_pgcode(self):
        """Test that function handles orig without pgcode attribute."""
        mock_error = MagicMock()
        mock_error.orig = MagicMock(spec=[])  # No pgcode attribute

        result = is_db_serialization_error(mock_error)
        assert result is False


@pytest.mark.offline
class TestIsDeadlockError:
    """Test the is_deadlock_error function."""

    @pytest.fixture(autouse=True)
    def mock_flask_app(self):
        """Mock Flask current_app for all tests in this class."""
        mock_app = MagicMock()
        mock_app.logger = MagicMock()
        with patch.dict("sys.modules", {"flask": MagicMock()}):
            with patch.object(
                __import__("ref.core.util", fromlist=["current_app"]),
                "current_app",
                mock_app,
            ):
                yield mock_app

    def test_returns_false_for_non_deadlock_error(
        self, mock_flask_app: MagicMock
    ) -> None:
        """Test that function returns False for non-deadlock errors."""
        # Create a simple mock error that is not a DeadlockDetected
        mock_error = MagicMock()
        mock_error.orig = MagicMock()

        result = is_deadlock_error(mock_error)
        assert result is False

    def test_returns_true_for_deadlock_detected_type(
        self, mock_flask_app: MagicMock
    ) -> None:
        """Test that function detects DeadlockDetected in orig."""
        from psycopg2.errors import DeadlockDetected

        # Create actual DeadlockDetected instance
        try:
            # DeadlockDetected requires certain arguments, create via exception
            raise DeadlockDetected()
        except DeadlockDetected as e:
            # Wrap in an OperationalError-like object
            mock_error = MagicMock()
            mock_error.orig = e

            result = is_deadlock_error(mock_error)
            assert result is True


@pytest.mark.offline
class TestAnsiColorUtilStaticMethods:
    """Test that AnsiColorUtil methods are static and callable."""

    def test_green_is_static(self):
        """Test that green is a static method."""
        # Should be callable without instance
        result = AnsiColorUtil.green("test")
        assert isinstance(result, str)

    def test_yellow_is_static(self):
        """Test that yellow is a static method."""
        result = AnsiColorUtil.yellow("test")
        assert isinstance(result, str)

    def test_red_is_static(self):
        """Test that red is a static method."""
        result = AnsiColorUtil.red("test")
        assert isinstance(result, str)

    def test_can_call_on_class(self):
        """Test that methods can be called on the class directly."""
        assert AnsiColorUtil.green("a") is not None
        assert AnsiColorUtil.yellow("b") is not None
        assert AnsiColorUtil.red("c") is not None


@pytest.mark.offline
class TestColorOutputFormat:
    """Test the exact format of color output."""

    def test_green_format(self):
        """Test exact format of green output."""
        text = "message"
        expected = f"{Fore.GREEN}{text}{Style.RESET_ALL}"
        assert AnsiColorUtil.green(text) == expected

    def test_yellow_format(self):
        """Test exact format of yellow output."""
        text = "message"
        expected = f"{Fore.YELLOW}{text}{Style.RESET_ALL}"
        assert AnsiColorUtil.yellow(text) == expected

    def test_red_format(self):
        """Test exact format of red output."""
        text = "message"
        expected = f"{Fore.RED}{text}{Style.RESET_ALL}"
        assert AnsiColorUtil.red(text) == expected

    def test_multiline_text(self):
        """Test that multiline text is handled correctly."""
        multiline = "line1\nline2\nline3"
        result = AnsiColorUtil.green(multiline)
        # The entire multiline text should be wrapped, not each line
        assert result == f"{Fore.GREEN}{multiline}{Style.RESET_ALL}"
