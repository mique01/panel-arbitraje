#!/usr/bin/env bash
set -euo pipefail

ALLOWED_ORIGIN="${RENDER_EXTERNAL_HOSTNAME:-*}"

exec panel serve app.py \
  --address 0.0.0.0 \
  --port "${PORT:-10000}" \
  --num-procs 1 \
  --allow-websocket-origin="${ALLOWED_ORIGIN}"
