#!/usr/bin/env bash
set -euo pipefail
systemctl is-active farmcraft-worker.service || true
systemctl is-enabled farmcraft-worker.service || true
cloud-init status --short || true
docker info --format '{{.ServerVersion}}' || true
journalctl -u farmcraft-worker.service -n 12 --no-pager --output=cat | sed -E 's/(Bearer |credential[=:])[A-Za-z0-9._-]+/\1[redacted]/g'
