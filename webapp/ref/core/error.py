import contextlib
import sys


class InconsistentStateError(Exception):

    def __init__(self, *args, msg=None, **kwargs):
        msg = msg or 'The system is in an inconsistent state that it can not recover from automatically.'
        super().__init__(*args, **kwargs)


@contextlib.contextmanager
def inconsistency_on_error(msg=None):
    """
    Raises a InconsistentStateError error if an exception is raised inside this context.
    If this context is used during handling and exception (i.e., inside an `except` arm),
    this original exception is reraised and propably chanied to an InconsistentStateError,
    if cleanup also fails.
    """

    #If we are used inside an exception handler, then exc_obj is the current exception.
    exc_type, exc_obj, exc_tb = sys.exc_info()
    del exc_type
    del exc_tb

    try:
        # Try to restore from erroneous state
        yield
    except Exception as e:
        if exc_obj:
            # Chain all errors together:
            # InconsistentStateError `from` error during restore `from` original error
            try:
                raise e from exc_obj
            except Exception as e:
                raise InconsistentStateError(msg) from e
        else:
            # If we where not already in an exception handler,
            # just chain the exception that occurred during restore
            # and InconsistentStateError.
            raise InconsistentStateError(msg) from e
    else:
        # No errors happend during cleanup.
        if exc_obj:
            # However, we where already raising and exception in the caller,
            # so reraise it thus it can bubble up.
            raise exc_obj
