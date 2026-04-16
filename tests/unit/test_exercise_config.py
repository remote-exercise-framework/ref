"""
Unit Tests for ExerciseManager._parse_attr and ExerciseConfigError

Tests for exercise configuration parsing utilities.
"""

import datetime

import pytest

from ref.core.exercise import ExerciseConfigError, ExerciseManager


@pytest.mark.offline
class TestExerciseConfigError:
    """Test the ExerciseConfigError exception class."""

    def test_can_raise(self):
        """Test that exception can be raised."""
        with pytest.raises(ExerciseConfigError):
            raise ExerciseConfigError("Test error")

    def test_message_preserved(self):
        """Test that error message is preserved."""
        try:
            raise ExerciseConfigError("Custom message")
        except ExerciseConfigError as e:
            assert "Custom message" in str(e)

    def test_inherits_from_exception(self):
        """Test that ExerciseConfigError inherits from Exception."""
        assert issubclass(ExerciseConfigError, Exception)


@pytest.mark.offline
class TestParseAttrRequired:
    """Test _parse_attr with required attributes."""

    def test_required_attr_present(self):
        """Test parsing a required attribute that exists."""
        cfg = {"name": "test_value"}
        result = ExerciseManager._parse_attr(cfg, "name", str, required=True)
        assert result == "test_value"
        assert "name" not in cfg  # Should be removed from dict

    def test_required_attr_missing(self):
        """Test that missing required attribute raises error."""
        cfg = {}
        with pytest.raises(
            ExerciseConfigError, match='Missing required attribute "name"'
        ):
            ExerciseManager._parse_attr(cfg, "name", str, required=True)

    def test_required_attr_none_value(self):
        """Test that None value for required attribute raises error."""
        cfg = {"name": None}
        with pytest.raises(
            ExerciseConfigError, match='Missing required attribute "name"'
        ):
            ExerciseManager._parse_attr(cfg, "name", str, required=True)


@pytest.mark.offline
class TestParseAttrOptional:
    """Test _parse_attr with optional attributes."""

    def test_optional_attr_present(self):
        """Test parsing an optional attribute that exists."""
        cfg = {"name": "test_value"}
        result = ExerciseManager._parse_attr(
            cfg, "name", str, required=False, default="default"
        )
        assert result == "test_value"
        assert "name" not in cfg

    def test_optional_attr_missing_returns_default(self):
        """Test that missing optional attribute returns default."""
        cfg = {}
        result = ExerciseManager._parse_attr(
            cfg, "name", str, required=False, default="default_value"
        )
        assert result == "default_value"

    def test_optional_attr_none_returns_default(self):
        """Test that None value for optional attribute returns default."""
        cfg = {"name": None}
        result = ExerciseManager._parse_attr(
            cfg, "name", str, required=False, default="default_value"
        )
        assert result == "default_value"
        assert "name" not in cfg  # None entry should be removed

    def test_optional_attr_default_none(self):
        """Test optional attribute with None as default."""
        cfg = {}
        result = ExerciseManager._parse_attr(
            cfg, "name", str, required=False, default=None
        )
        assert result is None


@pytest.mark.offline
class TestParseAttrTypeValidation:
    """Test _parse_attr type validation."""

    def test_string_type(self):
        """Test parsing string type."""
        cfg = {"value": "hello"}
        result = ExerciseManager._parse_attr(cfg, "value", str)
        assert result == "hello"
        assert isinstance(result, str)

    def test_int_type(self):
        """Test parsing integer type."""
        cfg = {"value": 42}
        result = ExerciseManager._parse_attr(cfg, "value", int)
        assert result == 42
        assert isinstance(result, int)

    def test_float_type(self):
        """Test parsing float type."""
        cfg = {"value": 3.14}
        result = ExerciseManager._parse_attr(cfg, "value", float)
        assert result == 3.14
        assert isinstance(result, float)

    def test_bool_type(self):
        """Test parsing boolean type."""
        cfg = {"value": True}
        result = ExerciseManager._parse_attr(cfg, "value", bool)
        assert result is True
        assert isinstance(result, bool)

    def test_list_type(self):
        """Test parsing list type."""
        cfg = {"value": [1, 2, 3]}
        result = ExerciseManager._parse_attr(cfg, "value", list)
        assert result == [1, 2, 3]
        assert isinstance(result, list)

    def test_dict_type(self):
        """Test parsing dict type."""
        cfg = {"value": {"key": "val"}}
        result = ExerciseManager._parse_attr(cfg, "value", dict)
        assert result == {"key": "val"}
        assert isinstance(result, dict)

    def test_wrong_type_raises_error(self):
        """Test that wrong type raises ExerciseConfigError."""
        cfg = {"value": "not_an_int"}
        with pytest.raises(ExerciseConfigError, match="Type of attribute"):
            ExerciseManager._parse_attr(cfg, "value", int)

    def test_wrong_type_error_message(self):
        """Test that type error message contains useful info."""
        cfg = {"count": "five"}
        try:
            ExerciseManager._parse_attr(cfg, "count", int)
        except ExerciseConfigError as e:
            assert "count" in str(e)
            assert "int" in str(e)


