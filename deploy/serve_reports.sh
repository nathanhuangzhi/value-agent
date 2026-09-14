#!/usr/bin/env bash
# Static file server for the published archive (HTML reports + api/ JSON).
#
# Listens on 127.0.0.1 only; `tailscale serve` fronts it with HTTPS on the
# tailnet:   tailscale serve --bg --set-path /reports http://127.0.0.1:8091
# (that serve rule persists in tailscaled state across reboots — set it once).
#
# Install (as the pipeline user):
#   crontab -e →  @reboot  /home/nathan/value-agent/deploy/serve_reports.sh
# Idempotent: exits quietly if a server is already bound to the port.

set -euo pipefail

PUBLISH_DIR="${PUBLISH_DIR:-$HOME/public/value-agent}"
PORT="${PORT:-8091}"

mkdir -p "$PUBLISH_DIR"
if ss -tln 2>/dev/null | grep -q "127.0.0.1:$PORT "; then
  exit 0
fi
cd "$PUBLISH_DIR"
exec python3 -m http.server "$PORT" --bind 127.0.0.1 >/dev/null 2>&1
