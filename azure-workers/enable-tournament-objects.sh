#!/usr/bin/env bash
set -euo pipefail
set +x
root=/opt/farmcraft-staging
unit=/etc/systemd/system/farmcraft-staging-worker@.service
test -f "$unit"
for slot in 01 02; do systemctl stop "farmcraft-staging-worker@$slot.service"; done
install -d -m 0750 -o farmcraft -g farmcraft "$root/data/objects"
cp "$unit" "$unit.before-tournament-objects"
if ! grep -q '^ReadWritePaths=.* /opt/farmcraft-staging/data/objects' "$unit"; then
  sed -i '/^ReadWritePaths=/s|$| /opt/farmcraft-staging/data/objects|' "$unit"
fi
systemctl daemon-reload
for slot in 01 02; do systemctl start "farmcraft-staging-worker@$slot.service"; done
sleep 12
for slot in 01 02; do
  state=$(systemctl is-active "farmcraft-staging-worker@$slot.service")
  printf 'slot_%s=%s\n' "$slot" "$state"
  test "$state" = active
done
printf 'tournament_objects=ok\n'
