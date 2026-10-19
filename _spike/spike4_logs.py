# Spike 4: minimal elicitation over streamable HTTP with full server logs,
# to capture exactly where "Invalid request parameters" originates.
import anyio
import json
import logging
import socket

import mcp.client.streamable_http as client_http
import mcp.server.streamable_http as server_http
import mcp.shared.session as shared_session

logging.basicConfig(level=logging.DEBUG, format="%(name)s %(levelname)s %(message)s")
for noisy in ("httpx", "httpcore", "asyncio", "cel"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.fastmcp import FastMCP, Context
from mcp.types import ElicitResult
from pydantic import BaseModel


class Confirm(BaseModel):
    confirm: bool


def cb(m, schema):
    logging.getLogger("spike").info("elicitation callback fired: %s", m)
    return ElicitResult(action="accept", content={"confirm": True})


async def main():
    mcp = FastMCP("spike4", stateless_http=False, json_response=True)

    @mcp.tool()
    async def ask_confirm(ctx: Context) -> Confirm:
        """Elicits a boolean."""
        res = await ctx.elicit("Apply?", Confirm)
        return Confirm(confirm=res.__class__.__name__ == "AcceptedElicitation")

    app = mcp.streamable_http_app()
    import uvicorn

    config = uvicorn.Config(app, host="127.0.0.1", port=8896, log_level="error")
    server = uvicorn.Server(config)
    async with anyio.create_task_group() as tg:
        tg.start_soon(server.serve)
        for _ in range(80):
            try:
                with socket.create_connection(("127.0.0.1", 8896), timeout=0.2):
                    break
            except OSError:
                await anyio.sleep(0.05)
        async with streamablehttp_client(
            "http://127.0.0.1:8896/mcp", headers={"Authorization": "Bearer x"}
        ) as (r, w, _):
            async with ClientSession(r, w, elicitation_callback=cb) as s:
                init = await s.initialize()
                print("protocol:", init.protocolVersion, flush=True)
                res = await s.call_tool("ask_confirm", {})
                print("RESULT:", [c.model_dump() for c in res.content], flush=True)
        tg.cancel_scope.cancel()


if __name__ == "__main__":
    anyio.run(main)
