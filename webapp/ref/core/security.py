from flask_login import login_required, current_user
from flask import current_app
from functools import wraps
from ref.core import flash

def admin_required(func):
    @wraps(func)
    def decorated_view(*args, **kwargs):
        if 'LOGIN_DISABLED' in current_app.config and current_app.config['LOGIN_DISABLED']:
            pass
        elif not current_user.is_admin:
            return current_app.login_manager.unauthorized()
        return func(*args, **kwargs)
    return login_required(decorated_view)