from .api import api_getkeys, api_getuserinfo, api_provision
from .exercise import (admin_default_routes, exercise_build, exercise_diff,
                       exercise_do_import, exercise_view, exercise_view_all)
from .graph import graph
from .instances import (instance_delete, instance_stop, instances_by_user_id,
                        instances_view_all, instances_view_by_exercise,
                        instances_view_details)
from .login import login
from .student import (student_default_routes, student_delete, student_getkey,
                      student_restorekey, student_view_all,
                      student_view_single)
from .system import system_gc