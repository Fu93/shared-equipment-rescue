"""Accountability & concurrency hardening regression tests (this round).

Covers:
* researcher public-tool visibility in the audit trail (SQL boundary),
* apply-flow TOCTOU fix: racing double-apply applies exactly once,
* transport ledger: 403 origin/host rejections land hash-chained rows that
  /metrics exposes and a demo reset never shrinks,
* /metrics pins both chain heads,
* audit chain stays green over the whole flow.
"""

import asyncio
import os
import sys
import tempfile

import httpx
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from mcp import ClientSession, types  # noqa: E402
from mcp.client.streamable_http import streamablehttp_client  # noqa: E402

MCP_PORT = int(os.environ.get("SER_TEST_PORT2", "0"))  # 0 = OS-assigned ephemeral port
URL = f"http://127.0.0.1:{MCP_PORT}/mcp"
TOKENS = {"manager": "tok-manager", "li": "tok-li"}
DEMO_DATE = "2026-10-20"


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


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


async def _start_server(dbp: str):
    global URL, MCP_PORT
    os.environ["SER_DB_PATH"] = dbp
    os.environ["SER_NO_RATE_LIMIT"] = "1"
    import uvicorn
    from mcp_server.server import TransportGuardMiddleware, register_all_tools

    # Fresh FastMCP instance per module: the module-level singleton's
    # StreamableHTTPSessionManager is single-shot per process (run() once);
    # a second in-process server must build its own.
    from mcp.server.fastmcp import FastMCP
    fresh = FastMCP("shared-equipment-rescue-test2",
                    host="127.0.0.1", port=MCP_PORT,
                    stateless_http=False, json_response=False)
    register_all_tools(fresh)
    import mcp_server.server as srv
    srv.initialize_storage()
    app = TransportGuardMiddleware(fresh.streamable_http_app())
    config = uvicorn.Config(app, host="127.0.0.1", port=MCP_PORT,
                            log_level="error")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    await _wait_started(server, task)
    MCP_PORT = _bound_port(server)
    URL = f"http://127.0.0.1:{MCP_PORT}/mcp"
    return server, task


def _elicitation_handler(confirm_value):
    """confirm=True/False → ElicitResult content {"confirm": bool};
    None → DeclinedElicitation (client refuses the prompt)."""
    async def handler(message, schema):
        if confirm_value is None:
            from mcp.types import DeclinedElicitation
            return DeclinedElicitation()
        return types.ElicitResult(
            action="accept", content={"confirm": bool(confirm_value)}
        )

    return handler


class Client:
    def __init__(self, session):
        self.session = session

    async def structured(self, name, args=None):
        res = await self.session.call_tool(name, args or {})
        assert res.isError is False, f"isError on {name}: {res.content}"
        return res.structuredContent


async def _open_session(token, confirm=None):
    headers = {"authorization": f"Bearer {TOKENS[token]}"} if token else {}
    cm = streamablehttp_client(URL, headers=headers)
    read, write, _ = await cm.__aenter__()
    sm_cm = ClientSession(
        read, write, elicitation_callback=_elicitation_handler(confirm)
    )
    session = await sm_cm.__aenter__()
    await session.initialize()
    return Client(session), cm, sm_cm


@pytest.fixture(scope="module")
async def server_env():
    dbp = os.path.join(tempfile.gettempdir(), "ser_test_accountability.db")
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


def _metrics():
    r = httpx.get(
        f"http://127.0.0.1:{MCP_PORT}/metrics",
        headers={"host": f"127.0.0.1:{MCP_PORT}"}, timeout=5,
    )
    assert r.status_code == 200
    return r.json()["database"]


def _report_outage(client, equipment_id="confocal-a"):
    return client.structured("equipment_report_outage", {
        "equipment_id": equipment_id,
        "start": f"{DEMO_DATE}T10:00:00+01:00",
        "end": f"{DEMO_DATE}T16:00:00+01:00",
        "reason": "accountability probe",
    })


# 1) researcher public-visibility SQL fix -----------------------------------


@pytest.mark.anyio
async def test_researcher_sees_public_tool_events(server_env):
    """Researcher audit view = own rows + PUBLIC_TOOLS rows (SQL boundary)."""
    m, hm, hmS = await _open_session("manager", confirm=True)
    try:
        ro = await _report_outage(m)
        assert ro["status"] == "recorded"
    finally:
        await hmS.__aexit__(None, None, None)
        await hm.__aexit__(None, None, None)

    l, hl, hlS = await _open_session("li")
    try:
        audit = await l.structured("schedule_audit_get", {})
        assert audit["status"] == "ok"
        tools_seen = {e["tool"] for e in audit["entries"]}
        # manager's public tool event is visible to the researcher
        assert "equipment_report_outage" in tools_seen
        # manager's private tool events are NOT visible
        assert "schedule_get" not in tools_seen
        assert "verify_audit_chain" not in tools_seen
    finally:
        await hlS.__aexit__(None, None, None)
        await hl.__aexit__(None, None, None)


