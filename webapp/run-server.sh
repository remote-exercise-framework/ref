#!/bin/bash

set -e

#Trust secure headers even if the proxy is not running on localhost.
#Without this, X-FORWARDED-PROTO is not trusted and redirects are rewritten
#to http.
export FORWARDED_ALLOW_IPS="*"

mkdir -p /data/log
args=""

# --disable-logging : Disables loggin of request information ("GET /../index.html...").

if [[ "$DEBUG" == "1" || "$TESTING" == "1" ]]; then
    #--py-autoreload=1 --- Check every second if any python file changed
    uwsgi --http :8000 --disable-logging --master --py-autoreload=1 --processes 4 --manage-script-name --mount "/=ref:create_app()" $args
else
    uwsgi --http :8000 --disable-logging --master --processes 4 --manage-script-name --mount "/=ref:create_app()" --logger file:logfile=/data/log/uwsgi.log,maxsize=33554432 $args
fi
