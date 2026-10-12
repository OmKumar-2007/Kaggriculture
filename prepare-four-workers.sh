#!/bin/bash
set -euo pipefail

ROOT=/opt/farmcraft-staging
WORKERS="$ROOT/config/workers"

test -x "$ROOT/farmcraft-evaluator/.venv/bin/python"
test -f /etc/systemd/system/farmcraft-staging-worker@.service

install -d -m 0700 -o farmcraft -g farmcraft "$WORKERS"

HOST=$(hostname)

case "$HOST" in
  farmcraft-eval-02) PREFIX=farmcraft-kr ;;
  farmcraft-eval-03) PREFIX=farmcraft-id ;;
  *) echo "Unexpected VM hostname: $HOST"; exit 1 ;;
esac

for SLOT in 01 02; do
  PROFILE="$WORKERS/$SLOT.env"

  if test -e "$PROFILE"; then
    echo "Existing profile $PROFILE; refusing overwrite"
    exit 2
  fi

  install -m 0600 -o farmcraft -g farmcraft \
    "$ROOT/config/profile-templates/azure-laptop.env.example" \
    "$PROFILE"

  sed -i \
    -e 's|^FARMCRAFT_API_URL=.*|FARMCRAFT_API_URL=https://farmcraft-staging-api.livelybush-912ee7d2.koreacentral.azurecontainerapps.io|' \
    -e "s/^WORKER_NAME=.*/WORKER_NAME=$PREFIX-$SLOT/" \
    -e 's/^WORKER_CONCURRENCY=.*/WORKER_CONCURRENCY=1/' \
    "$PROFILE"

  echo "PREPARED: $PREFIX-$SLOT"
done
