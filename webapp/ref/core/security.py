from flask_login import login_required, current_user
from flask import current_app
from functools import wraps
from ref.core import flash
from pathlib import Path
from werkzeug.local import LocalProxy
from ref.model.enums import UserAuthorizationGroups

log = LocalProxy(lambda: current_app.logger)

def admin_required(func):
    """
    Only allow admins to access the given view.
    """
    @wraps(func)
    def decorated_view(*args, **kwargs):
        if UserAuthorizationGroups.ADMIN not in current_user.auth_groups:
            return current_app.login_manager.unauthorized()
        return func(*args, **kwargs)
    return login_required(decorated_view)

def grading_assistant_required(func):
    """
    Only allow admins and grading assistants to access the given view.
    """
    @wraps(func)
    def decorated_view(*args, **kwargs):
        if UserAuthorizationGroups.GRADING_ASSISTANT not in current_user.auth_groups and UserAuthorizationGroups.ADMIN not in current_user.auth_groups:
            return current_app.login_manager.unauthorized()
        return func(*args, **kwargs)
    return login_required(decorated_view)

def group_required(func, *groups):
    @wraps(func)
    def decorated_view(*args, **kwargs):
        user_auth_groups = current_user.auth_groups
        for g in groups:
            assert isinstance(g, UserAuthorizationGroups)
            if g not in user_auth_groups:
                return current_app.login_manager.unauthorized()
        return func(*args, **kwargs)

    return login_required(decorated_view)

def sanitize_path_is_subdir(parent_path, child_path):
    if isinstance(parent_path, str):
        parent_path = Path(parent_path)
    if isinstance(child_path, str):
        child_path = Path(child_path)

    try:
        parent_path = parent_path.resolve()
        child_path = child_path.resolve()
    except ValueError:
        log.warning(f'Failed to sanitize path', exc_info=True)
        return False

    return child_path.as_posix().startswith(parent_path.as_posix())