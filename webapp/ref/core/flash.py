import flask

def success(msg):
    flask.flash(msg, 'success')

def warning(msg):
    flask.flash(msg, 'warning')

def info(msg):
    flask.flash(msg, 'info')

def error(msg):
    flask.flash(msg, 'error')