"""
Unit Tests for ref/core/util.py

Tests for utility functions that don't require Flask/DB context.
"""

import datetime

import pytest
from unittest.mock import MagicMock, patch
from colorama import Fore, Style

from ref.core.util import (
    AnsiColorUtil,
    datetime_to_string,
    is_db_serialization_error,
    is_deadlock_error,
    ssh_key_basename,
    utc_datetime_to_local_tz,
)


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


@pytest.mark.offline
class TestSshKeyBasename:
    """Filename mapping for OpenSSH public keys."""

    def test_ed25519(self):
        assert (
            ssh_key_basename("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5 comment") == "id_ed25519"
        )

    def test_rsa(self):
        assert ssh_key_basename("ssh-rsa AAAAB3NzaC1yc2E comment") == "id_rsa"

    def test_ecdsa_nistp256(self):
        assert (
            ssh_key_basename("ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTY=")
            == "id_ecdsa"
        )

    def test_ecdsa_nistp521(self):
        assert ssh_key_basename("ecdsa-sha2-nistp521 AAAA") == "id_ecdsa"

    def test_dsa(self):
        assert ssh_key_basename("ssh-dss AAAAB3NzaC1kc3M=") == "id_dsa"

    def test_none(self):
        assert ssh_key_basename(None) == "id_rsa"

    def test_empty_string(self):
        assert ssh_key_basename("") == "id_rsa"

    def test_whitespace_only(self):
        assert ssh_key_basename("   \n") == "id_rsa"

    def test_leading_whitespace_is_stripped(self):
        assert ssh_key_basename("   ssh-ed25519 AAAA") == "id_ed25519"

    def test_unknown_algo_falls_back_to_rsa(self):
        assert ssh_key_basename("bogus-algo AAAA") == "id_rsa"


@pytest.mark.offline
class TestUtcDatetimeToLocalTz:
    """Conversion of naive-UTC datetimes (as stored in the DB) to the
    configured system timezone, for display purposes."""

    def test_converts_naive_utc_to_berlin_cest(self):
        naive_utc = datetime.datetime(2026, 4, 26, 15, 59)
        with patch("ref.core.util.SystemSettingsManager") as ssm:
            ssm.TIMEZONE.value = "Europe/Berlin"
            local = utc_datetime_to_local_tz(naive_utc)
        assert local.strftime("%Y-%m-%dT%H:%M") == "2026-04-26T17:59"

    def test_converts_naive_utc_to_berlin_cet_in_winter(self):
        naive_utc = datetime.datetime(2026, 1, 15, 12, 0)
        with patch("ref.core.util.SystemSettingsManager") as ssm:
            ssm.TIMEZONE.value = "Europe/Berlin"
            local = utc_datetime_to_local_tz(naive_utc)
        assert local.strftime("%Y-%m-%dT%H:%M") == "2026-01-15T13:00"

    def test_utc_timezone_is_identity(self):
        naive_utc = datetime.datetime(2026, 4, 26, 15, 59)
        with patch("ref.core.util.SystemSettingsManager") as ssm:
            ssm.TIMEZONE.value = "UTC"
            local = utc_datetime_to_local_tz(naive_utc)
        assert local.strftime("%Y-%m-%dT%H:%M") == "2026-04-26T15:59"

    def test_crosses_day_boundary(self):
        naive_utc = datetime.datetime(2026, 4, 26, 23, 30)
        with patch("ref.core.util.SystemSettingsManager") as ssm:
            ssm.TIMEZONE.value = "Europe/Berlin"
            local = utc_datetime_to_local_tz(naive_utc)
        assert local.strftime("%Y-%m-%dT%H:%M") == "2026-04-27T01:30"


@pytest.mark.offline
class TestDatetimeToString:
    """Human-readable formatting of DB-stored (naive UTC) datetimes."""

    def test_naive_utc_formatted_in_system_tz(self):
        naive_utc = datetime.datetime(2026, 4, 26, 15, 59, 0)
        with patch("ref.core.util.SystemSettingsManager") as ssm:
            ssm.TIMEZONE.value = "Europe/Berlin"
            s = datetime_to_string(naive_utc)
        assert s == "26/04/2026 17:59:00"

    def test_aware_datetime_preserves_its_tz(self):
        from dateutil import tz as _tz

        aware_utc = datetime.datetime(2026, 4, 26, 15, 59, 0, tzinfo=_tz.gettz("UTC"))
        # Aware datetimes pass through without re-conversion.
        s = datetime_to_string(aware_utc)
        assert s == "26/04/2026 15:59:00"
