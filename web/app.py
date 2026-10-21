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
import sys
import urllib.parse
from typing import Optional

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.staticfiles import StaticFiles

app = FastAPI(title="Shared Equipment Rescue Web UI")

# Shared streaming client. SSE streams must stay open indefinitely, but the
# SAME client also serves the plain JSON path and /metrics - and with no
# timeout at all, a half-dead upstream (accepts the TCP connection, then
# stalls) left the proxy request hanging FOREVER. The browser just sat there.
# So: no timeout for the SSE relay, a bounded one for everything else.
_client: httpx.AsyncClient | None = None

# Bounded timeout for the non-streaming upstream calls (JSON-RPC responses
# and /metrics). Long enough for a busy LLM narration, short enough that a
# stalled upstream surfaces as an error instead of a hanging page.
UPSTREAM_TIMEOUT = float(os.environ.get("SER_UPSTREAM_TIMEOUT", "30"))


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(None))
    return _client


def bounded_client() -> httpx.AsyncClient:
    """A client with a real timeout, for calls that are NOT SSE streams."""
    global _bounded
    if _bounded is None:
        _bounded = httpx.AsyncClient(timeout=httpx.Timeout(UPSTREAM_TIMEOUT))
    return _bounded


_bounded: httpx.AsyncClient | None = None

client = get_client()  # module-level default for the proxy coroutine

HOP_BY_HOP_REQ = {
    "host", "content-length", "connection", "keep-alive",
    "proxy-authenticate", "proxy-authorization", "te", "trailer",
    "transfer-encoding", "upgrade", "origin", "referer",
    # Client-supplied forwarding headers never reach the MCP server: its
    # uvicorn trusts loopback proxies, so a forged X-Forwarded-For would
    # otherwise pick the server-side rate-limit bucket.
    "x-forwarded-for", "x-real-ip", "forwarded",
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
# Host policy mirrors the MCP server's guard: any *loopback* host:port is a
# legitimate target, because the shell is started with a configurable
# --port and the demo may run on 8080, 8099, ... A hard-coded "127.0.0.1:8080"
# would make every other documented port answer 403 on every route. The
# security property that matters is loopback-ness (a rebound DNS name is
# exactly the attack the guard exists for), not a fixed port number.
ALLOWED_HOST_NAMES = {"127.0.0.1", "localhost", "::1", "[::1]"}


def _load_allowed_hosts() -> set:
    """SER_ALLOWED_HOSTS: comma-separated exact public hostnames (no port, no wildcard).

    A Host header matches when its name is listed; any port is accepted only
    if it is numeric and in 1-65535 ("name:abc" and "name:" are refused).

    Unset means loopback only, as before. A hosted demo (for example
    shared-equipment-rescue.onrender.com) lists its own public name here so
    the guard still rejects every other Host a rebound DNS name could send.
    """
    out = set()
    for part in os.environ.get("SER_ALLOWED_HOSTS", "").split(","):
        part = part.strip().lower().rstrip(".")
        if part and "*" not in part and "/" not in part and ":" not in part:
            out.add(part)
    return out


EXTRA_ALLOWED_HOSTS = _load_allowed_hosts()


def _valid_port(port: str) -> bool:
    return port.isascii() and port.isdigit() and 0 < int(port) <= 65535


def _loopback_host_allowed(host: str) -> bool:
    """True for loopback host[:port] values; empty Host is tolerated."""
    if not host:
        return True
    if host.startswith("["):                      # IPv6 bracket form [::1]:8080
        inside, _, _rest = host.partition("]")
        return inside.lstrip("[") in {"::1", "127.0.0.1"} or inside == "localhost"
    name, sep, _port = host.rpartition(":")
    if not sep:
        name = host
    if EXTRA_ALLOWED_HOSTS and name.lower().rstrip(".") in EXTRA_ALLOWED_HOSTS:
        # The name matched; a port, when present, must be a real one
        # (1-65535, digits only). "name:abc" or "name:" is refused.
        return not sep or _valid_port(_port)
    if name in ALLOWED_HOST_NAMES:
        return True
    try:
        import ipaddress

        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


def _origin_allowed(origin: str) -> bool:
    """Exact-match allowlist, plus any loopback http(s) origin.

    The browser's Origin for a same-origin fetch is the page's own origin,
    which carries whatever --port the shell was started with. Loopback
    origins are therefore accepted in addition to the explicit allowlist.
    """
    if origin in ALLOWED_ORIGINS:
        return True
    try:
        parsed = urllib.parse.urlparse(origin)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.hostname or ""
    if host in ALLOWED_HOST_NAMES:
        return True
    try:
        import ipaddress

        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False

# Per-IP token bucket, same budget as the MCP server guard: ~4 req/s, burst 16.
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


_rate_limiter = _TokenBucket(rate_per_sec=4.0, burst=16)

# Header the proxy uses to tell the MCP server which client a request is for.
# The proxy always overwrites it, so a browser cannot choose its own bucket.
CLIENT_IP_FORWARD_HEADER = "x-ser-client-ip"


def client_ip(request: Request) -> str:
    """Rate-limit key: the socket peer, or one edge-set header when configured.

    SER_CLIENT_IP_HEADER names a header that the hosting edge sets and
    overwrites itself (cf-connecting-ip on Render, which sits behind
    Cloudflare). X-Forwarded-For is never used: Render appends to whatever the
    client sent, so its leftmost entry is attacker-chosen. Unset means the raw
    socket peer, exactly as before.
    """
    name = os.environ.get("SER_CLIENT_IP_HEADER", "").strip().lower()
    if name and name != "x-forwarded-for":
        value = (request.headers.get(name) or "").strip()
        if value and "," not in value and len(value) <= 64:
            return value
    return request.client.host if request.client else "unknown"


def upstream_headers(request: Request) -> dict:
    """Request headers to forward upstream, with our own client-IP header set."""
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in HOP_BY_HOP_REQ and k.lower() != CLIENT_IP_FORWARD_HEADER
    }
    headers[CLIENT_IP_FORWARD_HEADER] = client_ip(request)
    return headers


