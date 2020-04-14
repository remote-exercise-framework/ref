import flask


def success(msg):
    flask.flash(msg, 'success')
    flask.current_app.logger.debug(f'flash.success({msg})')

def warning(msg):
    flask.flash(msg, 'warning')
    flask.current_app.logger.debug(f'flash.warning({msg})')

def info(msg):
    flask.flash(msg, 'info')
    flask.current_app.logger.debug(f'flash.info({msg})')

def error(msg):
    flask.flash(msg, 'error')
    flask.current_app.logger.debug(f'flash.error({msg})')
