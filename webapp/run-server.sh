#!/bin/bash

set -e

#Trust secure headers even if the proxy is not running on localhost.
#Without this, X-FORWARDED-PROTO is not trusted and redirects are rewritten
#to http.
export FORWARDED_ALLOW_IPS="*"

mkdir /data/log
args=" --logger file:logfile=/data/log/uwsgi.log,maxsize=33554432 "
if [[ ! -z "$DEBUG" && "$DEBUG" == "1" ]]; then
    #--py-autoreload=1 --- Check every second if any python file changed
    uwsgi --http :8000 --master --py-autoreload=1 --processes 4 --manage-script-name --mount "/=ref:create_app()" $args
else
    uwsgi --http :8000 --master --processes 4 --manage-script-name --mount "/=ref:create_app()" $args
fi

# if [[ -z "$DEBUG" || "$DEBUG" == "0" ]]; then
#     #gunicorn -w 4 -b :8000 'ref:create_app()' --log-level debug --reload
    
# else
#     uwsgi --http :8000 --master --processes 4 --manage-script-name --mount "/=ref:create_app()"
# fi
