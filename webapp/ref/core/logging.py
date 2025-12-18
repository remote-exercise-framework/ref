"""
Central logging utility for REF.

Provides a logger that works both in Flask application context and in
standalone environments (e.g., unit tests). When running inside Flask,
it uses the Flask app logger. Outside Flask, it falls back to standard
Python logging.
"""

import logging
from werkzeug.local import LocalProxy


def get_logger(name: str = __name__):
    """Get a logger that works both in Flask and standalone contexts.

    Args:
        name: The logger name (typically __name__ of the calling module).

    Returns:
        A LocalProxy that lazily resolves to either Flask's app logger
        or a standard Python logger.
    """
    def _get():
        try:
            from flask import current_app
            if current_app:
                return current_app.logger
        except RuntimeError:
            # Outside Flask application context
            pass
        return logging.getLogger(name)
    return LocalProxy(_get)
