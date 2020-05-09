import contextlib
import sys


class InconsistentStateError(Exception):

    def __init__(self, msg=None, *args, **kwargs):
        msg = msg or 'The system is in an inconsistent state that can not be recovered automatically.'
        super().__init__(*args, **kwargs)


@contextlib.contextmanager
def inconsistency_on_error(msg=None):
    #If we are used inside an exception handler, then exc_obj is the current exception.
    exc_type, exc_obj, exc_tb = sys.exc_info()
    del exc_type
    del exc_tb

    try:
        yield
    except Exception as e:
        if exc_obj:
            try:
                raise e from exc_obj
            except Exception as e:
                raise InconsistentStateError(msg) from e
        else:
            raise InconsistentStateError(msg) from e
    else:
        if exc_obj:
            raise exc_obj
