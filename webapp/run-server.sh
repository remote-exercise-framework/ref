#!/bin/env bash

set -eu
set -o pipefail

readonly pid_file_path=/tmp/uwsgi.pid

#Trust secure headers even if the proxy is not running on localhost.
#Without this, X-FORWARDED-PROTO is not trusted and redirects are rewritten
#to http.
export FORWARDED_ALLOW_IPS="*"

# Ensure inotifywait is installed
if ! command -v inotifywait &> /dev/null; then
    echo "[!] inotifywait not found. Install it with: sudo apt install inotify-tools."
    return 1
fi


mkdir -p /data/log
args=""

echo "[+] Waiting for the DB container..."
wait-for -t 30 db:5432
echo "[+] DB is up, starting webserver."

function on_signal() {
    uwsgi --stop "$pid_file_path"
    exit 0
}

trap "on_signal" TERM INT

if [[ "$DEBUG" == "1" || "$DEBUG" == "true" || "$DEBUG" == "True" ]]; then
    # Our costom inotify loop since uwsgi's py-reload does not work if there are, e.g., syntax
    # errors. Such error cause the server stop responding to fs events.
    (
        # shellcheck disable=SC2034
        inotifywait -m -e modify,create,delete -r . | while read -r path action file; do
            # echo "[+] Detected $action on $file in $path, reloading"
            uwsgi --reload "$pid_file_path"
        done
    ) &
fi

# --py-autoreload=1 --- Check every second if any python file changed
# --disable-logging --- Do not log every request, i.e., GET ...
uwsgi \
    --http :8000 \
    --pidfile "$pid_file_path" \
    --http-keepalive \
    --disable-logging \
    --master \
    --processes 1 \
    --manage-script-name \
    --mount "/=ref:create_app()" \
    $args