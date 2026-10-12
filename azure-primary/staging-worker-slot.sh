#!/usr/bin/env bash
set -euo pipefail
set +x
action="${1:-status}"
slot="${2:-01}"
[[ "$slot" =~ ^(0[1-9]|10)$ ]] || { echo 'Slot must be 01 through 10.' >&2; exit 2; }
root=/opt/farmcraft-staging
workers="$root/config/workers"
service="farmcraft-staging-worker@$slot.service"
profile="$workers/$slot.env"
credential="$workers/$slot.credentials.json"

case "$action" in
  prepare)
    test -d "$root" && test -f "$root/config/profile-templates/azure-laptop.env.example"
    install -d -m 0700 -o farmcraft -g farmcraft "$workers"
    test ! -e "$profile" && test ! -e "$credential" || { echo 'Slot already exists.' >&2; exit 3; }
    install -m 0600 -o farmcraft -g farmcraft "$root/config/profile-templates/azure-laptop.env.example" "$profile"
    sed -i -e 's|^FARMCRAFT_API_URL=.*|FARMCRAFT_API_URL=https://farmcraft-staging-api.livelybush-912ee7d2.koreacentral.azurecontainerapps.io|' \
      -e "s/^WORKER_NAME=.*/WORKER_NAME=farmcraft-staging-$slot/" \
      -e 's/^WORKER_CONCURRENCY=.*/WORKER_CONCURRENCY=1/' "$profile"
    echo "Prepared staging slot $slot. Verify compatibility and host capacity, then register with a one-use token."
    ;;
  register)
    test -f "$profile" && test ! -e "$credential" || { echo 'Slot not prepared or credential exists.' >&2; exit 3; }
    test -t 0 || { echo 'Register from an interactive terminal; token prompt needs a TTY.' >&2; exit 3; }
    runuser -u farmcraft -- env FARMCRAFT_WORKER_ENV_FILE="$profile" \
      FARMCRAFT_WORKER_CREDENTIAL_FILE="$credential" \
      "$root/farmcraft-evaluator/.venv/bin/python" "$root/farmcraft-evaluator/app/worker.py" --register
    chmod 0600 "$credential"
    ;;
  start)
    test -f "$profile" && test -f "$credential" || { echo 'Register first.' >&2; exit 3; }
    rm -f "$workers/$slot.credentials.drain"
    systemctl enable --now "$service"
    ;;
  restart)
    test -f "$profile" && test -f "$credential" || { echo 'Register first.' >&2; exit 3; }
    rm -f "$workers/$slot.credentials.drain"
    systemctl restart "$service"
    ;;
  status) systemctl status --no-pager "$service" ;;
  logs) journalctl -u "$service" --no-pager -n 60 ;;
  drain)
    test -f "$credential" || { echo 'Credential missing.' >&2; exit 3; }
    touch "$workers/$slot.credentials.drain"
    chown farmcraft:farmcraft "$workers/$slot.credentials.drain"
    echo 'Drain requested. Confirm no active jobs in Admin before revoking.'
    ;;
  stop)
    systemctl stop "$service"
    ;;
  *) echo 'Usage: staging-worker-slot.sh prepare|register|start|restart|status|logs|drain|stop SLOT' >&2; exit 2 ;;
esac
