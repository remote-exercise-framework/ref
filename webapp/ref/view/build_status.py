"""Exercise build-status polling endpoint for the admin dashboard."""

from flask import jsonify

from ref import refbp
from ref.core import admin_required
from ref.model import Exercise


@refbp.route("/api/build-status")
@admin_required
def api_build_status():
    """Map exercise id → build status, used by the exercises list UI."""
    exercises = Exercise.query.all()
    return jsonify({str(e.id): e.build_job_status.value for e in exercises})
