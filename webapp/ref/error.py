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

def is_api_request():
    return request.path.startswith('/api')

def errorhandler(code_or_exception):
    def decorator(func):
        error_handlers.append({'func': func, 'code_or_exception': code_or_exception})

        @wraps(func)
        def wrapped(*args, **kwargs):
            return func(*args, **kwargs)
        return wrapped
    return decorator

def render_error_template(e, code):
    if is_api_request():
        msg = jsonify(
            {'error': str(e)}
        )
        return msg, code
    return render_template('error.html',
                           smiley=random.choice(smileys_sad),
                           text=e,
                           title='{}'.format(code)), code

@errorhandler(NotFound.code)
def not_found(e):
    text = f'Not Found: Unable to find the requested ressource.'
    return render_error_template(text, NotFound.code)

@errorhandler(Forbidden.code)
def forbidden(e):
    return render_error_template(e, Forbidden.code)

@errorhandler(BadRequest.code)
def bad_request(e):
    return render_error_template(e, BadRequest.code)

@errorhandler(TooManyRequests.code)
def too_many_requests(e):
    return render_error_template(e, TooManyRequests.code)

@errorhandler(Exception)
@errorhandler(InternalServerError.code)
def internal_error(e):
    code = uuid.uuid4()
    logging.error(Exception(f"Code: {code}", e), exc_info=True)

    text = f'Internal Error: If the problem persists, please contact the server administrator and provide the following error code {code}'
    return render_error_template(text, InternalServerError.code)
