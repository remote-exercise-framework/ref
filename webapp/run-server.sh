#!/bin/bash

set -e

source upgrade_db.sh

if [[ -z "$DEBUG" || "$DEBUG" == "0" ]]; then
    #Trust secure headers even if the proxy is not running on localhost.
    #Without this, X-FORWARDED-PROTO is not trusted and redirects are rewritten
    #to http.
    export FORWARDED_ALLOW_IPS="*"
    gunicorn -w 4 -b :8000 'ref:create_app()' --log-level debug --reload
else
    export FLASK_APP=ref
    export FLASK_DEBUG=1
    flask run --host 0.0.0.0 --port 8000
fi
