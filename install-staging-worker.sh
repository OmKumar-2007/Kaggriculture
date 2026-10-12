#!/bin/bash
set -euo pipefail

ROOT=/opt/farmcraft-staging
HASH=6d7981469ec3e931c36de96df5a9e0e7339dc3120cdaa87a6c8da506cee5d116
ARCHIVE=/tmp/farmcraft-worker-source.tgz

if test -f "$ROOT/farmcraft-evaluator/app/worker.py"; then
    echo "SOURCE_ALREADY_INSTALLED"
    exit 0
fi

export HASH ARCHIVE

python3 - <<'PY'
import json
import os
import urllib.parse
import urllib.request

metadata = "http://169.254.169.254/metadata/identity/oauth2/token"
query = urllib.parse.urlencode({
    "api-version": "2018-02-01",
    "resource": "https://storage.azure.com/"
})

request = urllib.request.Request(
    metadata + "?" + query,
    headers={"Metadata": "true"}
)

with urllib.request.urlopen(request, timeout=20) as response:
    token = json.load(response)["access_token"]

blob_url = (
    "https://fcstg6chsyox4t2zfa.blob.core.windows.net/"
    "worker-bootstrap/farmcraft-worker-"
    + os.environ["HASH"] + ".tgz"
)

request = urllib.request.Request(
    blob_url,
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

mkdir -p "$ROOT"
tar -xzf "$ARCHIVE" -C "$ROOT"

test -f "$ROOT/farmcraft-evaluator/app/worker.py"
test -f "$ROOT/config/evaluation.json"

echo "SOURCE_INSTALLED"