def validate_transport_headers(request: Request) -> Optional[str]:
    """Return a 403 message if Origin/Host fail, else None (allowed)."""
    origin = request.headers.get("origin")
    if origin is not None and not _origin_allowed(origin):
        return f"unrecognized Origin {origin!r}"
    host = request.headers.get("host", "")
    if not _loopback_host_allowed(host):
        return f"unrecognized Host {host!r}"
    return None


def upstream_target(request: Request) -> tuple[str, int]:
    """(host, port) of the MCP server, with the same defaults the proxy uses."""
    if not getattr(request.app.state, "mcp_port", None):
        request.app.state.mcp_host = "127.0.0.1"
        request.app.state.mcp_port = 8765
    return request.app.state.mcp_host, request.app.state.mcp_port


@app.get("/")
async def serve_home(request: Request) -> HTMLResponse:
    """Serve the main HTML page (same Origin/Host policy as /mcp)."""
    denial = validate_transport_headers(request)
    if denial is not None:
        return JSONResponse({"error": denial}, status_code=403)
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "index.html"),
              "r", encoding="utf-8") as f:
        html = f.read()
    # app.py lives in web/, so the package root is not on sys.path until added.
    # Same values the MCP process bound at import. Start both processes with
    # the same SER_DEMO_DATE and SER_DEMO_TZ, or leave both unset.
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)
    from mcp_server.constants import DEMO_DATE, DEMO_TZ, DEMO_TZ_OFFSET
    html = (html
            .replace("__SER_DEMO_DATE__", DEMO_DATE)
            .replace("__SER_DEMO_TZ__", DEMO_TZ)
            .replace("__SER_DEMO_OFFSET__", DEMO_TZ_OFFSET))
    return HTMLResponse(content=html)


@app.get("/metrics")
async def serve_metrics(request: Request) -> Response:
    """Aggregated observability: proxy self + upstream MCP /metrics.

    Same Origin/Host policy as /mcp — a DNS-rebinding page must not read
    chain heads / row counts from this endpoint either. Same-origin HTML/JS
    (and a local curl) can scrape one endpoint for the whole stack: process
    uptime + flood budget here, database shape and chain/audit state from
    the server. Aggregation is best-effort — if the MCP server is down, its
    section reports the failure instead of 500ing.
    """
    denial = validate_transport_headers(request)
    if denial is not None:
        return JSONResponse({"error": denial}, status_code=403)
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
    # Bounded client: /metrics is a plain JSON call, not an SSE stream, so
    # it must not inherit the "wait forever" timeout of the relay client.
    client = bounded_client()
    host, port = upstream_target(request)
    try:
        r = await client.get(f"http://{host}:{port}/metrics",
                             headers={CLIENT_IP_FORWARD_HEADER: client_ip(request)})
        stats["server"] = r.json() if r.status_code == 200 else \
            {"error": f"upstream status {r.status_code}"}
    except Exception as exc:
        stats["server"] = {"error": str(exc)[:120]}
    return JSONResponse(stats)


@app.post("/agent/step")
@app.post("/agent/result")
async def proxy_agent(request: Request) -> Response:
    """Forward one agent step to the MCP server. The browser still executes tools."""
    denial = validate_transport_headers(request)
    if denial is not None:
        return JSONResponse({"error": denial}, status_code=403)
    client = bounded_client()
    host, port = upstream_target(request)
    headers = upstream_headers(request)
    url = f"http://{host}:{port}{request.url.path}"
    try:
        upstream = await client.post(url, content=await request.body(), headers=headers)
    except httpx.TimeoutException:
        return JSONResponse({"error": "MCP server did not respond in time", "bedrock": False},
                            status_code=504)
    except httpx.TransportError:
        return JSONResponse({"error": "MCP server unreachable", "bedrock": False},
                            status_code=502)
    media = upstream.headers.get("content-type", "application/json")
    return Response(content=upstream.content, status_code=upstream.status_code, media_type=media)


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
    if not _rate_limiter.allow(client_ip(request)):
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

    headers = upstream_headers(request)

    body = await request.body()
    # The SSE relay (GET /mcp) must stay open indefinitely, but a JSON
    # response must not hang forever if the upstream stalls. So the timeout
    # is per-request: unbounded for the event stream, bounded otherwise.
    is_stream_get = request.method == "GET"
    relay = client if is_stream_get else bounded_client()
    req = relay.build_request(
        method=request.method,
        url=url,
        headers=headers,
        content=body,
    )
    try:
        upstream = await relay.send(req, stream=True)
    except httpx.TimeoutException:
        return Response(
            content='{"jsonrpc":"2.0","id":null,"error":{"code":-32001,'
            '"message":"MCP server did not respond in time - check that '
            '\\"python -m mcp_server\\" is running on :8765"}}',
            status_code=504,
            media_type="application/json",
        )
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
