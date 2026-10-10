#!/usr/bin/env bash
set -euo pipefail
active=false
for unit in farmcraft-worker.service farmcraft-worker@2.service farmcraft-worker@3.service farmcraft-worker@4.service; do
  if systemctl is-active --quiet "$unit"; then active=true; fi
done
if [[ "$active" == true ]]; then
  echo 'ACTIVE_WORKER: drain and wait before deallocation.'
else
  echo 'SAFE_TO_DEALLOCATE'
fi
