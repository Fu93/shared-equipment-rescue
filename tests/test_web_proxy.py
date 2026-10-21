"""Web proxy regression tests (the web/ layer had no test coverage).

Covers the transport guard and the proxy contract the browser demo depends on:

* the Origin/Host guard accepts any LOOPBACK origin/host (the shell is
  started with a configurable --port, so a hard-coded "127.0.0.1:8080"
  silently 403s every route on every other port) while still rejecting
  foreign hosts and origins, which is the DNS-rebinding attack the guard
  exists for;
* the proxy relays a real MCP Streamable HTTP session (initialize, list_tools,
  call_tool) end to end;
* a dead upstream yields 502 with an actionable hint, not a bare 500;
* /metrics aggregates proxy state and the upstream section, and reports the
  same rate-limit budget the README documents.

The MCP server is started in-process on an ephemeral port, the proxy is
started as a subprocess against it.
"""

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time

import httpx
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from mcp import ClientSession  # noqa: E402
from mcp.client.streamable_http import streamablehttp_client  # noqa: E402

MCP_PORT = int(os.environ.get("SER_TEST_PORT3", "0"))  # 0 = OS-assigned ephemeral
URL = f"http://127.0.0.1:{MCP_PORT}/mcp"
WEB_PORT = int(os.environ.get("SER_TEST_WEB_PORT", "0"))  # 0 = OS-assigned ephemeral
WEB_URL = f"http://127.0.0.1:{WEB_PORT}"


def _bound_port(server) -> int:
    ports = [sock.getsockname()[1] for s in (getattr(server, "servers", None) or [])
             for sock in (getattr(s, "sockets", None) or [])]
    assert len(ports) == 1, f"expected exactly one bound port, got {ports}"
    return ports[0]


async def _wait_started(server, task):
    for _ in range(100):
        if getattr(server, "started", False):
            return
        if task.done():
            exc = task.exception()
            raise RuntimeError(
                f"uvicorn failed to start (port conflict or app error): {exc!r}"
            )
        await asyncio.sleep(0.05)
    raise RuntimeError("uvicorn did not start within 5 seconds")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="module")
