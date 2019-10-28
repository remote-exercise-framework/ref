from flask_login import login_required, current_user
from flask import current_app
from functools import wraps

def admin_required(func):
    @wraps(func)
    def decorated_view(*args, **kwargs):
        if not current_user.is_admin:
            return current_app.login_manager.unauthorized()
        return func(*args, **kwargs)
    return login_required(decorated_view)