#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ -f data/host-worker.pid ]]; then
  worker="$(cat data/host-worker.pid)"
  pkill -P "$worker" 2>/dev/null || true
  kill "$worker" 2>/dev/null || true
  rm data/host-worker.pid
fi
docker compose down
echo 'FarmCraft stopped; data volumes preserved.'