def live_stack():
    """Start MCP in a background thread + the web proxy as a subprocess."""
    global URL, MCP_PORT, WEB_PORT, WEB_URL
    import threading

    import uvicorn
    from mcp.server.fastmcp import FastMCP
    from mcp_server.server import TransportGuardMiddleware, register_all_tools

    os.environ["SER_NO_RATE_LIMIT"] = "1"
    import tempfile

    dbp = os.path.join(tempfile.gettempdir(), "ser_webproxy_test.db")
    if os.path.exists(dbp):
        os.remove(dbp)
    os.environ["SER_DB_PATH"] = dbp

    fresh = FastMCP("shared-equipment-rescue-web-test",
                    host="127.0.0.1", port=0,
                    stateless_http=False, json_response=False)
    register_all_tools(fresh)
    import mcp_server.server as srv
    srv.initialize_storage()
    app = TransportGuardMiddleware(fresh.streamable_http_app())
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
    server = uvicorn.Server(config)
    loop = asyncio.new_event_loop()

    def _run():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(server.serve())

    th = threading.Thread(target=_run, daemon=True)
    th.start()
    for _ in range(100):
        if getattr(server, "started", False):
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("MCP server did not start")
    MCP_PORT = _bound_port(server)
    URL = f"http://127.0.0.1:{MCP_PORT}/mcp"

    WEB_PORT = _free_port()
    WEB_URL = f"http://127.0.0.1:{WEB_PORT}"
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    out = open(os.path.join(tempfile.gettempdir(), "ser_web_proxy_out.log"), "w+",
               encoding="utf-8")
    web = subprocess.Popen(
        [sys.executable, "-X", "utf8", "app.py", "--port", str(WEB_PORT),
         "--mcp-port", str(MCP_PORT)],
        cwd=os.path.join(ROOT, "web"), env=env, creationflags=0x08000000,
        stdout=out, stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.time() + 25
        while time.time() < deadline:
            try:
                if httpx.get(f"{WEB_URL}/metrics", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if web.poll() is not None:
                out.flush()
                out.seek(0)
                raise RuntimeError(
                    "web proxy exited: " + out.read()[-2000:]
                )
            time.sleep(0.3)
        else:
            out.flush()
            out.seek(0)
            raise RuntimeError("web proxy did not start: " + out.read()[-2000:])
        yield {"web": web, "mcp_port": MCP_PORT, "web_port": WEB_PORT,
               "web_url": WEB_URL, "mcp_url": URL, "server": server}
    finally:
        try:
            web.terminate()
            web.wait(timeout=6)
        except Exception:
            try:
                web.kill()
            except Exception:
                pass
        server.should_exit = True
        time.sleep(0.5)


# --- transport guard --------------------------------------------------------


def test_loopback_host_allowed_any_port():
    """Any loopback host:port is legitimate (the shell has a --port flag)."""
    from web.app import _loopback_host_allowed  # noqa: E402

    for host in ("127.0.0.1:8080", "127.0.0.1:8099", "127.0.0.1:65535",
                 "localhost:3000", "[::1]:8080", "127.0.0.1"):
        assert _loopback_host_allowed(host) is True, host
    # the attack the guard exists for stays blocked
    for host in ("evil.example", "evil.example:8099", "attacker.test:80",
                 "192.168.1.10:8080", "10.0.0.5"):
        assert _loopback_host_allowed(host) is False, host
    # absent Host is tolerated
    assert _loopback_host_allowed("") is True


def test_loopback_origin_allowed_any_port():
    """A browser's own Origin carries the port it was served on."""
    from web.app import _origin_allowed  # noqa: E402

    for origin in ("http://127.0.0.1:8080", "http://127.0.0.1:8099",
                   "http://localhost:3000", "http://[::1]:8080"):
        assert _origin_allowed(origin) is True, origin
    for origin in ("http://evil.example", "https://evil.example:8099",
                   "http://192.168.1.10:8080", "file://", "null"):
        assert _origin_allowed(origin) is False, origin


def test_guard_accepts_own_port_and_rejects_foreign(live_stack):
    """End-to-end: the served port works, a foreign Host/Origin is 403."""
    base = live_stack["web_url"]
    r = httpx.get(base + "/", timeout=10)
    assert r.status_code == 200, r.status_code
    assert "Facility Manager" in r.text

    assert httpx.get(base + "/", headers={"Host": "evil.example"},
                     timeout=10).status_code == 403
    assert httpx.get(base + "/", headers={"Origin": "http://evil.example"},
                     timeout=10).status_code == 403
    ok = httpx.get(base + "/", headers={"Host": f"127.0.0.1:{live_stack['web_port']}"},
                   timeout=10)
    assert ok.status_code == 200


# --- proxy behaviour --------------------------------------------------------


def test_proxy_relays_real_mcp_session(live_stack):
    """A real MCP client over the proxy: 8 tools and a working schedule_get."""
    url = live_stack["web_url"] + "/mcp"

    async def _run():
        async with streamablehttp_client(
            url, headers={"authorization": "Bearer tok-manager"}
        ) as (read, write, _sid):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = sorted(t.name for t in tools.tools)
                got = await session.call_tool("schedule_get", {})
                return names, got.structuredContent or {}

    names, payload = asyncio.run(_run())
    assert len(names) == 8, names
    assert payload.get("schedule_version") is not None, payload


def test_metrics_aggregates_both_layers(live_stack):
    m = httpx.get(live_stack["web_url"] + "/metrics", timeout=10).json()
    assert "proxy" in m and m["proxy"]["rate_limit"]["burst"] == 16, m
    assert m.get("server") is not None and "error" not in m["server"], m["server"]


def test_dead_upstream_returns_502_with_hint(live_stack):
    """If the MCP server dies, the proxy explains how to restart it."""
    live_stack["server"].should_exit = True
    for _ in range(60):
        try:
            httpx.get(f"http://127.0.0.1:{live_stack['mcp_port']}/metrics", timeout=1)
        except httpx.HTTPError:
            break
        time.sleep(0.2)
    r = httpx.post(live_stack["web_url"] + "/mcp",
                   headers={"authorization": "Bearer tok-manager",
                            "accept": "application/json, text/event-stream",
                            "content-type": "application/json"},
                   json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                   timeout=15)
    assert r.status_code == 502, (r.status_code, r.text[:200])
    body = r.json()
    assert "mcp_server" in body["error"]["message"], body