# 2) apply TOCTOU -----------------------------------------------------------


@pytest.mark.anyio
async def test_double_apply_is_single_submitted(server_env):
    """Concurrent double apply: exactly one 'applied'; the other sees
    already_applied/plan_stale — and the version never double-bumps."""
    m, hm, hmS = await _open_session("manager", confirm=True)
    try:
        rs = await m.structured("reset_demo_data")
        assert rs["schedule_version"] == 1
        ro = await _report_outage(m, "confocal-b")
        v = ro["schedule_version"]
        pr = await m.structured("schedule_propose_replan", {
            "outage_id": ro["outage_id"], "schedule_version": v,
        })
        assert pr["status"] == "proposed"

        new_version_before = None
        applied_results, stale_results = await asyncio.gather(
            m.structured("schedule_apply_replan", {
                "plan_id": pr["plan_id"], "schedule_version": v,
            }),
            m.structured("schedule_apply_replan", {
                "plan_id": pr["plan_id"], "schedule_version": v,
            }),
        )
        results = [applied_results, stale_results]
        statuses = [r["status"] for r in results]
        assert statuses.count("applied") == 1, statuses
        other = next(r for r in results if r["status"] != "applied")
        assert other["status"] in ("already_applied", "plan_stale"), other
        for r in results:
            if r["status"] == "applied":
                new_version_before = r["new_version"]
        # version bumped exactly once from v
        assert new_version_before == v + 1, (new_version_before, v)
    finally:
        await hmS.__aexit__(None, None, None)
        await hm.__aexit__(None, None, None)


# 3) transport ledger -------------------------------------------------------


@pytest.mark.anyio
async def test_transport_rejections_land_in_ledger(server_env):
    """403 origin + 403 host leave hash-chained rows; /metrics pins both heads.

    Uses httpx.AsyncClient: the uvicorn server runs on THIS test's event loop,
    so a sync httpx call would block the loop and deadlock.
    """
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{MCP_PORT}",
                                 timeout=10) as http:
        r1 = await http.post("/mcp", headers={
            "origin": "https://evil.example",
            "accept": "application/json",
            "content-type": "application/json",
        }, json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert r1.status_code == 403, r1.text

        r2 = await http.post("/mcp", headers={
            "host": "evil.example",
            "accept": "application/json",
            "content-type": "application/json",
        }, json={"jsonrpc": "2.0", "id": 2, "method": "ping"})
        assert r2.status_code == 403, r2.text

        # NOTE: 429 is rate-limit driven; SER_NO_RATE_LIMIT=1 disables it for
        # this module's server, so 429 is exercised live in the probe.

        m = await http.get("/metrics", headers={"host": f"127.0.0.1:{MCP_PORT}"})
        assert m.status_code == 200
    dbf = m.json()["database"]
    ledger = dbf["transport_ledger"]
    assert ledger["ok"] is True
    ev = ledger["events"]
    assert ev["origin"] >= 1, ev
    assert ev["host"] >= 1, ev
    assert ledger["head_hash"]
    chain = dbf["audit_chain"]
    assert chain["ok"] is True
    assert chain["head_hash"]


@pytest.mark.anyio
async def test_transport_ledger_survives_reset(server_env):
    """reset_demo_data wipes the demo workspace but never shrinks the
    transport ledger (retained per-peer evidence)."""
    m, hm, hmS = await _open_session("manager", confirm=True)
    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{MCP_PORT}",
                                     timeout=10) as http:
            r = await http.get("/metrics",
                               headers={"host": f"127.0.0.1:{MCP_PORT}"})
            before = r.json()["database"]["transport_ledger"]["events"]["total"]

            await http.post("/mcp", headers={
                "origin": "https://attacker.example",
                "accept": "application/json",
                "content-type": "application/json",
            }, json={"jsonrpc": "2.0", "id": 9, "method": "ping"})
            r = await http.get("/metrics",
                               headers={"host": f"127.0.0.1:{MCP_PORT}"})
            mid = r.json()["database"]["transport_ledger"]["events"]["total"]
            assert mid >= before + 1

        rs = await m.structured("reset_demo_data")
        assert rs["status"] == "reset"
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{MCP_PORT}",
                                     timeout=10) as http:
            r = await http.get("/metrics",
                               headers={"host": f"127.0.0.1:{MCP_PORT}"})
            after = r.json()["database"]["transport_ledger"]["events"]["total"]
            assert after >= mid
            # ledger chain still intact after the reset
            assert r.json()["database"]["transport_ledger"]["ok"] is True
    finally:
        await hmS.__aexit__(None, None, None)
        await hm.__aexit__(None, None, None)


