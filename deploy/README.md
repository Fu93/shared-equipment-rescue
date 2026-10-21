# Hosted demo (Render)

One Render **web service**, Python runtime, one public port.

| Setting | Value |
|---|---|
| Build command | `pip install -r requirements.txt` |
| Start command | `bash deploy/render_start.sh` |

`deploy/render_start.sh` starts the MCP server on `127.0.0.1:8765` with a fresh SQLite file (seeded on boot), waits for it, then starts the web proxy on `0.0.0.0:$PORT`. If either process exits, the script exits non-zero and Render restarts the service. There is no persistent disk: every deploy or restart is a fresh seed, and **Reset demo data** reseeds while it runs.

Environment (all opt-in; local defaults are unchanged):

| Variable | Value | Why |
|---|---|---|
| `SER_ALLOWED_HOSTS` | `<service>.onrender.com` | Host guard accepts this exact public name as well as loopback. |
| `SER_ALLOWED_ORIGINS` | `https://<service>.onrender.com` | Origin guard accepts the page's own origin. |
| `SER_CLIENT_IP_HEADER` | `cf-connecting-ip` | Per-IP budget keys on the header Cloudflare sets and overwrites. X-Forwarded-For is never used: Render appends to whatever the visitor sent. |
| `SER_TRUST_PROXY_CLIENT_IP` | `1` | MCP server keys its own buckets on the proxy's `x-ser-client-ip` (loopback peers only). Without it every visitor shares one server-side bucket. |
| `SER_LLM_MODE` | `scripted` | Bedrock stays off; the page shows `Fallback: pattern parser (Bedrock off)`. |
| `SER_DEMO_TZ` | `Europe/London` | Leave `SER_DEMO_DATE` unset so the seeded day is always today. |

Do not set `AWS_*`, `SER_BEDROCK_STUB`, or `SER_NO_RATE_LIMIT` on a public deploy.
