#!/usr/bin/env bash
set -euo pipefail
set +x
root=/opt/farmcraft-staging
archive=/tmp/farmcraft-sandbox-fix-98aee45f326dc9f9c73f9f9fa2c996de68024d0e1929de6e5079f5ed77d40f4f.tgz
blob=https://fcstg6chsyox4t2zfa.blob.core.windows.net/worker-bootstrap/sandbox-fix-98aee45f326dc9f9c73f9f9fa2c996de68024d0e1929de6e5079f5ed77d40f4f.tgz
test -d "$root"
for slot in 01 02; do systemctl stop "farmcraft-staging-worker@$slot.service"; done
token=$(curl -fsS -H Metadata:true 'http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https%3A%2F%2Fstorage.azure.com%2F' | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
curl -fsS --retry 5 --retry-all-errors --retry-delay 6 \
  -H "Authorization: Bearer $token" -H 'x-ms-version: 2021-12-02' \
  "$blob" -o "$archive"
unset token
echo '98aee45f326dc9f9c73f9f9fa2c996de68024d0e1929de6e5079f5ed77d40f4f  /tmp/farmcraft-sandbox-fix-98aee45f326dc9f9c73f9f9fa2c996de68024d0e1929de6e5079f5ed77d40f4f.tgz' | sha256sum -c -
test "$(tar -tzf "$archive")" = 'backend/services/sandbox.py'
cp "$root/backend/services/sandbox.py" "$root/backend/services/sandbox.py.before-cluster-fix"
tar -xzf "$archive" -C "$root" --no-same-owner
chmod 0644 "$root/backend/services/sandbox.py"
rm -f "$archive"
install -d -m 0750 -o farmcraft -g farmcraft "$root/data/tmp"
unit=/etc/systemd/system/farmcraft-staging-worker@.service
cp "$unit" "$unit.before-cluster-fix"
if ! grep -q '^Environment=TMPDIR=' "$unit"; then
  sed -i '/^Environment=FARMCRAFT_WORKER_CREDENTIAL_FILE=/a Environment=TMPDIR=/opt/farmcraft-staging/data/tmp' "$unit"
fi
if ! grep -q '^ReadWritePaths=.* /opt/farmcraft-staging/data/tmp' "$unit"; then
  sed -i '/^ReadWritePaths=/s|$| /opt/farmcraft-staging/data/tmp|' "$unit"
fi
systemctl daemon-reload
cd "$root"
PYTHONPATH="$root:$root/farmcraft-evaluator/app" farmcraft-evaluator/.venv/bin/python -c 'from runner import execute; print("runner_import=ok")'
for slot in 01 02; do systemctl start "farmcraft-staging-worker@$slot.service"; done
sleep 12
for slot in 01 02; do
  state=$(systemctl is-active "farmcraft-staging-worker@$slot.service")
  printf 'slot_%s=%s\n' "$slot" "$state"
  test "$state" = active
done
printf 'sandbox_fix=ok\n'
