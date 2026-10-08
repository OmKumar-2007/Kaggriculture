#!/usr/bin/env bash
set -euo pipefail
package="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
printf stop > "$package/.stop"
echo 'Graceful stop requested. Active containers are being cancelled.'
