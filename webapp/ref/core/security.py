from flask_login import login_required, current_user
from flask import current_app
from functools import wraps
from ref.core import flash
from pathlib import Path

def admin_required(func):
    @wraps(func)
    def decorated_view(*args, **kwargs):
        if 'LOGIN_DISABLED' in current_app.config and current_app.config['LOGIN_DISABLED']:
            pass
        elif not current_user.is_admin:
            return current_app.login_manager.unauthorized()
        return func(*args, **kwargs)
    return login_required(decorated_view)


def sanitize_path_is_subdir(parent_path, child_path):
    if isinstance(parent_path, str):
        parent_path = Path(parent_path)
    if isinstance(child_path, str):
        child_path = Path(child_path)

    parent_path = parent_path.resolve()
    child_path = child_path.resolve()

    return child_path.as_posix().startswith(parent_path.as_posix())