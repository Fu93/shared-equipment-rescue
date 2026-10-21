#!/usr/bin/env bash
# One-port hosted demo (Render web service): MCP server on loopback, web proxy on $PORT.
#   Build:  pip install -r requirements.txt
#   Start:  bash deploy/render_start.sh
# The MCP server binds 127.0.0.1 only; the browser reaches it through the proxy's
# same-origin /mcp. A fresh SQLite file is seeded on every boot (no persistent disk),
# and "Reset demo data" reseeds it while running. Bedrock stays off unless the
# platform sets AWS credentials, which this demo never does.
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${PORT:-8080}"
MCP_PORT="${SER_MCP_PORT:-8765}"
export SER_DB_PATH="${SER_DB_PATH:-/tmp/ser_demo.db}"
export SER_LLM_MODE="${SER_LLM_MODE:-scripted}"
# Neither uvicorn may rewrite the client address from X-Forwarded-For: on Render
# that header keeps whatever the visitor sent. The proxy keys its budget on
# SER_CLIENT_IP_HEADER (cf-connecting-ip) and hands the MCP server its own header.
export FORWARDED_ALLOW_IPS=""
rm -f "$SER_DB_PATH" "$SER_DB_PATH-wal" "$SER_DB_PATH-shm"

python -m mcp_server --host 127.0.0.1 --port "$MCP_PORT" --db "$SER_DB_PATH" &
MCP_PID=$!
trap 'kill "$MCP_PID" "${WEB_PID:-}" 2>/dev/null || true' EXIT INT TERM

for _ in $(seq 1 100); do
  if python - "$MCP_PORT" <<'PY' 2>/dev/null; then break; fi
import socket, sys
socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=0.5).close()
PY
  kill -0 "$MCP_PID" 2>/dev/null || { echo "MCP server exited during startup" >&2; exit 1; }
  sleep 0.2
done

cd web
python app.py --host 0.0.0.0 --port "$PORT" --mcp-host 127.0.0.1 --mcp-port "$MCP_PORT" &
WEB_PID=$!
# If either process dies, exit non-zero so the platform restarts the service.
wait -n "$MCP_PID" "$WEB_PID"
echo "a demo process exited; stopping" >&2
exit 1
