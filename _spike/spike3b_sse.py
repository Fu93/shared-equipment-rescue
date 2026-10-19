# Spike 3: elicitation path alone.
import anyio
import json
import socket

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.fastmcp import FastMCP, Context
from pydantic import BaseModel


class Confirm(BaseModel):
    confirm: bool


def build():
    mcp = FastMCP("spike3", stateless_http=False, json_response=False)

    @mcp.tool()
    async def ask_confirm(ctx: Context) -> Confirm:
        """Elicits a boolean and echoes it."""
        res = await ctx.elicit("Apply replan", Confirm)
        kind = res.__class__.__name__
        action = getattr(res, "action", None)
        data = getattr(res, "data", None)
        return Confirm(confirm=True)  # placeholder; we print kind/action below
        # note: returning details via print instead

    return mcp


async def probe(tag: str, hdr: dict, elicit_cb, timeout_s: float = 20) -> list[dict]:
    out: list[dict] = []

    async def body():
        async with streamablehttp_client(
            "http://127.0.0.1:8897/mcp", headers=hdr
        ) as (r, w, _):
            async with ClientSession(r, w, elicitation_callback=elicit_cb) as s:
                init = await s.initialize()
                out.append({"tag": tag, "protocol": init.protocolVersion})
                res = await s.call_tool("ask_confirm", {})
                out.append(
                    {
                        "tag": tag,
                        "content": [c.model_dump() for c in res.content],
                        "structured": res.structuredContent,
                    }
                )

    with anyio.move_on_after(timeout_s, shield=True):
        await body()
        out.append({"tag": tag, "done": True})
    return out


def cb_accept(m, schema):
    print(f"[{m}] accept", flush=True)
    from mcp.types import ElicitResult

    return ElicitResult(action="accept", content={"confirm": True})


def cb_decline(m, schema):
    print(f"[{m}] decline", flush=True)
    from mcp.types import ElicitResult

    return ElicitResult(action="decline")


async def main():
    mcp = build()
    _app = mcp.streamable_http_app()
    import uvicorn

    config = uvicorn.Config(_app, host="127.0.0.1", port=8897, log_level="error")
    server = uvicorn.Server(config)
    async with anyio.create_task_group() as tg:
        tg.start_soon(server.serve)
        for _ in range(80):
            try:
                with socket.create_connection(("127.0.0.1", 8897), timeout=0.2):
                    break
            except OSError:
                await anyio.sleep(0.05)
        results: list[dict] = []
        results += await probe("accept", {"Authorization": "Bearer x"}, cb_accept)
        results.append("---")
        results += await probe("decline", {"Authorization": "Bearer x"}, cb_decline)
        results.append("---")
        results += await probe("no-cb", {"Authorization": "Bearer x"}, None)
        tg.cancel_scope.cancel()
    print(json.dumps(results, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    anyio.run(main)

