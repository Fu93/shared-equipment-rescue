# Spike: does a per-request Authorization header reach the tool on each call?
# Tests stateful and stateless FastMCP streamable-HTTP modes with a real client.
import contextvars
import json

import anyio
from starlette.types import ASGIApp, Receive, Scope, Send

from mcp.server.fastmcp import FastMCP

CUR = contextvars.ContextVar("cur", default="-")


class TokenMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "http":
            headers = {
                k.decode("latin-1").lower(): v.decode("latin-1")
                for k, v in scope.get("headers", [])
            }
            tok = CUR.set(headers.get("authorization", ""))
            try:
                await self.app(scope, receive, send)
            finally:
                CUR.reset(tok)
        else:
            await self.app(scope, receive, send)


def build(stateless: bool) -> FastMCP:
    mcp = FastMCP("spike", stateless_http=stateless, json_response=True)

    @mcp.tool()
    def whoami() -> dict:
        """Return the token visible inside the tool."""
        return {"middleware_token": CUR.get()}

    return mcp


async def client_probe(url: str) -> list[dict]:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    out = []

    async def with_session(headers: dict, tag: str, calls: list[str]):
        async with streamablehttp_client(url, headers=headers) as (r, w, _):
            async with ClientSession(r, w) as s:
                init = await s.initialize()
                out.append({"tag": tag, "protocol": init.protocolVersion})
                for call_headers in (None, {"Authorization": "Bearer call-time-token"}):
                    for tool in calls:
                        res = await s.call_tool(
                            "whoami", {}, headers=call_headers if False else None
                        )
                        out.append(
                            {
                                "tag": tag,
                                "tool": tool,
                                "with_call_headers": call_headers is not None,
                                "content": [c.model_dump() for c in res.content],
                                "structured": res.structuredContent,
                            }
                        )

    await with_session({"Authorization": "Bearer init-time-token"}, "sess1", ["whoami"])
    return out


async def serve(mcp: FastMCP, port: int) -> None:
    import uvicorn

    app = mcp.streamable_http_app()
    wrapped = TokenMiddleware(app)
    config = uvicorn.Config(wrapped, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    for stateless in (False, True):
        mcp = build(stateless)
        mode = "stateless" if stateless else "stateful"
        task = anyio.create_task_group()  # noqa
        import anyio

        async def run_server_and_client():
            async with anyio.create_task_group() as tg:
                import uvicorn  # noqa
                from starlette.types import ASGIApp  # noqa

                ready = anyio.Event()

                async def _serve():
                    # serve in same task group so we can cancel
                    config = uvicorn.Config(
                        TokenMiddleware(mcp.streamable_http_app()),
                        host="127.0.0.1",
                        port=8811 if stateless else 8812,
                        log_level="error",
                    )
                    server = uvicorn.Server(config)
                    tg.start_soon(server.serve)
                    # wait a moment for bind
                    import time

                    for _ in range(80):
                        import socket

                        try:
                            with socket.create_connection(
                                ("127.0.0.1", config.port), timeout=0.2
                            ):
                                ready.set()
                                break
                        except OSError:
                            await anyio.sleep(0.05)
                    if not ready.is_set():
                        raise RuntimeError("server did not start")

                await _serve()

                url = f"http://127.0.0.1:{8811 if stateless else 8812}/mcp"
                # need session manager lifespan for stateful mode
                results: list = []

                from mcp import ClientSession
                from mcp.client.streamable_http import streamablehttp_client

                async def probe(tag: str, tool_headers: dict | None):
                    async with streamablehttp_client(
                        url, headers={"Authorization": "Bearer init-time-token"}
                    ) as (r, w, _):
                        async with ClientSession(r, w) as s:
                            init = await s.initialize()
                            results.append(
                                {"tag": tag, "protocol": init.protocolVersion}
                            )
                            res = await s.call_tool("whoami", {}, headers=tool_headers)
                            results.append(
                                {
                                    "tag": tag,
                                    "hdr": tool_headers,
                                    "structured": res.structuredContent,
                                }
                            )

                # stateful mode requires lifespan; run session manager within this task group
                if stateless:
                    await probe("call-no-hdr", None)
                    results.append("---")
                    await probe("call-hdr", {"Authorization": "Bearer call-time-token"})
                else:
                    async with mcp.session_manager.run():
                        await probe("call-no-hdr", None)
                        results.append("---")
                        await probe(
                            "call-hdr", {"Authorization": "Bearer call-time-token"}
                        )

                print(f"===== MODE {mode} =====")
                for r in results:
                    print(json.dumps(r, ensure_ascii=False))
                tg.cancel_scope.cancel()

        await run_server_and_client()
        print()


if __name__ == "__main__":
    anyio.run(main)
