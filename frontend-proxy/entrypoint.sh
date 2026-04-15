#!/bin/sh
set -eu

if [ "${HOT_RELOADING:-false}" = "true" ]; then
    ln -sf /etc/caddy/Caddyfile.dev /etc/caddy/Caddyfile
else
    ln -sf /etc/caddy/Caddyfile.prod /etc/caddy/Caddyfile
fi

exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile
