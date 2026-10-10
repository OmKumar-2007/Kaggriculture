#!/usr/bin/env bash
set -euo pipefail
set +x
test -n "${registrationToken:-}" || { echo 'Missing protected registration token' >&2; exit 2; }
test -x /opt/farmcraft/farmcraft-evaluator/.venv/bin/python || { echo 'Cloud-init has not completed' >&2; exit 3; }
cd /opt/farmcraft/farmcraft-evaluator
if test -f credentials.json; then
  echo 'Worker is already registered; refusing to overwrite its identity.' >&2
  exit 4
fi
printf '%s\n' "$registrationToken" | runuser -u farmcraft -- .venv/bin/python app/worker.py --register
unset registrationToken
chmod 600 credentials.json
systemctl enable --now farmcraft-worker.service
echo 'Worker registered and service started.'
