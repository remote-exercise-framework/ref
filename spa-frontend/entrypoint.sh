#!/bin/sh
set -eu

# The host bind mount can swap the source tree underneath us; make sure
# node_modules exists before running any npm scripts.
if [ ! -d node_modules ] || [ -z "$(ls -A node_modules 2>/dev/null || true)" ]; then
  echo "[spa-frontend] installing deps"
  if [ -f package-lock.json ]; then npm ci; else npm install; fi
fi

if [ "${HOT_RELOADING:-false}" = "true" ]; then
  echo "[spa-frontend] starting vite dev server (HMR)"
  exec npm run dev
else
  # The prod SPA bundle is baked into the frontend-proxy image at docker
  # build time (multi-stage Dockerfile). The spa-frontend service is
  # gated behind the `dev` compose profile and should never start without
  # HOT_RELOADING=true. Fail loudly if this branch is ever reached.
  echo "[spa-frontend] prod mode: this container should not run in prod; frontend-proxy bakes the bundle" >&2
  exit 1
fi
