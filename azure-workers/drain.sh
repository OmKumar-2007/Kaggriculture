#!/usr/bin/env bash
set -euo pipefail
touch /opt/farmcraft/farmcraft-evaluator/.drain
chown farmcraft:farmcraft /opt/farmcraft/farmcraft-evaluator/.drain
echo 'Drain requested; no new claims. Active attempts may finish before the service exits.'