# 4) chain green + already_applied replay audited ---------------------------


@pytest.mark.anyio
async def test_audit_pagination_no_row_dropped(server_env):
    """P0 regression: paging limit=N over M rows must display EVERY visible
    row exactly once — no silent drop at any page boundary.

    Pre-fix behavior: the cursor pointed at page[-1] of the un-truncated
    (+1 lookahead) fetch, so that row was never displayed; paging limit=2
    over 5 rows returned only 4. The fix walks strictly below the last
    DISPLAYED row (keyset semantics).
    """
    m, hm, hmS = await _open_session("manager", confirm=True)
    try:
        rs = await m.structured("reset_demo_data")
        assert rs["status"] == "reset"

        # Seed 5 static rows under a dedicated tool name, then page with
        # tool_filter so the walks are comparable across limits — otherwise
        # each schedule_audit_get call writes its own audit row mid-walk and
        # the newest-first set shifts under our feet.
        from mcp_server.db import record_audit_standalone
        for i in range(5):
            record_audit_standalone(
                tool="pagination_probe", result="ok",
                actor_id="user-manager", detail=f"seed{i}",
            )

        for limit in (1, 2, 3):
            collected = []
            cursor = None
            for _ in range(50):  # runaway guard
                args = {"limit": limit, "tool_filter": "pagination_probe"}
                if cursor is not None:
                    args["before_id"] = cursor
                page = await m.structured("schedule_audit_get", args)
                assert page["status"] == "ok", page
                collected.extend(
                    e["detail"] for e in page["entries"])
                if page["next_before_id"] is None:
                    break
                cursor = page["next_before_id"]
            else:
                pytest.fail("runaway pagination")
            assert sorted(collected) == [f"seed{i}" for i in range(5)], (
                f"limit={limit}: row dropped or duplicated: {collected}")
    finally:
        await hmS.__aexit__(None, None, None)
        await hm.__aexit__(None, None, None)


@pytest.mark.anyio
async def test_debug_confirm_writes_audit_row(server_env):
    """debug_confirm elicitation outcomes are audited like every other tool."""
    m, hm, hmS = await _open_session("manager", confirm=True)
    try:
        rs = await m.structured("reset_demo_data")
        assert rs["status"] == "reset"
        dc = await m.structured("debug_confirm")
        assert dc["elicited"] is True and dc["action"] == "accept", dc

        audit = await m.structured("schedule_audit_get", {"limit": 10})
        assert audit["status"] == "ok"
        rows = [(e["tool"], e["result"]) for e in audit["entries"]]
        assert ("debug_confirm", "accept") in rows, rows[:5]
        # its own reset row is the newest entry (reset wipe happens first)
        assert rows[0][0] in ("debug_confirm", "reset_demo_data"), rows[:3]
    finally:
        await hmS.__aexit__(None, None, None)
        await hm.__aexit__(None, None, None)


@pytest.mark.anyio
async def test_applied_replay_audited_chain_green(server_env):
    """already_applied replay leaves an audit row; chain verifies green."""
    m, hm, hmS = await _open_session("manager", confirm=True)
    try:
        await m.structured("reset_demo_data")
        ro = await _report_outage(m)
        v = ro["schedule_version"]
        pr = await m.structured("schedule_propose_replan", {
            "outage_id": ro["outage_id"], "schedule_version": v,
        })
        assert pr["status"] == "proposed"
        ap = await m.structured("schedule_apply_replan", {
            "plan_id": pr["plan_id"], "schedule_version": v,
        })
        assert ap["status"] == "applied"
        ap2 = await m.structured("schedule_apply_replan", {
            "plan_id": pr["plan_id"], "schedule_version": ap["new_version"],
        })
        assert ap2["status"] == "already_applied"

        # replay must have left a result row on the audit trail
        audit = await m.structured("schedule_audit_get", {"limit": 20})
        assert audit["status"] == "ok"
        results = {e["result"] for e in audit["entries"]}
        assert "already_applied" in results, results

        # chain verifies green over everything
        chain = await m.structured("verify_audit_chain")
        assert chain["status"] == "ok"
        assert chain["chain_ok"] is True
    finally:
        await hmS.__aexit__(None, None, None)
        await hm.__aexit__(None, None, None)
