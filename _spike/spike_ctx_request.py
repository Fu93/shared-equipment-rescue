# Spike: authentic proof that ctx.request_context.request is the per-call
# Starlette Request on stateful Streamable HTTP, incl. elicitation.
import anyio
import json
import socket

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.fastmcp import FastMCP, Context


def build():
    mcp = FastMCP("spike", stateless_http=False, json_response=True)

    @mcp.tool()
    def whoami(ctx: Context) -> dict:
        """Return identity info read from the per-call starlette request."""
        req = ctx.request_context.request
        info: dict = {"request_type": type(req).__name__}
        if req is not None:
            info["auth"] = req.headers.get("authorization")
            info["mcp_session_id"] = req.headers.get("mcp-session-id")
        return info

    @mcp.tool()
    async def ask_confirm(ctx: Context) -> dict:
        """Elicits a boolean and echoes it."""
        from pydantic import BaseModel

        class Confirm(BaseModel):
            confirm: bool

        res = await ctx.elicit("Apply replan", Confirm)
        return {
            "kind": res.__class__.__name__,
            "action": getattr(res, "action", None),
            "data": getattr(res, "data", None),
        }

    return mcp


async def probe(tag: str, hdr: dict, elicit_cb) -> list[dict]:
    out: list[dict] = []
    async with streamablehttp_client(
        "http://127.0.0.1:8899/mcp", headers=hdr
    ) as (r, w, _):
        async with ClientSession(r, w, elicitation_callback=elicit_cb) as s:
            init = await s.initialize()
            out.append({"tag": tag, "protocol": init.protocolVersion})
            res = await s.call_tool("whoami", {})
            out.append({"tag": tag, "whoami": res.structuredContent})
            res2 = await s.call_tool("ask_confirm", {})
            out.append({"tag": tag, "elicit": res2.structuredContent})
    return out


def cb_accept(m: str, schema):
    print(f"[callback] got elicitation: {m}")
    from mcp.types import ElicitResult

    return ElicitResult(action="accept", content={"confirm": True})


def cb_decline(m: str, schema):
    from mcp.types import ElicitResult

    return ElicitResult(action="decline")


async def main():
    mcp = build()
    _app = mcp.streamable_http_app()  # lifespan runs the session manager
    import uvicorn

    config = uvicorn.Config(_app, host="127.0.0.1", port=8899, log_level="error")
    server = uvicorn.Server(config)
    async with anyio.create_task_group() as tg:
        tg.start_soon(server.serve)
        for _ in range(80):
            try:
                with socket.create_connection(("127.0.0.1", 8899), timeout=0.2):
                    break
            except OSError:
                await anyio.sleep(0.05)
        results: list[dict] = []
        results += await probe(
            "manager", {"Authorization": "Bearer tok-manager"}, cb_accept
        )
        results.append("---")
        results += await probe("declining", {"Authorization": "Bearer tok-manager"}, cb_decline)
        results.append("---")
        results += await probe("no-headers", {}, None)
        tg.cancel_scope.cancel()
    print(json.dumps(results, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    anyio.run(main)
