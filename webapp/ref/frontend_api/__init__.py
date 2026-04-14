"""JSON API consumed by the Vue frontend served from the `spa-frontend` container.

Every endpoint in this package lives under the `/api/v2/*` URL prefix and is
registered on the main `refbp` blueprint through the submodule imports at the
bottom of this file. Submodules are split by logical domain (`students.py`,
later `exercises.py`, `instances.py`, …) so growth is additive.

All endpoints here are intentionally CSRF-exempt. The Flask app has no
`CSRFProtect` middleware and the existing `/api/scoreboard/*` endpoints are
already consumed unauthenticated; rate limiting carries the abuse-prevention
burden.
"""

from typing import Any

from flask import jsonify


# Shared rate-limit strings — use these so every SPA endpoint rate-limits
# consistently and changes happen in one place.
SPA_WRITE_LIMIT = "16 per minute;1024 per day"
SPA_READ_LIMIT = "60 per minute"


def spa_api_error(
    form_message: str,
    fields: dict[str, list[str]] | None = None,
    status: int = 400,
) -> tuple[Any, int]:
    """Return the shared error envelope used by every SPA endpoint.

    The shape deliberately differs from `api.error_response`'s flat string so
    the SPA can surface per-field validation errors alongside a top-level
    form message.
    """
    body: dict[str, Any] = {"error": {"form": form_message}}
    if fields:
        body["error"]["fields"] = fields
    return jsonify(body), status


# Importing the submodules registers their routes on `refbp`.
from . import scoreboard  # noqa: E402,F401
from . import students  # noqa: E402,F401
