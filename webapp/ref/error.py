from flask import render_template, current_app
from werkzeug.exceptions import Forbidden
from werkzeug.exceptions import Gone
from werkzeug.exceptions import InternalServerError
from werkzeug.exceptions import MethodNotAllowed
from werkzeug.exceptions import NotFound
from functools import wraps
import random
from binascii import hexlify
import logging
import os
import uuid
error_handlers = []

smileys_sad = [u'😐', u'😑', u'😒', u'😓', u'😔', u'😕', u'😖', u'😝', u'😞', u'😟',
               u'😠', u'😡', u'😢', u'😣', u'😥', u'😦', u'😧', u'😨', u'😩', u'😪',
               u'😫', u'😭', u'😮', u'😯', u'😰', u'😱', u'😲', u'😵', u'😶', u'😾',
               u'😿', u'🙀']

def errorhandler(code_or_exception):
    def decorator(func):
        error_handlers.append({'func': func, 'code_or_exception': code_or_exception})

        @wraps(func)
        def wrapped(*args, **kwargs):
            return func(*args, **kwargs)
        return wrapped
    return decorator

def render_error_template(e, code, json=False):
    if json:
        return {'message': e}, code
    return render_template('error.html',
                           smiley=random.choice(smileys_sad),
                           text=e,
                           title='{}'.format(code)), code

@errorhandler(NotFound.code)
def not_found(e='404: Not Found', json=False):
    text = f'Not Found: Unable to find the requested ressource.'
    return render_error_template(text, NotFound.code, json)

@errorhandler(Forbidden.code)
def forbidden(e='Forbidden', json=False):
    return render_error_template(e, Forbidden.code, json)

@errorhandler(Exception)
@errorhandler(InternalServerError.code)
def internal_error(e):
    code = uuid.uuid4()
    logging.error(Exception(f"Code: {code}", e), exc_info=True)
    if current_app.config['DEBUG']:
        raise e

    text = f'Internal Server Error: If the problem persists, please contact the server administrator and provide the following error code {code}'
    return render_error_template(text, InternalServerError.code)
