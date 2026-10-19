# Spike 5: minimal PASS/FAIL verdict per elicitation scenario, no ExceptionGroup noise.
import anyio, json, socket

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.fastmcp import FastMCP, Context
from mcp.types import ElicitResult
from pydantic import BaseModel


class Confirm(BaseModel):
    confirm: bool


def make_mcp() -> FastMCP:
    mcp = FastMCP("spike5", stateless_http=False, json_response=False)

    @mcp.tool()
    async def ask_confirm(ctx: Context, behavior: str) -> Confirm:
        """Elicits a boolean."""
        try:
            res = await ctx.elicit("Apply this change? Please confirm.", Confirm)
        except Exception as e:
            raise RuntimeError(f"ELICIT_EXC:{type(e).__name__}:{e}")
        name = res.__class__.__name__
        if name == "AcceptedElicitation":
            return Confirm(confirm=bool(res.data.confirm))
        if name == "DeclinedElicitation":
            return Confirm(confirm=False)
        return Confirm(confirm=False)  # cancel

    return mcp


async def run_one(port: int, behavior: str, with_cb: bool) -> dict:
    mcp = make_mcp()
    app = mcp.streamable_http_app()
    import uvicorn

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="critical")
    server = uvicorn.Server(config)
    serve_done: list[str] = []

    async def serve_quiet():
        try:
            await server.serve()
        except BaseException as e:
            serve_done.append(type(e).__name__)

    async with anyio.create_task_group() as tg:
        tg.start_soon(serve_quiet)
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                await anyio.sleep(0.05)

        async def cb(ctx, params):
            if behavior == "accept":
                return ElicitResult(action="accept", content={"confirm": True})
            if behavior == "decline":
                return ElicitResult(action="decline")
            return ElicitResult(action="cancel")

        async def run_session():
            async with streamablehttp_client(
                f"http://127.0.0.1:{port}/mcp", headers={"Authorization": "Bearer x"},
            ) as (r, w, sid):
                async with ClientSession(r, w, elicitation_callback=cb if with_cb else None) as s:
                    init = await s.initialize()
                    res = await s.call_tool("ask_confirm", {"behavior": behavior})
                    return {
                        "protocol": init.protocolVersion,
                        "structured": res.structuredContent,
                        "isError": res.isError,
                        "text": [c.text for c in res.content if getattr(c, "text", None)],
                    }

        out = {}
        with anyio.move_on_after(60):
            try:
                out = await run_session()
            except BaseException as e:
                out = {"error": f"{type(e).__name__}: {e}"}
        tg.cancel_scope.cancel()
    return out


async def main():
    results = {}
    for port, behavior, with_cb, label in [
        (8911, "accept", True, "accept"),
        (8912, "decline", True, "decline"),
        (8913, "cancel", True, "cancel"),
        (8914, "accept", False, "no-callback"),
    ]:
        try:
            results[label] = await run_one(port, behavior, with_cb)
        except BaseException as e:
            results[label] = {"uncaught": f"{type(e).__name__}: {e}"}
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    anyio.run(main)
