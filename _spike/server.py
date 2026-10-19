# Spike: verify per-request Authorization over Streamable HTTP reaches FastMCP tools.
import contextvars
import sys
from dataclasses import dataclass
from typing import Any

import anyio
from starlette.applications import Starlette
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.routing import Mount

from mcp.server.fastmcp import FastMCP, Context

CUR_TOKEN = contextvars.ContextVar("cur_token", default=None)
CUR_SCOPE = contextvars.ContextVar("cur_scope", default=None)


class TokenMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http",):
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        tok = headers.get("authorization", "")
        token = CUR_TOKEN.set(tok)
        ts = CUR_SCOPE.set(scope)
        try:
            await self.app(scope, receive, send)
        finally:
            CUR_SCOPE.reset(ts)
            CUR_TOKEN.reset(token)


@dataclass
class Who:
    middleware_token: str | None
    ctx_request_attrs: list[str]
    session_id: str | None = None


mcp = FastMCP("spike", stateless_http=False, json_response=True)


@mcp.tool()
def whoami(ctx: Context) -> dict:
    """Return the identity info visible inside the tool."""
    req = getattr(ctx.request_context, "request", None)
    attrs = sorted(a for a in dir(req) if not a.startswith("_")) if req is not None else []
    try:
        sess = str(ctx.session.session_id) if ctx.session else None
    except Exception as e:
        sess = f"err:{e}"
    return {
        "middleware_token": CUR_TOKEN.get(),
        "ctx_request_attrs": attrs[:40],
        "session_id": sess,
    }


app = mcp.streamable_http_app()


async def lifespan(starlette_app):
    async with anyio.create_task_group() as tg:
        async with mcp.session_manager.run():
            tg.start_soon(lambda: (yield))

async def run():
    star = Starlette(
        routes=[Mount("/", app)],
        middleware=[],
    )
    # wrap
    wrapped = TokenMiddleware(app)
    import uvicorn
    config = uvicorn.Config(wrapped, host="127.0.0.1", port=8799, log_level="error")
    srv = uvicorn.Server(config)
    await srv.serve()


if __name__ == "__main__":
    print("spike server on :8799", flush=True)

    # Wire lifespan to make session manager ready (needed in stateful mode)
    app.router.lifespan_context = _real_lifespan if False else None  # cleanup below
print("built")
