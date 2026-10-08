#!/usr/bin/env bash
set -euo pipefail
package="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$package/.venv/bin/python" "$package/app/worker.py"
