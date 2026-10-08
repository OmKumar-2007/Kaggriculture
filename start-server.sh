#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
workers="${1:-2}"
[[ "$workers" =~ ^[1-8]$ ]] || { echo 'Worker count must be 1–8.' >&2; exit 1; }
command -v docker >/dev/null
command -v python3 >/dev/null
python3 -c 'import rq, redis, sqlalchemy, psycopg, psutil' || { echo 'Install python3 -m pip install -r requirements-worker.txt' >&2; exit 1; }
if [[ ! -f .env ]]; then
  read -rsp 'Choose organizer password (12+ characters): ' admin_password; echo
  [[ ${#admin_password} -ge 12 ]] || { echo 'Password too short.' >&2; exit 1; }
  if docker volume inspect kaggriculture_postgres_data >/dev/null 2>&1; then postgres_password=local-arena; else postgres_password="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"; fi
  ADMIN_PASSWORD_FOR_SETUP="$admin_password" python3 - "$postgres_password" <<'PY' > .env
import hashlib, os, secrets, sys
salt = secrets.token_hex(18)
digest = hashlib.pbkdf2_hmac('sha256', os.environ['ADMIN_PASSWORD_FOR_SETUP'].encode(), salt.encode(), 310000).hex()
print('POSTGRES_PASSWORD=' + sys.argv[1])
print("ADMIN_PASSWORD_HASH='pbkdf2_sha256$310000$" + salt + '$' + digest + "'")
print('ADMIN_SESSION_SECRET=' + secrets.token_hex(48))
print('FARMCRAFT_BIND_IP=0.0.0.0')
print('FARMCRAFT_PORT=8000')
print('MAX_SUBMISSION_SIZE_KB=256')
PY
  chmod 600 .env
  unset admin_password
fi
set -a; source .env; set +a
export DATABASE_URL="postgresql+psycopg://arena:${POSTGRES_PASSWORD}@127.0.0.1:5432/neural_coliseum"
export REDIS_URL=redis://127.0.0.1:6379/0 STORAGE_BACKEND=local LOCAL_STORAGE_ROOT="$PWD/data/objects" APP_ENV=local NEURAL_COLISEUM_TRUSTED_LOCAL=0 MAX_EVALUATION_WORKERS="$workers"
mkdir -p data/objects
docker build -t nitw-farm-ai-evaluator NITW_Farm_AI_Challenge_v1
docker compose up -d --build
if [[ -f data/host-worker.pid ]] && kill -0 "$(cat data/host-worker.pid)" 2>/dev/null; then echo 'Host worker already running.'; else nohup python3 -m backend.worker > data/host-worker.log 2> data/host-worker-errors.log & echo $! > data/host-worker.pid; fi
echo "FarmCraft: http://127.0.0.1:${FARMCRAFT_PORT:-8000}/"
hostname -I 2>/dev/null | tr ' ' '\n' | sed '/^$/d' | while read -r ip; do echo "LAN candidate: http://${ip}:${FARMCRAFT_PORT:-8000}/"; done
