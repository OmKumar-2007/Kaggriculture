#!/bin/bash
set -euo pipefail

ROOT=/opt/farmcraft-staging
HASH=bddac87f053bed5dba7c0d27a4ae86ea2ef02e631b2bf39312bc8bb911c1c2fd
ARCHIVE=/tmp/farmcraft-worker-current.tgz
NEXT=/opt/farmcraft-staging-next

test ! -e "$NEXT" || {
    echo "STOP: staging replacement directory already exists"
    exit 3
}

export HASH ARCHIVE

python3 - <<'PY'
import json, os, urllib.parse, urllib.request

params = urllib.parse.urlencode({
    "api-version": "2018-02-01",
    "resource": "https://storage.azure.com/"
})

request = urllib.request.Request(
    "http://169.254.169.254/metadata/identity/oauth2/token?" + params,
    headers={"Metadata": "true"}
)

with urllib.request.urlopen(request, timeout=20) as response:
    token = json.load(response)["access_token"]

url = (
    "https://fcstg6chsyox4t2zfa.blob.core.windows.net/"
    "worker-bootstrap/farmcraft-worker-"
    + os.environ["HASH"] + ".tgz"
)

request = urllib.request.Request(
    url,
    headers={
        "Authorization": "Bearer " + token,
        "x-ms-version": "2023-11-03"
    }
)

with urllib.request.urlopen(request, timeout=90) as response:
    with open(os.environ["ARCHIVE"], "wb") as output:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)

print("DOWNLOAD_OK")
PY

echo "$HASH  $ARCHIVE" | sha256sum -c -

mkdir "$NEXT"
tar -xzf "$ARCHIVE" -C "$NEXT"

test "$(cat "$NEXT/farmcraft-evaluator/VERSION")" = "2026.10.12"

EXPECTED_CONFIG=dd37e57c78ef19d8ae0b60a3dbd3aa038a2892d919dbc57238a126a678f684c1
ACTUAL_CONFIG=$(sha256sum "$NEXT/config/evaluation.json" | cut -d ' ' -f1)
test "$ACTUAL_CONFIG" = "$EXPECTED_CONFIG"

test ! -d "$ROOT/farmcraft-evaluator/.venv" || {
    echo "STOP: existing Python environment needs inspection"
    exit 4
}

test ! -d "$ROOT/config/workers" || {
    echo "STOP: existing worker credentials need preservation"
    exit 4
}

BACKUP=/opt/farmcraft-staging-backup-20261012
test ! -e "$BACKUP"

mv "$ROOT" "$BACKUP"
mv "$NEXT" "$ROOT"

echo "UPDATED_SOURCE_OK"
