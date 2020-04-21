import logging
import os
import random
import uuid
from binascii import hexlify
from functools import wraps

from flask import current_app, jsonify, render_template, request
from werkzeug.exceptions import (BadRequest, Forbidden, Gone,
                                 InternalServerError, MethodNotAllowed,
                                 NotFound, TooManyRequests)

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
    if request.path.startswith('/api'):
        msg = jsonify(
            {'error': str(e)}
        )
        return msg, code
    return render_template('error.html',
                           smiley=random.choice(smileys_sad),
                           text=e,
                           title='{}'.format(code)), code

@errorhandler(NotFound.code)
def not_found(e, json=False):
    text = f'Not Found: Unable to find the requested ressource.'
    return render_error_template(text, NotFound.code, json)

@errorhandler(Forbidden.code)
def forbidden(e, json=False):
    return render_error_template(e, Forbidden.code, json)

@errorhandler(BadRequest.code)
def bad_request(e, json=False):
    return render_error_template(e, BadRequest.code, json)

@errorhandler(TooManyRequests.code)
def too_many_requests(e, json=False):
    return render_error_template(e, TooManyRequests.code, json)

@errorhandler(Exception)
@errorhandler(InternalServerError.code)
def internal_error(e):
    code = uuid.uuid4()
    logging.error(Exception(f"Code: {code}", e), exc_info=True)
    if current_app.debug:
        raise e

    text = f'Internal Server Error: If the problem persists, please contact the server administrator and provide the following error code {code}'
    is_json = False
    if hasattr(e, 'is_json_api'):
        is_json = True

    return render_error_template(text, InternalServerError.code, is_json)
