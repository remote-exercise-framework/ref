"""JSON endpoints called by services (SSH reverse proxy, student containers).

These endpoints are not consumed by end-user browsers — they are the
machine-to-machine surface of the web app.

- `ssh` — the SSH reverse proxy asking the web app to authenticate a
  connection, provision an instance, and fetch welcome headers.
- `instance` — exercise containers posting back reset/submit/info events,
  authenticated with a per-instance signature.

Submodule imports at the bottom of this file register their routes on
`refbp` as a side effect of `import ref.services_api`.
"""

from typing import Any

from flask import jsonify


def error_response(msg: Any, code: int = 400):
    """Envelope for failed API requests. ``{"error": <msg>}``."""
    return jsonify({"error": msg}), code


def ok_response(msg: Any):
    """Envelope for successful API requests. Arbitrary JSON body."""
    return jsonify(msg), 200


# Side-effect imports — each submodule attaches routes to `refbp`.
from . import instance  # noqa: E402,F401
from . import ssh  # noqa: E402,F401
