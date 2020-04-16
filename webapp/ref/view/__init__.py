from .api import api_get_header, api_getkeys, api_getuserinfo, api_provision
from .exercise import (admin_default_routes, exercise_build, exercise_diff,
                       exercise_do_import, exercise_view, exercise_view_all)
from .grading import (grading_view_all, grading_view_exercise,
                      grading_view_submission)
from .graph import graph
from .group import group_view_all
from .instances import (instance_delete, instance_stop, instances_by_user_id,
                        instances_view_all, instances_view_by_exercise,
                        instances_view_details)
from .login import login
from .student import (student_default_routes, student_delete, student_getkey,
                      student_restorekey, student_view_all,
                      student_view_single)
from .submission import (submission_delete, submission_reset,
                         submissions_by_instance, submissions_view_all)
from .system import system_gc
from .system_settings import view_system_settings
