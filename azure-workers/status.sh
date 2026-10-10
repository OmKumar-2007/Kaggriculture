#!/usr/bin/env bash
set -euo pipefail
systemctl is-active farmcraft-worker.service || true
systemctl is-enabled farmcraft-worker.service || true
for slot in 2 3 4; do
  if test -f "/opt/farmcraft/farmcraft-evaluator/workers/$slot.credentials.json"; then
    printf 'slot %s: ' "$slot"
    systemctl is-active "farmcraft-worker@$slot.service" || true
  fi
done
cloud-init status || true
docker info --format '{{.ServerVersion}}' || true
journalctl -u farmcraft-worker.service -n 12 --no-pager --output=cat | sed -E 's/(Bearer |credential[=:])[A-Za-z0-9._-]+/\1[redacted]/g'
