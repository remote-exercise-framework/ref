#!/bin/sh
set -eu

if [ "${HOT_RELOADING:-false}" = "true" ]; then
    ln -sf /etc/caddy/Caddyfile.dev /etc/caddy/Caddyfile
else
    python3 /usr/local/bin/render_caddyfile.py
fi

exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile
