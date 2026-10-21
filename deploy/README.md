# Hosted demo (Render)

One Render **web service**, Python runtime, one public port.

| Setting | Value |
|---|---|
| Build command | `pip install -r requirements.txt` |
| Start command | `bash deploy/render_start.sh` |

`deploy/render_start.sh` starts the MCP server on `127.0.0.1:8765` with a fresh SQLite file (seeded on boot) and waits up to `SER_MCP_START_TIMEOUT` seconds (default 30) for it to listen. If it never listens, or exits during startup, the script logs that and exits 1 without starting the proxy. Otherwise it starts the web proxy on `0.0.0.0:$PORT`. When either process stops, the script logs which one (`MCP server (pid N)` or `web proxy (pid N)`) and its exit status, stops the other, and exits non-zero so Render restarts the service. There is no persistent disk: every deploy or restart is a fresh seed, and **Reset demo data** reseeds while it runs.

Environment (all opt-in; local defaults are unchanged):

| Variable | Value | Why |
|---|---|---|
| `SER_ALLOWED_HOSTS` | `<service>.onrender.com` | Host guard accepts this exact public name as well as loopback. Entries are bare names (no port, no wildcard). A Host header with a port matches only if the port is digits in 1–65535, so `name:abc`, `name:` and `name:0` are refused. |
| `SER_ALLOWED_ORIGINS` | `https://<service>.onrender.com` | Origin guard accepts the page's own origin. |
| `SER_CLIENT_IP_HEADER` | `cf-connecting-ip` | Per-IP budget keys on the header Cloudflare sets and overwrites. X-Forwarded-For is never used: Render appends to whatever the visitor sent. |
| `SER_TRUST_PROXY_CLIENT_IP` | `1` | MCP server keys its own buckets on the proxy's `x-ser-client-ip` (loopback peers only). Without it every visitor shares one server-side bucket. |
| `SER_CLASSIFY_PLATFORM_PROBES` | `1` | Render probes every listening port at boot with a bare `HEAD /`, which reaches the loopback MCP server with a non-loopback Host. It is still refused (403) and still written to the hash-chained transport ledger, but as event `host_probe` instead of `host`. `/metrics` counts it under `transport_ledger.events.host_probe` and the header badge mentions it in its tooltip, without the amber warning. Only a loopback `HEAD /` with no query, Origin, token, cookie or body qualifies; every other refused Host stays `host` and stays amber. |
| `SER_LLM_MODE` | `scripted` | Bedrock stays off; the page shows `Fallback: pattern parser (Bedrock off)`. |
| `SER_DEMO_TZ` | `Europe/London` | Leave `SER_DEMO_DATE` unset so the seeded day is always today. |

Do not set `AWS_*`, `SER_BEDROCK_STUB`, or `SER_NO_RATE_LIMIT` on a public deploy.
