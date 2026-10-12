#!/bin/bash
set -euo pipefail

ROOT=/opt/farmcraft-staging
cd "$ROOT"

echo "=== Checking evaluation configuration ==="
EXPECTED=dd37e57c78ef19d8ae0b60a3dbd3aa038a2892d919dbc57238a126a678f684c1
ACTUAL=$(sha256sum config/evaluation.json | cut -d ' ' -f1)

if [ "$ACTUAL" != "$EXPECTED" ]; then
    echo "ERROR: Evaluation configuration hash mismatch"
    exit 1
fi

echo "CONFIG_HASH_OK"

echo "=== Checking evaluator version ==="
cat farmcraft-evaluator/VERSION

echo "=== Installing Python environment ==="
python3 -m venv farmcraft-evaluator/.venv
farmcraft-evaluator/.venv/bin/python -m pip install -r farmcraft-evaluator/requirements.txt

echo "=== Building evaluator Docker image ==="
docker build \
    -t nitw-farm-ai-evaluator:2026.10.12 \
    -f NITW_Farm_AI_Challenge_v1/Dockerfile \
    NITW_Farm_AI_Challenge_v1

echo "=== Configuring ownership ==="
chown -R farmcraft:farmcraft "$ROOT"
chmod 755 "$ROOT"

echo "=== Installing staging service ==="
install -m 0644 \
    azure-primary/farmcraft-staging-worker@.service \
    /etc/systemd/system/farmcraft-staging-worker@.service

systemctl daemon-reload

echo "INSTALLATION_COMPLETE"
