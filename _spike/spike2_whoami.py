# Spike 2: whoami only — is the per-call starlette request visible? Hard timeout.
import anyio
import json
import socket

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.fastmcp import FastMCP, Context


def build():
    mcp = FastMCP("spike2", stateless_http=False, json_response=True)

    @mcp.tool()
    def whoami(ctx: Context) -> dict:
        """Return identity info read from the per-call starlette request."""
        req = ctx.request_context.request
        info: dict = {"request_type": type(req).__name__}
        if req is not None:
            info["auth"] = req.headers.get("authorization")
            info["sid"] = req.headers.get("mcp-session-id")
        return info

    return mcp


async def probe(tag: str, hdr: dict, timeout_s: float = 15) -> list[dict]:
    out: list[dict] = []

    async def body():
        async with streamablehttp_client(
            "http://127.0.0.1:8898/mcp", headers=hdr
        ) as (r, w, _):
            async with ClientSession(r, w) as s:
                init = await s.initialize()
                out.append({"tag": tag, "protocol": init.protocolVersion})
                res = await s.call_tool("whoami", {})
                out.append({"tag": tag, "whoami": res.structuredContent})

    with anyio.move_on_after(timeout_s, shield=True):
        await body()
        out.append({"tag": tag, "done": True})
    return out


async def main():
    mcp = build()
    _app = mcp.streamable_http_app()
    import uvicorn

    config = uvicorn.Config(_app, host="127.0.0.1", port=8898, log_level="error")
    server = uvicorn.Server(config)
    async with anyio.create_task_group() as tg:
        tg.start_soon(server.serve)
        for _ in range(80):
            try:
                with socket.create_connection(("127.0.0.1", 8898), timeout=0.2):
                    break
            except OSError:
                await anyio.sleep(0.05)
        results: list[dict] = []
        results += await probe("a", {"Authorization": "Bearer tok-manager"})
        results.append("---")
        results += await probe("b", {"Authorization": "Bearer tok-li"})
        results.append("---")
        results += await probe("c", {})
        tg.cancel_scope.cancel()
    print(json.dumps(results, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    anyio.run(main)
