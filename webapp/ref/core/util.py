import os
import signal
import traceback
import sqlalchemy
from contextlib import contextmanager
from datetime import datetime
from functools import wraps
from multiprocessing import Lock, RLock

import psycopg2
from colorama import Fore, Style
from dateutil import tz
from flask import (abort, current_app, g, redirect, render_template, request,
                   url_for)
#http://initd.org/psycopg/docs/errors.html
from psycopg2.errors import DeadlockDetected, TransactionRollback
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from urllib.parse import urlparse as url_parse

from ref.core import flash
from ref.model import SystemSettingsManager

_database_lock = RLock()

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

# def lock_db():
#     _database_lock.acquire()
#     g.db_lock_cnt = g.get('db_lock_cnt', 0) + 1

# def unlock_db():
#     assert g.get('db_lock_cnt', 0) > 0
#     g.pop('db_lock_cnt', 0)
#     _database_lock.release()

# def have_db_lock():
#     return g.get('db_lock_cnt', 0) > 0

def lock_db(connection: sqlalchemy.engine.Connection, readonly=False):
    if readonly:
        connection.execute(sqlalchemy.text('select pg_advisory_xact_lock_shared(1234);'))
    else:
        connection.execute(sqlalchemy.text('select pg_advisory_xact_lock(1234);'))

def unlock_db_and_commit():
    current_app.db.session.commit()

def unlock_db_and_rollback():
    current_app.db.session.rollback()

# def unlock_db(readonly=False):
#     current_app.logger.info(f"Unlocking database (readonly={readonly})")
#     if readonly:
#         current_app.db.session.execute('select pg_advisory_unlock_shared(1337);')
#     else:
#         current_app.db.session.execute('select pg_advisory_unlock(1337);')

# def unlock_all_db():
#     current_app.logger.info(f"Releasing all DB locks")
#     current_app.db.session.execute('select pg_advisory_unlock_all();')

def utc_datetime_to_local_tz(ts: datetime):
    """
    Convert the given (UTC) datetime to a datetime with the local
    timezone.
    Args:
        ts - A datetime that must be in UTC
    """
    from_zone = tz.gettz('UTC')
    to_zone = tz.gettz(SystemSettingsManager.TIMEZONE.value)

    utc = ts.replace(tzinfo=from_zone)
    return utc.astimezone(to_zone)

def datetime_transmute_into_local(dt: datetime):
    """
    Change the datetime's timezone to the local timezone without
    considering its current timezone (if any).
    NOTE: The datetime is just interpreted as the local timezone while being
    treated as having no timezone at all.
    Args:
        ts - A datetime with an arbitrary timezone.
    Returns:
        The given `ts` with the timezone set to the local timezone.
    """
    to_zone = tz.gettz(SystemSettingsManager.TIMEZONE.value)
    return dt.replace(tzinfo=to_zone)

def datetime_to_naive_utc(dt: datetime):
    """
    Convert the given datetime from its current timezone into UTC.
    Next, the timezone is erased, yielding a naive datetime with no
    timezone attached.
    """
    return dt.astimezone(tz.tzutc()).replace(tzinfo=None)

def datetime_to_string(ts: datetime):
    if ts.tzinfo is None:
        ts = utc_datetime_to_local_tz(ts)
    return ts.strftime("%d/%m/%Y %H:%M:%S")

class AnsiColorUtil():

    @staticmethod
    def green(s):
        return Fore.GREEN + s + Style.RESET_ALL
    @staticmethod
    def yellow(s):
        return Fore.YELLOW + s + Style.RESET_ALL
    @staticmethod
    def red(s):
        return Fore.RED + s + Style.RESET_ALL

def failsafe():
    exc = traceback.format_exc()
    current_app.logger.error(f'Failsafe was triggered by the following exception:\n{exc}')

    has_uwsgi = True
    try:
        import uwsgi
    except ImportError:
        current_app.logger.warning('Not running under uwsgi, failsafe will not work.')
        has_uwsgi = False

    if current_app.debug:
        current_app.logger.warning('Running in debug mode, not triggering failsafe.')
    else:
        if has_uwsgi:
            os.kill(uwsgi.masterpid(), signal.SIGTERM)
