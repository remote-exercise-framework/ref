#!/bin/bash

set -e

#Trust secure headers even if the proxy is not running on localhost.
#Without this, X-FORWARDED-PROTO is not trusted and redirects are rewritten
#to http.
export FORWARDED_ALLOW_IPS="*"

uwsgi --http :8000 --master --processes 4 --manage-script-name --mount "/=ref:create_app()"

# if [[ -z "$DEBUG" || "$DEBUG" == "0" ]]; then
#     #gunicorn -w 4 -b :8000 'ref:create_app()' --log-level debug --reload
    
# else
#     uwsgi --http :8000 --master --processes 4 --manage-script-name --mount "/=ref:create_app()"
# fi
