#!/usr/bin/env bash
set -euo pipefail
set +x
slot="${slot:-}"
[[ "$slot" =~ ^[2-4]$ ]] || { echo 'Slot must be 2, 3 or 4.' >&2; exit 2; }
test -n "${registrationToken:-}" || { echo 'Missing protected registration token.' >&2; exit 2; }
root=/opt/farmcraft/farmcraft-evaluator
workers="$root/workers"
test -x "$root/.venv/bin/python" || { echo 'Evaluator environment is missing.' >&2; exit 3; }
test -f "$root/.env" || { echo 'Primary worker settings are missing.' >&2; exit 3; }
test ! -f "$workers/$slot.credentials.json" || { echo 'Worker slot already registered; refusing to overwrite identity.' >&2; exit 4; }
mkdir -p "$workers"
cp "$root/.env" "$workers/$slot.env"
sed -i -E "s/^WORKER_NAME=.*/WORKER_NAME=farmcraft-eval-0${slot}/; s/^WORKER_CONCURRENCY=.*/WORKER_CONCURRENCY=1/" "$workers/$slot.env"
chown -R farmcraft:farmcraft "$workers"
chmod 700 "$workers"
chmod 600 "$workers/$slot.env"
install -m 0644 /opt/farmcraft/azure-workers/farmcraft-worker@.service /etc/systemd/system/farmcraft-worker@.service
systemctl daemon-reload
cd "$root"
printf '%s\n' "$registrationToken" | runuser -u farmcraft -- env \
  FARMCRAFT_WORKER_ENV_FILE="$workers/$slot.env" \
  FARMCRAFT_WORKER_CREDENTIAL_FILE="$workers/$slot.credentials.json" \
  .venv/bin/python app/worker.py --register
unset registrationToken
chmod 600 "$workers/$slot.credentials.json"
systemctl enable --now "farmcraft-worker@$slot.service"
systemctl is-active "farmcraft-worker@$slot.service"
echo "Worker slot $slot registered and started."
