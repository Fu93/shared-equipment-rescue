"""Live end-to-end tests over real Streamable HTTP transport.

Spawns uvicorn in a background taskgroup, then speaks MCP (initialize →
tools/call) exactly like a real client, including elicitation handling.
Reuses spike5's proven client wiring.
"""

import asyncio
import json
import os
import sys
import tempfile

import httpx
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import mcp  # noqa: E402
from mcp import ClientSession, types  # noqa: E402
from mcp.client.streamable_http import streamablehttp_client  # noqa: E402

MCP_PORT = int(os.environ.get("SER_TEST_PORT", "8907"))
URL = f"http://127.0.0.1:{MCP_PORT}/mcp"
TOKENS = {"manager": "tok-manager", "chen": "tok-chen", "li": "tok-li", "wang": "tok-wang"}


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


async def _start_server(dbp: str):
    os.environ["SER_DB_PATH"] = dbp
    os.environ.setdefault("SER_FROZEN_IN_TESTS", "0")
    import uvicorn
    from mcp_server.server import build_app, mcp as _mcp

    app = build_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=MCP_PORT, log_level="error")
    server = uvicorn.Server(config)

    task = asyncio.create_task(server.serve())
    # wait for readiness
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.05)
    assert server.started, "uvicorn did not start"
    return server, task


def _elicitation_handler(response_confirm):
    async def handler(message, schema):
        if response_confirm is None:
            from mcp.types import DeclinedElicitation

            return DeclinedElicitation()
        return types.ElicitResult(
            action="accept",
            content={"confirm": response_confirm},
        )

    return handler


class Client:
    """Stateful MCP client over streamable http with a token header."""

    def __init__(self, session, httpx_client, confirm=None):
        self.session = session
        self.http = httpx_client
        self.confirm = confirm

    async def call(self, name, args=None):
        res = await self.session.call_task if False else await self._call(name, args)
        return res

    async def _call(self, name, args=None):
        result = await self.session.call_tool(name, args or {})
        return result

    async def structured(self, name, args=None):
        res = await self._call(name, args)
        assert res.isError is False, f"isError on {name}: {res.content}"
        assert res.structuredContent is not None
        return res.structuredContent


async def _open_session(token, confirm=None):
    headers = {"authorization": f"Bearer {TOKENS[token]}"} if token else {}
    elic = _elicitation_handler(confirm)
    cm = streamablehttp_client(URL, headers=headers)
    read, write, get_session_id = await cm.__aenter__()
    # elicitation capability requires async callback on the ClientSession
    sm_cm = ClientSession(read, write, elicitation_callback=elic)
    session = await sm_cm.__aenter__()
    init = await session.initialize()
    return Client(session, None, confirm), cm, sm_cm, init


@pytest.fixture(scope="module")
async def server_env():
    dbp = os.path.join(tempfile.gettempdir(), "ser_test_server.db")
    if os.path.exists(dbp):
        os.remove(dbp)
    server, task = await _start_server(dbp)
    yield {"db": dbp}
    server.should_exit = True
    try:
        await asyncio.wait_for(task, timeout=5)
    except Exception:
        task.cancel()
    if os.path.exists(dbp):
        os.remove(dbp)


# --- tests --------------------------------


@pytest.mark.anyio
async def test_initialize_and_list_tools(server_env):
    client, hcm, scm, init = await _open_session("manager")
    try:
        assert init.protocolVersion == "2025-11-25"
        names = {t.name for t in (await client.session.list_tools()).tools}
        assert names == {
            "schedule_get",
            "equipment_report_outage",
            "schedule_propose_replan",
            "schedule_apply_replan",
            "reset_demo_data",
            "debug_confirm",
        }
    finally:
        await scm.__aexit__(None, None, None)
        await hcm.__aexit__(None, None, None)


@pytest.mark.anyio
async def test_forbidden_without_token(server_env):
    client, hcm, scm, init = await _open_session(None)
    try:
        res = await client.structured("schedule_get", {"unit_id": "lab-a", "date": "2026-10-20"})
        assert res["status"] == "forbidden"
    finally:
        await scm.__aexit__(None, None, None)
        await hcm.__aexit__(None, None, None)


@pytest.mark.anyio
async def test_manager_full_flow_http(server_env):
    client, hcm, scm, init = await _open_session("manager", confirm=True)
    try:
        g = await client.structured("schedule_get")
        assert g["status"] == "ok" and g["schedule_version"] == 1

        ro = await client.structured("equipment_report_outage", {
            "equipment_id": "confocal-a",
            "start": "2026-10-20T10:00:00+01:00",
            "end": "2026-10-20T16:00:00+01:00",
            "reason": "laser fault",
        })
        assert ro["status"] == "recorded" and ro["outage_id"] == "O1"
        v2 = ro["schedule_version"]

        pr = await client.structured("schedule_propose_replan", {
            "outage_id": "O1", "schedule_version": v2,
        })
        assert pr["status"] == "proposed"
        assert [(c["booking_id"], c["new_equipment"]) for c in pr["changes"]] == [
            ("B2", "confocal-b"), ("B4", "confocal-a"),
        ]

        ap = await client.structured("schedule_apply_replan", {
            "plan_id": pr["plan_id"], "schedule_version": v2,
        })
        assert ap["status"] == "applied" and ap["new_version"] == 3

        ap2 = await client.structured("schedule_apply_replan", {
            "plan_id": pr["plan_id"], "schedule_version": ap["new_version"],
        })
        assert ap2["status"] == "already_applied"
    finally:
        await scm.__aexit__(None, None, None)
        await hcm.__aexit__(None, None, None)


@pytest.mark.anyio
async def test_apply_declined_is_side_effect_free(server_env):
    client, hcm, scm, init = await _open_session("manager", confirm=True)
    try:
        ro = await client.structured("equipment_report_outage", {
            "equipment_id": "confocal-b",
            "start": "2026-10-20T10:00:00+01:00",
            "end": "2026-10-20T11:30:00+01:00",
            "reason": "x",
        })
        v = ro["schedule_version"]
        pr = await client.structured("schedule_propose_replan", {
            "outage_id": ro["outage_id"], "schedule_version": v,
        })
        assert pr["plan_id"]
    finally:
        await scm.__aexit__(None, None, None)
        await hcm.__aexit__(None, None, None)

    # fresh client WITHOUT elicitation confirmation (declines)
    client2, hcm2, scm2, _ = await _open_session("manager", confirm=None)
    try:
        res = await client2.session.call_tool("schedule_apply_replan", {
            "plan_id": pr["plan_id"], "schedule_version": v,
        })
        # declined elicitation -> not_confirmed (no isError at protocol level)
        data = res.structuredContent
        assert data["status"] == "not_confirmed"
        # plan still proposed
        g = await client2.structured("schedule_get")
        assert any(p["plan_id"] == pr["plan_id"] for p in g["pending_plans"])
    finally:
        await scm2.__aexit__(None, None, None)
        await hcm2.__aexit__(None, None, None)


@pytest.mark.anyio
async def test_researcher_forbidden_report(server_env):
    client, hcm, scm, init = await _open_session("li")
    try:
        res = await client.structured("equipment_report_outage", {
            "equipment_id": "confocal-a",
            "start": "2026-10-20T10:00:00+01:00",
            "end": "2026-10-20T16:00:00+01:00",
        })
        assert res["status"] == "forbidden"
    finally:
        await scm.__aexit__(None, None, None)
        await hcm.__aexit__(None, None, None)


@pytest.mark.anyio
async def test_plan_stale_after_version_bump(server_env):
    """Self-contained: reset first, then stale propose with the pre-outage version."""
    client, hcm, scm, init = await _open_session("manager", confirm=True)
    try:
        rs = await client.structured("reset_demo_data")
        assert rs["schedule_version"] == 1
        ro = await client.structured("equipment_report_outage", {
            "equipment_id": "confocal-a",
            "start": "2026-10-20T10:00:00+01:00",
            "end": "2026-10-20T16:00:00+01:00",
            "reason": "laser",
        })
        assert ro["schedule_version"] == 2
        res = await client.structured("schedule_propose_replan", {
            "outage_id": ro["outage_id"], "schedule_version": 1,
        })
        assert res["status"] == "plan_stale"
    finally:
        await scm.__aexit__(None, None, None)
        await hcm.__aexit__(None, None, None)


@pytest.mark.anyio
async def test_reset_restores_version(server_env):
    client, hcm, scm, init = await _open_session("manager", confirm=True)
    try:
        rs = await client.structured("reset_demo_data")
        assert rs["status"] == "reset" and rs["schedule_version"] == 1
    finally:
        await scm.__aexit__(None, None, None)
        await hcm.__aexit__(None, None, None)


# --- Phase 3: restart-cycle persistence ------------------------------------

import subprocess
import time as _time

_RESTART_PORT = 8799


def _spawn_server(port, dbp):
    """Spawn a fresh *subprocess* server (uvicorn+F ol FastMCP singleton:
    StreamableHTTPSessionManager.run() is single-shot per instance) sharing dbp."""
    code = (
        "import asyncio, os, sys\n"
        "sys.path.insert(0, %r)\n" % ROOT +
        "os.environ['SER_DB_PATH'] = %r\n" % dbp +
        "os.environ['SER_FROZEN_NOW'] = '2026-10-20T12:00:00+01:00'\n"
        "os.environ.setdefault('SER_FROZEN_IN_TESTS', '0')\n"
        "import uvicorn\n"
        "from mcp_server.server import build_app\n"
        "async def main():\n"
        "    app = build_app()\n"
        "    cfg = uvicorn.Config(app, host='127.0.0.1', port=%d, log_level='error')\n" % port +
        "    s = uvicorn.Server(cfg)\n"
        "    t = asyncio.create_task(s.serve())\n"
        "    for _ in range(200):\n"
        "        if s.started: break\n"
        "        await asyncio.sleep(0.05)\n"
        "    await asyncio.Event().wait()\n"
        "asyncio.run(main())\n"
    )
    env = dict(os.environ)
    env["SER_DB_PATH"] = dbp
    proc = subprocess.Popen(
        [sys.executable, "-X", "utf8", "-c", code],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    import httpx
    deadline = _time.time() + 15
    while _time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"server subprocess exited early: {proc.returncode}")
        try:
            r = httpx.post(
                f"http://127.0.0.1:{port}/mcp",
                headers={"authorization": "Bearer tok-manager",
                          "accept": "application/json, text/event-stream",
                          "content-type": "application/json"},
                json={"jsonrpc": "2.0", "id": 0, "method": "ping"},
                timeout=2,
            )
            if r.status_code < 500:
                return proc
        except httpx.HTTPError:
            pass
        _time.sleep(0.2)
    raise RuntimeError("server subprocess did not come up")


def _kill_server(proc):
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()


@pytest.mark.anyio
async def test_restart_cycle_persists_outage_and_plan(server_env):
    """Outage + proposed plan must survive a full server stop/restart cycle on
    the SAME db file (persistence contract), and re-propose must stay
    idempotent across the restart."""
    dbp = server_env["db"]

    # --- session 1: in-process fixture server; record outage + propose ---
    c1, cm1, scm1, _ = await _open_session("manager")
    try:
        ro = await c1.structured("equipment_report_outage", {
            "equipment_id": "confocal-a",
            "start": "2026-10-20T10:00:00+01:00",
            "end": "2026-10-20T16:00:00+01:00",
            "reason": "restart-persistence probe",
        })
        assert ro["status"] in ("recorded", "duplicate_outage")
        outage_id = ro["outage_id"]
        ver = ro["schedule_version"]
        pr = await c1.structured("schedule_propose_replan", {
            "outage_id": outage_id, "schedule_version": ver,
        })
        assert pr["status"] == "proposed"
        plan_id = pr["plan_id"]
        plan_ver = pr["schedule_version"]
        n_changes = len(pr["changes"])
        n_unres = len(pr["unresolved"])
    finally:
        await scm1.__aexit__(None, None, None)
        await cm1.__aexit__(None, None, None)

    # --- stop in-process server (fixture teardown comes later; the port stays
    #     busy, so the 'restarted' server runs on its own port 8799) ---
    # NOTE: true process kill isn't possible in-process here; a fresh
    # subprocess server pointing at the SAME db file on a NEW port is the
    # equivalent restart: new process, new FastMCP, same SQLite persistence.

    proc = await asyncio.wait_for(
        asyncio.get_event_loop().run_in_executor(
            None, _spawn_server, _RESTART_PORT, dbp), timeout=20)
    try:
        cm2 = streamablehttp_client(
            f"http://127.0.0.1:{_RESTART_PORT}/mcp",
            headers={"authorization": "Bearer tok-manager"})
        read2, write2, _ = await cm2.__aenter__()
        sm2 = ClientSession(read2, write2)
        c2 = await sm2.__aenter__()
        try:
            await c2.initialize()
            sg = await c2.call_tool("schedule_get", {
                "unit_id": "lab-a", "date": "2026-10-20"})
            sg_s = sg.structuredContent
            assert sg_s["status"] == "ok", sg_s
            assert sg_s["schedule_version"] == plan_ver
            # outage survived
            assert any(o["id"] == outage_id for o in sg_s["open_outages"])
            # plan survived and pending
            pp = [p for p in sg_s["pending_plans"] if p["plan_id"] == plan_id]
            assert len(pp) == 1, (
                f"plan {plan_id} missing after restart: {sg_s['pending_plans']}")
            assert pp[0]["change_count"] == n_changes
            assert pp[0]["unresolved_count"] == n_unres
            # idempotent re-propose returns the same plan after restart
            pr2 = await c2.call_tool("schedule_propose_replan", {
                "outage_id": outage_id, "schedule_version": plan_ver})
            pr2_s = pr2.structuredContent
            assert pr2_s["status"] == "proposed"
            assert pr2_s["plan_id"] == plan_id
            assert pr2_s["message"] == (
                f"existing plan {plan_id} reused (idempotent)")
        finally:
            await sm2.__aexit__(None, None, None)
            await cm2.__aexit__(None, None, None)
    finally:
        _kill_server(proc)
