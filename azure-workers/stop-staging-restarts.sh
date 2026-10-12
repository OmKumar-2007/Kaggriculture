#!/usr/bin/env bash
set -euo pipefail
set +x
for slot in 01 02; do
  systemctl stop "farmcraft-staging-worker@${slot}.service" || true
  systemctl reset-failed "farmcraft-staging-worker@${slot}.service" || true
done
for slot in 01 02; do
  systemctl is-active "farmcraft-staging-worker@${slot}.service" || true
done
test -d /opt/farmcraft-staging
printf 'source_present=true\n'
if test -f /opt/farmcraft-staging/py_env.py; then
  printf 'py_env_present=true\n'
else
  printf 'py_env_present=false\n'
fi
if test -x /opt/farmcraft-staging/farmcraft-evaluator/.venv/bin/python; then
  printf 'venv_present=true\n'
fi
