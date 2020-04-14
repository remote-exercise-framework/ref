from contextlib import contextmanager
from functools import wraps

import psycopg2
from flask import (abort, current_app, redirect, render_template, request,
                   url_for)
#http://initd.org/psycopg/docs/errors.html
from psycopg2.errors import DeadlockDetected, TransactionRollback
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from werkzeug.urls import url_parse

from ref.core import flash
from ref.model import SystemSettingsManager


def redirect_to_next(default='ref.admin_default_routes'):
    next_page = request.args.get('next')
    if not next_page or url_parse(next_page).netloc != '':
        next_page = url_for(default)
    return redirect(next_page)

@contextmanager
def retry_on_deadlock(retry_delay=0.5, retry_count=20):
    tries = 0
    try:
        yield
    except DeadlockDetected as e:
        if tries == retry_count:
            current_app.logger.warning(f'Giving up to lock database after {retry_delay*retry_count} seconds')
            raise e
        tries += 1
        current_app.logger.info(f'Deadlock during DB operation. Retry in {retry_delay}s ({tries} of {retry_count})', exc_info=True)

def unavailable_during_maintenance(func):
    """
    Only allow admins to access the given view.
    """
    @wraps(func)
    def decorated_view(*args, **kwargs):
        if SystemSettingsManager.MAINTENANCE_ENABLED.value:
            return render_template('maintenance.html')
        return func(*args, **kwargs)
    return decorated_view

def on_integrity_error(msg='Please retry.', flash_category='warning', log=True):
    if flash_category:
        getattr(flash, flash_category)(msg)
    if log:
        current_app.logger.warning('Integrity error during commit', exc_info=True)

def set_transaction_deferable_readonly(commit=True):
    current_app.db.session.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE READ ONLY DEFERRABLE;')

def is_db_serialization_error(err: DBAPIError):
    return getattr(err.orig, 'pgcode', None) == '40001'

def is_deadlock_error(err: OperationalError):
    ret = isinstance(err, DeadlockDetected) or isinstance(err.orig, DeadlockDetected)
    if ret:
        current_app.logger.warning('Deadlock detected', exc_info=True)
    return ret
