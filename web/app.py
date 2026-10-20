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

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse
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


@app.get("/")
async def serve_home() -> HTMLResponse:
    """Serve the main HTML page."""
    with open("static/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.api_route("/mcp", methods=["GET", "POST", "DELETE", "OPTIONS"])
@app.api_route("/mcp/{path:path}", methods=["GET", "POST", "DELETE", "OPTIONS"])
async def proxy_mcp(request: Request, path: str = "") -> Response:
    """Streaming reverse-proxy for /mcp (SSE responses relay live)."""
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
