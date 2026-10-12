#!/usr/bin/env bash
set -euo pipefail
set +x
root=/opt/farmcraft-staging
cd "$root"
version=$(cat farmcraft-evaluator/VERSION)
config_sha=$(sha256sum config/evaluation.json | cut -d ' ' -f1)
test "$version" = 2026.10.12
test "$config_sha" = dd37e57c78ef19d8ae0b60a3dbd3aa038a2892d919dbc57238a126a678f684c1
test -f py_env.py && test -f run_match.py && test -f tournament.py
PYTHONPATH="$root:$root/farmcraft-evaluator/app" farmcraft-evaluator/.venv/bin/python -c 'from runner import execute'
docker image inspect nitw-farm-ai-evaluator:2026.10.12 >/dev/null
install -d -m 0750 -o farmcraft -g farmcraft "$root/data/replays"
unit=/etc/systemd/system/farmcraft-staging-worker@.service
test -f "$unit"
grep -q 'ProtectSystem=strict' "$unit"
grep -q '^ReadWritePaths=' "$unit"
if ! grep -q '^ReadWritePaths=.* /opt/farmcraft-staging/data/replays' "$unit"; then
  sed -i '/^ReadWritePaths=/s|$| /opt/farmcraft-staging/data/replays|' "$unit"
fi
systemctl daemon-reload
for slot in 01 02; do
  test -s "$root/config/workers/$slot.env"
  test -s "$root/config/workers/$slot.credentials.json"
  systemctl start "farmcraft-staging-worker@$slot.service"
done
sleep 12
printf 'version=%s\nconfig_sha=%s\n' "$version" "$config_sha"
for slot in 01 02; do
  state=$(systemctl is-active "farmcraft-staging-worker@$slot.service")
  printf 'slot_%s=%s\n' "$slot" "$state"
  test "$state" = active
done
printf 'worker_start=ok\n'
