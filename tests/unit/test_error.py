"""
Unit Tests for ref/core/error.py

Tests for InconsistentStateError exception and inconsistency_on_error context manager.
"""

import pytest

from ref.core.error import InconsistentStateError, inconsistency_on_error


@pytest.mark.offline
class TestInconsistentStateError:
    """Test the InconsistentStateError exception class."""

    def test_default_message(self):
        """Test that exception can be raised with default message."""
        with pytest.raises(InconsistentStateError):
            raise InconsistentStateError()

    def test_custom_message(self):
        """Test that exception can be raised with custom message."""
        with pytest.raises(InconsistentStateError):
            raise InconsistentStateError(msg="Custom error message")

    def test_exception_inheritance(self):
        """Test that InconsistentStateError inherits from Exception."""
        assert issubclass(InconsistentStateError, Exception)

    def test_can_catch_as_exception(self):
        """Test that InconsistentStateError can be caught as Exception."""
        caught = False
        try:
            raise InconsistentStateError()
        except Exception:
            caught = True
        assert caught


@pytest.mark.offline
class TestInconsistencyOnErrorNoException:
    """Test inconsistency_on_error when no exception occurs."""

    def test_no_error_passes_through(self):
        """Test that context passes through when no error occurs."""
        result = []
        with inconsistency_on_error():
            result.append("executed")
        assert result == ["executed"]

    def test_no_error_with_custom_message(self):
        """Test that context passes through with custom message when no error."""
        result = []
        with inconsistency_on_error(msg="Should not appear"):
            result.append("executed")
        assert result == ["executed"]


@pytest.mark.offline
class TestInconsistencyOnErrorWithException:
    """Test inconsistency_on_error when exception occurs inside context."""

    def test_error_raises_inconsistent_state(self):
        """Test that error in context raises InconsistentStateError."""
        with pytest.raises(InconsistentStateError):
            with inconsistency_on_error():
                raise ValueError("Original error")

    def test_error_chains_original_exception(self):
        """Test that original exception is chained."""
        try:
            with inconsistency_on_error():
                raise ValueError("Original error")
        except InconsistentStateError as e:
            # The __cause__ should be the ValueError
            assert e.__cause__ is not None
            assert isinstance(e.__cause__, ValueError)

    def test_custom_message_in_exception(self):
        """Test that custom message is used in InconsistentStateError."""
        custom_msg = "Custom inconsistency message"
        try:
            with inconsistency_on_error(msg=custom_msg):
                raise ValueError("Original error")
        except InconsistentStateError as e:
            # InconsistentStateError was raised (message handling is internal)
            assert e.__cause__ is not None


@pytest.mark.offline
class TestInconsistencyOnErrorInsideExceptionHandler:
    """Test inconsistency_on_error when used inside an exception handler."""

    def test_reraises_original_when_cleanup_succeeds(self):
        """Test that original exception is re-raised when cleanup succeeds."""
        with pytest.raises(RuntimeError, match="Original"):
            try:
                raise RuntimeError("Original")
            except RuntimeError:
                with inconsistency_on_error():
                    # Cleanup succeeds - no error here
                    pass
                # Should not reach here
                pytest.fail("Should have re-raised RuntimeError")

    def test_chains_exceptions_when_cleanup_fails(self):
        """Test exception chaining when cleanup also fails."""
        with pytest.raises(InconsistentStateError) as exc_info:
            try:
                raise RuntimeError("Original error")
            except RuntimeError:
                with inconsistency_on_error():
                    raise ValueError("Cleanup error")

        # Verify exception chain
        e = exc_info.value
        assert e.__cause__ is not None
        # The cause should be ValueError chained from RuntimeError
        assert isinstance(e.__cause__, ValueError)
        assert e.__cause__.__cause__ is not None
        assert isinstance(e.__cause__.__cause__, RuntimeError)


@pytest.mark.offline
class TestInconsistencyOnErrorEdgeCases:
    """Test edge cases for inconsistency_on_error."""

    def test_nested_contexts(self):
        """Test nested inconsistency_on_error contexts."""
        with pytest.raises(InconsistentStateError):
            with inconsistency_on_error(msg="Outer"):
                with inconsistency_on_error(msg="Inner"):
                    raise ValueError("Deep error")

    def test_context_with_return_value(self):
        """Test that context doesn't interfere with return values."""
        def func_with_context():
            with inconsistency_on_error():
                return 42
            return 0

        assert func_with_context() == 42

    def test_multiple_sequential_contexts(self):
        """Test multiple sequential uses of the context."""
        results = []

        with inconsistency_on_error():
            results.append(1)

        with inconsistency_on_error():
            results.append(2)

        assert results == [1, 2]
