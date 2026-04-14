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
  echo "[spa-frontend] building and starting vite preview"
  npm run build
  exec npm run preview
fi
