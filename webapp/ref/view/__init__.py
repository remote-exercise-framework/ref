# Route-registration side effects for the dedicated API packages. Nothing is
# re-exported directly from them here — `import ref.view` is the single entry
# point that wires every Flask route onto `refbp`, so we need the submodule
# imports to happen even though the names are unused.
import ref.frontend_api  # noqa: F401
import ref.services_api  # noqa: F401

from .build_status import api_build_status as api_build_status
from .exercise import admin_default_routes as admin_default_routes
from .exercise import exercise_browse as exercise_browse
from .exercise import exercise_build as exercise_build
from .exercise import exercise_diff as exercise_diff
from .exercise import exercise_do_import as exercise_do_import
from .exercise import exercise_view as exercise_view
from .exercise import exercise_view_all as exercise_view_all
from .file_browser import file_browser_load_file as file_browser_load_file
from .grading import grading_view_all as grading_view_all
from .grading import grading_view_exercise as grading_view_exercise
from .grading import grading_view_submission as grading_view_submission
from .graph import graph as graph
from .group import group_view_all as group_view_all
from .group_names import group_names_create as group_names_create
from .group_names import group_names_delete as group_names_delete
from .group_names import group_names_edit as group_names_edit
from .group_names import group_names_view_all as group_names_view_all
from .instances import instance_delete as instance_delete
from .instances import instance_stop as instance_stop
from .instances import instances_by_user_id as instances_by_user_id
from .instances import instances_view_all as instances_view_all
from .instances import instances_view_by_exercise as instances_view_by_exercise
from .instances import instances_view_details as instances_view_details
from .login import login as login
from .student import student_default_routes as student_default_routes
from .student import student_delete as student_delete
from .student import student_view_all as student_view_all
from .student import student_view_single as student_view_single
from .submission import submission_delete as submission_delete
from .submission import submission_reset as submission_reset
from .submission import submissions_by_instance as submissions_by_instance
from .submission import submissions_view_all as submissions_view_all
from .system import system_gc as system_gc
from .system_settings import view_system_settings as view_system_settings