@pytest.mark.offline
class TestParseAttrDatetimeTime:
    """Test _parse_attr with datetime.time type."""

    def test_time_from_iso_string(self):
        """Test parsing time from ISO format string."""
        cfg = {"time": "14:30:00"}
        result = ExerciseManager._parse_attr(cfg, "time", datetime.time)
        assert result == datetime.time(14, 30, 0)
        assert isinstance(result, datetime.time)

    def test_time_from_iso_string_short(self):
        """Test parsing time from short ISO format string."""
        cfg = {"time": "09:15"}
        result = ExerciseManager._parse_attr(cfg, "time", datetime.time)
        assert result == datetime.time(9, 15, 0)

    def test_time_already_time_object(self):
        """Test that time object passes through."""
        time_obj = datetime.time(10, 0, 0)
        cfg = {"time": time_obj}
        result = ExerciseManager._parse_attr(cfg, "time", datetime.time)
        assert result == time_obj

    def test_invalid_time_string_raises_error(self):
        """Test that invalid time string raises type error."""
        cfg = {"time": "not-a-time"}
        with pytest.raises(ExerciseConfigError, match="Type of attribute"):
            ExerciseManager._parse_attr(cfg, "time", datetime.time)


@pytest.mark.offline
class TestParseAttrValidators:
    """Test _parse_attr with custom validators."""

    def test_single_validator_passes(self):
        """Test attribute with passing validator."""
        cfg = {"count": 5}
        validators = [(lambda x: x > 0, "must be positive")]
        result = ExerciseManager._parse_attr(cfg, "count", int, validators=validators)
        assert result == 5

    def test_single_validator_fails(self):
        """Test attribute with failing validator."""
        cfg = {"count": -5}
        validators = [(lambda x: x > 0, "must be positive")]
        with pytest.raises(ExerciseConfigError, match="must be positive"):
            ExerciseManager._parse_attr(cfg, "count", int, validators=validators)

    def test_multiple_validators_all_pass(self):
        """Test attribute with multiple passing validators."""
        cfg = {"value": 50}
        validators = [
            (lambda x: x > 0, "must be positive"),
            (lambda x: x < 100, "must be less than 100"),
        ]
        result = ExerciseManager._parse_attr(cfg, "value", int, validators=validators)
        assert result == 50

    def test_multiple_validators_first_fails(self):
        """Test that first failing validator raises error."""
        cfg = {"value": -10}
        validators = [
            (lambda x: x > 0, "must be positive"),
            (lambda x: x < 100, "must be less than 100"),
        ]
        with pytest.raises(ExerciseConfigError, match="must be positive"):
            ExerciseManager._parse_attr(cfg, "value", int, validators=validators)

    def test_multiple_validators_second_fails(self):
        """Test that second failing validator raises error."""
        cfg = {"value": 150}
        validators = [
            (lambda x: x > 0, "must be positive"),
            (lambda x: x < 100, "must be less than 100"),
        ]
        with pytest.raises(ExerciseConfigError, match="must be less than 100"):
            ExerciseManager._parse_attr(cfg, "value", int, validators=validators)

    def test_string_validator(self):
        """Test validator on string attribute."""
        cfg = {"name": "test_exercise"}
        validators = [(lambda x: "_" in x, "must contain underscore")]
        result = ExerciseManager._parse_attr(cfg, "name", str, validators=validators)
        assert result == "test_exercise"

    def test_validator_error_includes_attr_name(self):
        """Test that validator error includes attribute name."""
        cfg = {"my_attr": "bad"}
        validators = [(lambda x: False, "always fails")]
        try:
            ExerciseManager._parse_attr(cfg, "my_attr", str, validators=validators)
        except ExerciseConfigError as e:
            assert "my_attr" in str(e)


@pytest.mark.offline
class TestParseAttrDictModification:
    """Test that _parse_attr properly modifies the input dict."""

    def test_attr_removed_after_parse(self):
        """Test that parsed attribute is removed from dict."""
        cfg = {"a": 1, "b": 2, "c": 3}
        ExerciseManager._parse_attr(cfg, "b", int)
        assert "b" not in cfg
        assert cfg == {"a": 1, "c": 3}

    def test_none_optional_removed(self):
        """Test that None optional attribute is removed from dict."""
        cfg = {"a": 1, "b": None}
        ExerciseManager._parse_attr(cfg, "b", str, required=False, default="x")
        assert "b" not in cfg

    def test_missing_optional_doesnt_modify_dict(self):
        """Test that missing optional doesn't add to dict."""
        cfg = {"a": 1}
        ExerciseManager._parse_attr(cfg, "b", str, required=False, default="x")
        assert cfg == {"a": 1}


@pytest.mark.offline
class TestParseAttrEdgeCases:
    """Test edge cases for _parse_attr."""

    def test_empty_string_is_valid(self):
        """Test that empty string is valid for string type."""
        cfg = {"name": ""}
        result = ExerciseManager._parse_attr(cfg, "name", str)
        assert result == ""

    def test_zero_is_valid_int(self):
        """Test that zero is valid for int type."""
        cfg = {"count": 0}
        result = ExerciseManager._parse_attr(cfg, "count", int)
        assert result == 0

    def test_false_is_valid_bool(self):
        """Test that False is valid for bool type."""
        cfg = {"enabled": False}
        result = ExerciseManager._parse_attr(cfg, "enabled", bool)
        assert result is False

    def test_empty_list_is_valid(self):
        """Test that empty list is valid for list type."""
        cfg = {"items": []}
        result = ExerciseManager._parse_attr(cfg, "items", list)
        assert result == []

    def test_empty_dict_is_valid(self):
        """Test that empty dict is valid for dict type."""
        cfg = {"config": {}}
        result = ExerciseManager._parse_attr(cfg, "config", dict)
        assert result == {}

    def test_date_type(self):
        """Test parsing date type (from YAML usually loaded as date)."""
        date_obj = datetime.date(2024, 1, 15)
        cfg = {"deadline": date_obj}
        result = ExerciseManager._parse_attr(cfg, "deadline", datetime.date)
        assert result == date_obj
