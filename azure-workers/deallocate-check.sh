#!/usr/bin/env bash
set -euo pipefail
if systemctl is-active --quiet farmcraft-worker.service; then
  echo 'ACTIVE_WORKER: drain and wait before deallocation.'
else
  echo 'SAFE_TO_DEALLOCATE'
fi
