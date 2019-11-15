from werkzeug.urls import url_parse
from flask import url_for, redirect, request, abort
from ref.core import flash

def redirect_to_next(default='ref.admin_default_routes'):
    next_page = request.args.get('next')
    if not next_page or url_parse(next_page).netloc != '':
        next_page = url_for(default)
    return redirect(next_page)
