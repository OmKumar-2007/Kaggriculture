#!/usr/bin/env bash
set -euo pipefail
package="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo="$(dirname "$package")"
[[ "$(uname -s)" == Linux ]] || { echo 'Ubuntu Linux required.' >&2; exit 1; }
command -v python3.11 >/dev/null || { echo 'Install Python 3.11 and python3.11-venv.' >&2; exit 1; }
command -v docker >/dev/null || { echo 'Install Docker Engine and permit this user to access it.' >&2; exit 1; }
docker info >/dev/null || { echo 'Start Docker Engine before setup.' >&2; exit 1; }
if [[ ! -f "$package/.env" ]]; then
  read -r -p 'FarmCraft API HTTPS URL: ' api_url
  read -r -p 'Evaluator laptop name: ' worker_name
  sed -e "s|https://your-api.onrender.com|${api_url%/}|" -e "s|Evaluation-Laptop-1|$worker_name|" "$package/.env.example" > "$package/.env"
fi
python3.11 -m venv "$package/.venv"
"$package/.venv/bin/python" -m pip install --disable-pip-version-check -r "$package/requirements.txt"
version="$(tr -d '\r\n' < "$package/VERSION")"
docker build -t "nitw-farm-ai-evaluator:$version" "$repo/NITW_Farm_AI_Challenge_v1"
"$package/.venv/bin/python" "$package/scripts/doctor.py"
"$package/.venv/bin/python" "$package/app/worker.py" --register
chmod 600 "$package/credentials.json"
echo 'Setup complete. Run farmcraft-evaluator/scripts/start-worker.sh.'
