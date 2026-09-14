#!/usr/bin/env bash
# The FastAPI service behind the app's AI tab (app/ai/*) — and the same
# /api routes the static archive bakes, for dev parity.
#
# Listens on 127.0.0.1:8000; `tailscale serve` fronts it on the tailnet:
#   tailscale serve --bg --set-path /ai http://127.0.0.1:8000/ai
# (set once; persists in tailscaled state).
#
# Install (as the pipeline user):
#   crontab -e →  @reboot  /home/nathan/value-agent/deploy/serve_ai.sh start
# run_daily.sh calls `restart` after its git pull so code changes land daily.
#
#   deploy/serve_ai.sh start|stop|restart|status

set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PORT="${PORT:-8000}"
PIDFILE="$REPO_DIR/logs/ai.pid"
LOG="$REPO_DIR/logs/ai.log"

mkdir -p "$REPO_DIR/logs"

is_running() {
  [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null
}

start() {
  if is_running; then echo "ai service already running (pid $(cat "$PIDFILE"))"; return 0; fi
  cd "$REPO_DIR"
  nohup venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$PORT" \
    --log-level warning >> "$LOG" 2>&1 < /dev/null &
  echo $! > "$PIDFILE"
  sleep 2
  if is_running; then echo "ai service started (pid $(cat "$PIDFILE"), :$PORT)"; else echo "ai service FAILED to start — see $LOG"; return 1; fi
}

stop() {
  if is_running; then
    kill "$(cat "$PIDFILE")" && echo "ai service stopped"
    for _ in 1 2 3 4 5; do is_running || break; sleep 1; done
  fi
  rm -f "$PIDFILE"
}

case "${1:-status}" in
  start)   start ;;
  stop)    stop ;;
  restart) stop; start ;;
  status)  if is_running; then echo "running (pid $(cat "$PIDFILE"))"; else echo "not running"; exit 1; fi ;;
  *) echo "usage: $0 start|stop|restart|status"; exit 2 ;;
esac
