#!/usr/bin/env bash
set -euo pipefail
test -f /opt/farmcraft/farmcraft-evaluator/credentials.json || { echo 'Register first' >&2; exit 2; }
rm -f /opt/farmcraft/farmcraft-evaluator/.drain
systemctl start farmcraft-worker.service
systemctl is-active farmcraft-worker.service
for slot in 2 3 4; do
  if test -f "/opt/farmcraft/farmcraft-evaluator/workers/$slot.credentials.json"; then
    systemctl start "farmcraft-worker@$slot.service"
    systemctl is-active "farmcraft-worker@$slot.service"
  fi
done
