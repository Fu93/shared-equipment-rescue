#!/usr/bin/env bash
# One-port hosted demo (Render web service): MCP server on loopback, web proxy on $PORT.
#   Build:  pip install -r requirements.txt
#   Start:  bash deploy/render_start.sh
# The MCP server binds 127.0.0.1 only; the browser reaches it through the proxy's
# same-origin /mcp. A fresh SQLite file is seeded on every boot (no persistent disk),
# and "Reset demo data" reseeds it while running. Bedrock stays off unless the
# platform sets AWS credentials, which this demo never does.
#
# Exit codes: 1 = the MCP server never started listening within
# SER_MCP_START_TIMEOUT seconds (default 30) or exited during startup;
# otherwise the exit status of whichever process stopped first (1 if it was 0).
set -uo pipefail
cd "$(dirname "$0")/.."
PORT="${PORT:-8080}"
MCP_PORT="${SER_MCP_PORT:-8765}"
START_TIMEOUT="${SER_MCP_START_TIMEOUT:-30}"
export SER_DB_PATH="${SER_DB_PATH:-/tmp/ser_demo.db}"
export SER_LLM_MODE="${SER_LLM_MODE:-scripted}"
# Neither uvicorn may rewrite the client address from X-Forwarded-For: on Render
# that header keeps whatever the visitor sent. The proxy keys its budget on
# SER_CLIENT_IP_HEADER (cf-connecting-ip) and hands the MCP server its own header.
export FORWARDED_ALLOW_IPS=""
rm -f "$SER_DB_PATH" "$SER_DB_PATH-wal" "$SER_DB_PATH-shm"

log() { echo "render_start: $*" >&2; }
MCP_PID=""; WEB_PID=""
stop_all() { kill $MCP_PID $WEB_PID 2>/dev/null || true; }
trap stop_all EXIT
trap 'log "signal received, stopping"; exit 143' INT TERM

python -m mcp_server --host 127.0.0.1 --port "$MCP_PORT" --db "$SER_DB_PATH" &
MCP_PID=$!
log "MCP server started (pid $MCP_PID), waiting up to ${START_TIMEOUT}s for 127.0.0.1:$MCP_PORT"

listening() {
  python - "$MCP_PORT" <<'PY' 2>/dev/null
import socket, sys
socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=0.5).close()
PY
}
deadline=$((SECONDS + START_TIMEOUT))
until listening; do
  if ! kill -0 "$MCP_PID" 2>/dev/null; then
    wait "$MCP_PID"; st=$?
    log "MCP server (pid $MCP_PID) exited during startup with status $st"
    exit 1
  fi
  if [ "$SECONDS" -ge "$deadline" ]; then
    log "MCP server (pid $MCP_PID) still not listening on 127.0.0.1:$MCP_PORT after ${START_TIMEOUT}s; giving up"
    exit 1
  fi
  sleep 0.2
done
log "MCP server listening on 127.0.0.1:$MCP_PORT"

(cd web && exec python app.py --host 0.0.0.0 --port "$PORT" --mcp-host 127.0.0.1 --mcp-port "$MCP_PORT") &
WEB_PID=$!
log "web proxy started (pid $WEB_PID) on 0.0.0.0:$PORT"

# If either process stops, say which one and how, then exit non-zero so the
# platform restarts the service.
DONE_PID=""
if (( BASH_VERSINFO[0] > 5 || (BASH_VERSINFO[0] == 5 && BASH_VERSINFO[1] >= 1) )); then
  wait -n -p DONE_PID "$MCP_PID" "$WEB_PID"; st=$?
else
  wait -n "$MCP_PID" "$WEB_PID"; st=$?
  kill -0 "$MCP_PID" 2>/dev/null || DONE_PID="$MCP_PID"
fi
if [ "$DONE_PID" = "$MCP_PID" ]; then who="MCP server (pid $MCP_PID)"; else who="web proxy (pid $WEB_PID)"; fi
log "$who exited with status $st; stopping the other process"
[ "$st" -eq 0 ] && st=1
exit "$st"
