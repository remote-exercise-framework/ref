"""SPA endpoint for checking the current user's authentication status."""

from flask_login import current_user

from ref import limiter, refbp
from ref.frontend_api import SPA_READ_LIMIT


@refbp.route("/api/v2/auth/me", methods=("GET",))
@limiter.limit(SPA_READ_LIMIT)
def spa_api_auth_me():
    """Return the authentication status of the current session.

    Shape (authenticated):

        {
          "authenticated": true,
          "is_admin": true,
          "is_grading_assistant": false
        }

    Shape (not authenticated):

        {
          "authenticated": false,
          "is_admin": false,
          "is_grading_assistant": false
        }
    """
    if current_user.is_authenticated:
        return {
            "authenticated": True,
            "is_admin": current_user.is_admin,
            "is_grading_assistant": current_user.is_grading_assistant,
        }, 200

    return {
        "authenticated": False,
        "is_admin": False,
        "is_grading_assistant": False,
    }, 200
