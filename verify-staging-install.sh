#!/bin/bash
set -eu

ROOT=/opt/farmcraft-staging

test "$(cat "$ROOT/farmcraft-evaluator/VERSION")" = "2026.10.12"
echo VERSION_OK

echo "dd37e57c78ef19d8ae0b60a3dbd3aa038a2892d919dbc57238a126a678f684c1  $ROOT/config/evaluation.json" | sha256sum -c -

test -x "$ROOT/farmcraft-evaluator/.venv/bin/python"
echo PYTHON_READY

docker image inspect nitw-farm-ai-evaluator:2026.10.12 >/dev/null
echo DOCKER_IMAGE_READY

test -f /etc/systemd/system/farmcraft-staging-worker@.service
echo SERVICE_READY

echo ALL_CHECKS_PASSED
