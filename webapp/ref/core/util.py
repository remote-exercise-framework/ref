from werkzeug.urls import url_parse
from flask import url_for, redirect, request, abort, current_app
from ref.core import flash
from contextlib import contextmanager
#http://initd.org/psycopg/docs/errors.html
from psycopg2.errors import TransactionRollback, DeadlockDetected

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
