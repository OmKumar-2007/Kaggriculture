#!/usr/bin/env bash
set -euo pipefail
set +x
root=/opt/farmcraft-staging
archive=/tmp/farmcraft-root-modules-75eb82cdd4d467fed7861416f5e6d75745596dd6bfe863382f552b1fd837a56b.tgz
blob=https://fcstg6chsyox4t2zfa.blob.core.windows.net/worker-bootstrap/root-modules-75eb82cdd4d467fed7861416f5e6d75745596dd6bfe863382f552b1fd837a56b.tgz
test -d "$root"
token=$(curl -fsS -H Metadata:true 'http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https%3A%2F%2Fstorage.azure.com%2F' | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
curl -fsS --retry 8 --retry-all-errors --retry-delay 8 \
  -H "Authorization: Bearer $token" -H 'x-ms-version: 2021-12-02' \
  "$blob" -o "$archive"
unset token
echo '75eb82cdd4d467fed7861416f5e6d75745596dd6bfe863382f552b1fd837a56b  /tmp/farmcraft-root-modules-75eb82cdd4d467fed7861416f5e6d75745596dd6bfe863382f552b1fd837a56b.tgz' | sha256sum -c -
test "$(tar -tzf "$archive" | sort | tr '\n' ' ')" = 'py_env.py run_match.py tournament.py '
tar -xzf "$archive" -C "$root" --no-same-owner
chmod 0644 "$root/py_env.py" "$root/run_match.py" "$root/tournament.py"
rm -f "$archive"
cd "$root"
PYTHONPATH="$root:$root/farmcraft-evaluator/app" farmcraft-evaluator/.venv/bin/python -c 'from runner import execute; print("runner_import=ok")'
printf 'root_module_install=ok\n'
