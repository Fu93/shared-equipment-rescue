# Spike 3c: SSE (json_response=False) elicitation, with an *async* callback.
# Verifies the full trio: accept / decline / no-callback -> concrete tool results.
import anyio
import json
import socket

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.fastmcp import FastMCP, Context
from mcp.types import ElicitResult
from pydantic import BaseModel


class Confirm(BaseModel):
    confirm: bool


TRUE_TEXT = "YES"
FALSE_TEXT = "NO"


def make_mcp() -> FastMCP:
    mcp = FastMCP("spike3c", stateless_http=False, json_response=False)

    @mcp.tool()
    async def ask_confirm(ctx: Context, behavior: str) -> Confirm:
        """Elicits a boolean. behavior: accept|decline|cancel are applied by the client."""
        try:
            res = await ctx.elicit("Apply this change? Please confirm.", Confirm)
        except Exception as e:  # no elicitation capability in client
            return Confirm(confirm=False) if FALSE_TEXT else Confirm(confirm=e.__class__.__name__ != "")
        if res.__class__.__name__ == "AcceptedElicitation":
            return Confirm(confirm=bool(res.data.confirm))
        return Confirm(confirm=False)

    return mcp


async def run_one(port: int, behavior: str, with_cb: bool):
    mcp = make_mcp()
    app = mcp.streamable_http_app()
    import uvicorn

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    async with anyio.create_task_group() as tg:
        async def serve_quiet():
            try:
                await server.serve()
            except BaseException:
                pass
        tg.start_soon(serve_quiet)
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                await anyio.sleep(0.05)

        async def cb(ctx, params):
            # client applies the scripted behavior
            action = behavior if behavior in ("accept", "decline", "cancel") else "cancel"
            if action == "accept":
                return ElicitResult(action="accept", content={"confirm": True})
            return ElicitResult(action=action)

        async def run_session():
            kwargs = {"headers": {"Authorization": "Bearer x"}}
            if with_cb:
                kwargs["elicitation_callback"] = cb
            async with streamablehttp_client(
                f"http://127.0.0.1:{port}/mcp", **kwargs
            ) as (r, w, sid):
                async with ClientSession(
                    r, w, elicitation_callback=cb if with_cb else None
                ) as s:
                    init = await s.initialize()
                    out = {"protocol": init.protocolVersion}
                    res = await s.call_tool(
                        "ask_confirm", {"behavior": behavior}
                    )
                    out["structured"] = res.structuredContent
                    out["text"] = [c.text for c in res.content if getattr(c, "text", None)]
                    return out

        try:
            with anyio.move_on_after(60):
                return await run_session()
        finally:
            tg.cancel_scope.cancel()


async def main():
    results = {}
    for port, behavior, with_cb in [
        (8901, "accept", True),
        (8902, "decline", True),
        (8903, "cancel", True),
        (8904, "accept", False),
    ]:
        try:
            results[f"{behavior}{'-with-cb' if with_cb else '-no-cb'}"] = await run_one(
                port, behavior, with_cb
            )
        except Exception as e:
            results[f"{behavior}{'-with-cb' if with_cb else '-no-cb'}"] = {
                "error": f"{type(e).__name__}: {e}"
            }
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    anyio.run(main)
