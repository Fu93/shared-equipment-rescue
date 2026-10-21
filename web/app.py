"""Shared Equipment Rescue demo web shell.

Serves the static client and proxies /mcp to the MCP server so the browser can
talk MCP Streamable HTTP without CORS issues. The proxy is streaming-aware:
SSE responses (GET /mcp) are relayed chunk-by-chunk so server-initiated
requests (elicitation/create) reach the browser in real time.

Run from this directory:
    python app.py                # web on :8080, expects MCP server on :8765
    python app.py --mcp-host 127.0.0.1 --mcp-port 8765
"""

from __future__ import annotations

import argparse
import os
from typing import Optional

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.staticfiles import StaticFiles

app = FastAPI(title="Shared Equipment Rescue Web UI")

# Shared streaming client (no request timeout: SSE streams stay open).
_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(None))
    return _client


client = get_client()  # module-level default for the proxy coroutine

HOP_BY_HOP_REQ = {
    "host", "content-length", "connection", "keep-alive",
    "proxy-authenticate", "proxy-authorization", "te", "trailer",
    "transfer-encoding", "upgrade", "origin", "referer",
}
HOP_BY_HOP_RESP = {
    "content-length", "content-encoding", "transfer-encoding", "connection",
    "keep-alive", "access-control-allow-origin",
}

# ---------------------------------------------------------------------------
# Origin / Host header validation (OWASP MCP Security Cheat Sheet #6)
#
# Streamable HTTP has no protocol-level sessions, so transport-level checks
# are the first line of defence against DNS-rebinding browsers and cross-site
# calls that riding on a user's token. Rules follow the spec + OWASP guidance:
#   - a present-but-unrecognized Origin -> 403
#   - an absent Origin is allowed (python MCP clients / curl send none)
#   - Host must be a locally-bound name; reject everything else
# ---------------------------------------------------------------------------
_BASE_ORIGINS = {
    "http://127.0.0.1:8080",
    "http://localhost:8080",
}


def _load_allowed_origins() -> set:
    """Demo defaults + SER_ALLOWED_ORIGINS (comma-separated, exact origins).

    Mirrors the MCP-server guard so both layers accept the same set. Only
    absolute scheme://host[:port] values are honoured; junk is dropped.
    """
    extra = os.environ.get("SER_ALLOWED_ORIGINS", "").strip()
    if not extra:
        return set(_BASE_ORIGINS)
    allowed = set(_BASE_ORIGINS)
    for part in extra.split(","):
        part = part.strip().rstrip("/")
        if part and "://" in part:
            allowed.add(part)
    return allowed


ALLOWED_ORIGINS = _load_allowed_origins()
ALLOWED_HOSTS = {
    "127.0.0.1:8080", "localhost:8080", "127.0.0.1", "localhost",
}

# Per-IP token bucket, same budget as the MCP server guard: ~4 req/s, burst 8.
# A normal browser session (poll + calls) stays under 1 req/s sustained.
import time as _time


class _TokenBucket:
    def __init__(self, rate_per_sec: float, burst: int):
        self.rate = rate_per_sec
        self.burst = float(burst)
        self.tokens: dict[str, float] = {}
        self.updated: dict[str, float] = {}

    def allow(self, key: str) -> bool:
        now = _time.monotonic()
        prev = self.updated.get(key)
        if prev is None:
            self.tokens[key] = self.burst
            self.updated[key] = now
            return True
        self.tokens[key] = min(self.burst, self.tokens[key] + (now - prev) * self.rate)
        self.updated[key] = now
        if self.tokens[key] >= 1.0:
            self.tokens[key] -= 1.0
            return True
        return False

    def trim(self, max_clients: int = 4096) -> None:
        if len(self.updated) <= max_clients:
            return
        oldest = sorted(self.updated, key=self.updated.get)[: len(self.updated) - max_clients]
        for k in oldest:
            self.tokens.pop(k, None)
            self.updated.pop(k, None)


_rate_limiter = _TokenBucket(rate_per_sec=4.0, burst=8)


def validate_transport_headers(request: Request) -> Optional[str]:
    """Return a 403 message if Origin/Host fail, else None (allowed)."""
    origin = request.headers.get("origin")
    if origin is not None and origin not in ALLOWED_ORIGINS:
        return f"unrecognized Origin {origin!r}"
    host = request.headers.get("host", "")
    if host and host not in ALLOWED_HOSTS:
        return f"unrecognized Host {host!r}"
    return None


