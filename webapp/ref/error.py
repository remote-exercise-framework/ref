import logging
import os
import random
import uuid
from binascii import hexlify
from functools import wraps, partial

from flask import current_app, jsonify, render_template, request
from werkzeug.exceptions import (BadRequest, Forbidden, Gone,
                                 InternalServerError, MethodNotAllowed,
                                 NotFound, TooManyRequests)

from ref.core import InconsistentStateError, failsafe

error_handlers = []

smileys_sad = [u'😐', u'😑', u'😒', u'😓', u'😔', u'😕', u'😖', u'😝', u'😞', u'😟',
               u'😠', u'😡', u'😢', u'😣', u'😥', u'😦', u'😧', u'😨', u'😩', u'😪',
               u'😫', u'😭', u'😮', u'😯', u'😰', u'😱', u'😲', u'😵', u'😶', u'😾',
               u'😿', u'🙀']

def is_api_request():
    return request.path.startswith('/api')

def errorhandler(code_or_exception):
    def decorator(func):
        if hasattr(func, '__fn'):
            f = getattr(func, '__fn')
        f = partial(func, code_or_exception)
        error_handlers.append({'func': f, 'code_or_exception': code_or_exception})

        @wraps(func)
        def wrapped(*args, **kwargs):
            return func(*args, **kwargs)
        #Save reference to original fn
        setattr(wrapped, '__fn', func)
        return wrapped

    return decorator

def render_error_template(e, code):
    current_app.logger.info(f'code={code}, error="{e}", path={request.path}')
    if is_api_request():
        msg = jsonify(
            {'error': str(e)}
        )
        return msg, code
    return render_template('error.html',
                           smiley=random.choice(smileys_sad),
                           text=e,
                           title='{}'.format(code)), code

@errorhandler(TooManyRequests.code)
@errorhandler(BadRequest.code)
@errorhandler(Forbidden.code)
@errorhandler(NotFound.code)
@errorhandler(MethodNotAllowed.code)
def handle_common_errors(code, e):
    return render_error_template(e, code)

@errorhandler(Exception)
@errorhandler(InternalServerError.code)
def internal_error(_, e):
    code = uuid.uuid4()
    current_app.logger.error(f"InternalServerError: {e}", exc_info=True)

    if isinstance(e, (AssertionError, InconsistentStateError)):
        failsafe()

    text = f'Internal Error: If the problem persists, please contact the server administrator and provide the following error code {code}'
    return render_error_template(text, InternalServerError.code)
