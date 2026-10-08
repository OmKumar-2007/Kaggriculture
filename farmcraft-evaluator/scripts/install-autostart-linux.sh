#!/usr/bin/env bash
set -euo pipefail
package="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/farmcraft-evaluator.service" <<EOF
[Unit]
Description=FarmCraft portable evaluator
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$package
ExecStart=$package/scripts/start-worker.sh
Restart=on-failure
RestartSec=15

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now farmcraft-evaluator.service
echo 'FarmCraft evaluator enabled for this user. Ensure Docker starts before it.'