@app.get("/")
async def serve_home() -> HTMLResponse:
    """Serve the main HTML page."""
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "index.html"),
              "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/metrics")
async def serve_metrics() -> Response:
    """Aggregated observability: proxy self + upstream MCP /metrics.

    Same-origin HTML/JS (and a local curl) can scrape one endpoint for the
    whole stack: process uptime + flood budget here, database shape and
    chain/audit state from the server. Aggregation is best-effort — if the
    MCP server is down, its section reports the failure instead of 500ing.
    """
    import time as _t
    if not _started_mono:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    stats: dict = {
        "proxy": {
            "uptime_seconds": round(_t.monotonic() - _started_mono, 1),
            "rate_limit": {"rate_per_sec": _rate_limiter.rate,
                           "burst": _rate_limiter.burst,
                           "tracked_clients": len(_rate_limiter.updated)},
        },
        "server": None,
    }
    client = get_client()
    try:
        r = await client.get("http://127.0.0.1:8765/metrics")
        stats["server"] = r.json() if r.status_code == 200 else \
            {"error": f"upstream status {r.status_code}"}
    except Exception as exc:
        stats["server"] = {"error": str(exc)[:120]}
    return JSONResponse(stats)


_started_mono = _time.monotonic()


app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")),
          name="static")


@app.api_route("/mcp", methods=["GET", "POST", "DELETE", "OPTIONS"])
@app.api_route("/mcp/{path:path}", methods=["GET", "POST", "DELETE", "OPTIONS"])
async def proxy_mcp(request: Request, path: str = "") -> Response:
    """Streaming reverse-proxy for /mcp (SSE responses relay live)."""
    # Transport header hardening first: never forward disallowed origins/hosts.
    denial = validate_transport_headers(request)
    if denial is not None:
        return JSONResponse(
            content={
                "jsonrpc": "2.0", "id": None,
                "error": {"code": -32002, "message": f"rejected: {denial}"},
            },
            status_code=403,
        )
    # Per-IP flood budget (local single-user demo: a hammering client is abuse).
    client_ip = request.client.host if request.client else "unknown"
    if not _rate_limiter.allow(client_ip):
        return JSONResponse(
            content={
                "jsonrpc": "2.0", "id": None,
                "error": {"code": -32002, "message": "rejected: rate limit exceeded"},
            },
            status_code=429,
        )
    _rate_limiter.trim()
    # Defaults for uvicorn starts that bypass __main__ (e.g. `uvicorn app:app`).
    if not getattr(request.app.state, "mcp_port", None):
        request.app.state.mcp_host = "127.0.0.1"
        request.app.state.mcp_port = 8765
    target_host = request.app.state.mcp_host
    target_port = request.app.state.mcp_port
    url = f"http://{target_host}:{target_port}/mcp"
    if path:
        url += f"/{path}"

    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in HOP_BY_HOP_REQ
    }

    body = await request.body()
    req = client.build_request(
        method=request.method,
        url=url,
        headers=headers,
        content=body,
    )
    try:
        upstream = await client.send(req, stream=True)
    except httpx.TransportError:  # ConnectError, ReadError, WriteError, etc.
        return Response(
            content='{"jsonrpc":"2.0","id":null,"error":{"code":-32001,'
            '"message":"MCP server unreachable - start it with \\"python -m mcp_server\\" on :8765"}}',
            status_code=502,
            media_type="application/json",
        )

    resp_headers = {
        k: v
        for k, v in upstream.headers.items()
        if k.lower() not in HOP_BY_HOP_RESP
    }

    media = upstream.headers.get("content-type", "application/json")
    if "text/event-stream" in media:
        # Relay the SSE stream chunk by chunk; close upstream when done.
        async def stream_generator():
            try:
                async for chunk in upstream.aiter_raw():
                    yield chunk
            finally:
                await upstream.aclose()

        from fastapi.responses import StreamingResponse

        return StreamingResponse(
            stream_generator(),
            status_code=upstream.status_code,
            headers=resp_headers,
            media_type=media,
        )

    content = await upstream.aread()
    await upstream.aclose()
    return Response(
        content=content,
        status_code=upstream.status_code,
        headers=resp_headers,
        media_type=media,
    )


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description="Shared Equipment Rescue web shell")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--mcp-host", default="127.0.0.1")
    parser.add_argument("--mcp-port", type=int, default=8765)
    args = parser.parse_args()

    app.state.mcp_host = args.mcp_host
    app.state.mcp_port = args.mcp_port
    uvicorn.run(app, host=args.host, port=args.port)
