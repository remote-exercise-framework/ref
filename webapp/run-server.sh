#!/bin/bash

set -e

source upgrade_db.sh

if [[ -z "$DEBUG" || "$DEBUG" == "0" ]]; then
    gunicorn -w 4 -b :8000 'ref:create_app()' --log-level debug --reload
else
    export FLASK_APP=ref
    export FLASK_DEBUG=1
    flask run --host 0.0.0.0 --port 8000
fi