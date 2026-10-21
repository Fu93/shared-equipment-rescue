"""Stubbed Bedrock tool loop: the model proposes, the policy decides."""

import json

import pytest

from mcp_server.agent import (
    catalog_from_fastmcp,
    run_agent_loop,
    tool_config_from_catalog,
)
from mcp_server.server import mcp


CATALOG = catalog_from_fastmcp(mcp)


class _Actor:
    user_id = "user-manager"
    name = "Facility Manager"
    role = "manager"


def _tool(name, arguments, tool_id="t1"):
    return {
        "output": {
            "message": {
                "content": [{
                    "toolUse": {
                        "toolUseId": tool_id,
                        "name": name,
                        "input": arguments,
                    }
                }]
            }
        }
    }


def _text(text):
    return {"output": {"message": {"content": [{"text": text}]}}}


def test_catalog_is_the_live_registry():
    names = sorted(tool["name"] for tool in CATALOG)
    assert names == [
        "debug_confirm",
        "equipment_report_outage",
        "reset_demo_data",
        "schedule_apply_replan",
        "schedule_audit_get",
        "schedule_get",
        "schedule_propose_replan",
        "verify_audit_chain",
    ]
    apply = next(tool for tool in CATALOG if tool["name"] == "schedule_apply_replan")
    assert set(apply["input_schema"]["properties"]) == {"plan_id", "schedule_version"}
    assert "confirm" not in apply["input_schema"]["properties"]
    cfg = tool_config_from_catalog(CATALOG)
    assert sorted(spec["toolSpec"]["name"] for spec in cfg["tools"]) == [
        "equipment_report_outage",
        "schedule_apply_replan",
        "schedule_audit_get",
        "schedule_get",
        "schedule_propose_replan",
    ]


def test_correct_tool_chain_then_narration():
    seen = {}
    script = [
        _tool("equipment_report_outage", {
            "equipment_id": "confocal-a",
            "start": "2026-10-20T10:00:00+01:00",
            "end": "2026-10-20T16:00:00+01:00",
        }, "t1"),
        _tool("schedule_propose_replan", {"outage_id": "O1", "schedule_version": 2}, "t2"),
        _text("Confocal A is down until 16:00. A replan is ready for you to confirm."),
    ]

    def converse(messages, tool_config):
        seen["names"] = sorted(spec["toolSpec"]["name"] for spec in tool_config["tools"])
        return script.pop(0)

    executed = []

    def execute(name, arguments):
        executed.append(name)
        if name == "equipment_report_outage":
            return {"status": "recorded", "outage_id": "O1", "schedule_version": 2}
        return {"status": "proposed", "plan_id": "P1"}

    result = run_agent_loop(
        "Alexa, Confocal A is down until 4pm, please sort out the bookings",
        converse=converse, execute=execute, catalog=CATALOG, actor=_Actor(),
    )
    assert result["ok"] is True
    assert result["applied"] is False
    assert result["stopped"] is None
    assert executed == ["equipment_report_outage", "schedule_propose_replan"]
    assert "confirm" in result["text"].lower()
    assert seen["names"] == [
        "equipment_report_outage",
        "schedule_apply_replan",
        "schedule_audit_get",
        "schedule_get",
        "schedule_propose_replan",
    ]


def test_unknown_tool_is_rejected_and_not_executed():
    def converse(messages, tool_config):
        return _tool("delete_everything", {})

    def execute(name, arguments):
        raise AssertionError("execute must not be called")

    result = run_agent_loop(
        "wipe it", converse=converse, execute=execute, catalog=CATALOG, actor=_Actor(),
    )
    assert result["stopped"] == "unknown_tool"
    assert result["executed"] == []
    assert "Nothing was called" in result["error"]


def test_apply_without_confirmation_stops_and_does_not_apply():
    def converse(messages, tool_config):
        return _tool("schedule_apply_replan", {"plan_id": "P1", "schedule_version": 2})

    executed = []

    def execute(name, arguments):
        executed.append((name, arguments))
        return {"status": "not_confirmed", "message": "no confirmation received"}

    result = run_agent_loop(
        "apply the plan", converse=converse, execute=execute, catalog=CATALOG, actor=_Actor(),
    )
    assert executed == [("schedule_apply_replan", {"plan_id": "P1", "schedule_version": 2})]
    assert result["applied"] is False
    assert result["stopped"] == "not_confirmed"
    assert "Nothing was applied" in result["message"]


def test_confirm_argument_is_rejected():
    def converse(messages, tool_config):
        return _tool("schedule_apply_replan", {
            "plan_id": "P1", "schedule_version": True, "confirm": True,
        })

    def execute(name, arguments):
        raise AssertionError("execute must not be called")

    result = run_agent_loop(
        "apply it", converse=converse, execute=execute, catalog=CATALOG, actor=_Actor(),
    )
    assert result["stopped"] == "bad_arguments"
    assert result["executed"] == []
    assert "Nothing was called" in result["error"]


def test_step_cap_stops_at_four_executions():
    calls = {"n": 0}

    def converse(messages, tool_config):
        calls["n"] += 1
        return _tool("schedule_get", {"unit_id": "lab-a", "date": "2026-10-20"}, f"t{calls['n']}")

    executed = []

    def execute(name, arguments):
        executed.append(name)
        return {"status": "ok", "schedule_version": 1}

    result = run_agent_loop(
        "what is on today", converse=converse, execute=execute, catalog=CATALOG, actor=_Actor(),
    )
    assert executed == ["schedule_get"] * 4
    assert calls["n"] == 4
    assert result["stopped"] == "step_cap"
    assert "4" in result["message"]


def test_overflow_in_one_turn_executes_nothing():
    def converse(messages, tool_config):
        content = []
        for i in range(5):
            content.append({
                "toolUse": {
                    "toolUseId": f"t{i}",
                    "name": "schedule_get",
                    "input": {},
                }
            })
        return {"output": {"message": {"content": content}}}

    def execute(name, arguments):
        raise AssertionError("execute must not be called")

    result = run_agent_loop(
        "read it five times", converse=converse, execute=execute, catalog=CATALOG,
    )
    assert result["stopped"] == "overflow"
    assert result["executed"] == []
    assert "Nothing from that reply was called" in result["error"]


def test_proposals_and_results_are_audited(monkeypatch, tmp_path):
    monkeypatch.setenv("SER_DB_PATH", str(tmp_path / "agent.db"))
    monkeypatch.delenv("SER_FROZEN_NOW", raising=False)
    from mcp_server.server import initialize_storage
    initialize_storage()

    def converse(messages, tool_config):
        return _tool("schedule_get", {})

    def execute(name, arguments):
        return {"status": "ok", "message": "six bookings"}

    run_agent_loop("show the day", converse=converse, execute=execute, catalog=CATALOG, actor=_Actor())
    from mcp_server import db as dbm
    rows = dbm.audit_entries(limit=10, tool="agent_tool_call")
    phases = []
    for row in rows:
        blob = (row["detail"] or "") + (row["detail_json"] or "") + (row["token_hint"] or "")
        assert "AWS_BEARER_TOKEN_BEDROCK" not in blob
        assert row["actor_id"] == "user-manager"
        assert row["token_hint"] == "-"
        phases.append(json.loads(row["detail_json"])["phase"])
    assert "proposed" in phases
    assert "result" in phases


def test_agent_step_is_off_when_scripted(monkeypatch, tmp_path):
    monkeypatch.setenv("SER_DB_PATH", str(tmp_path / "agent-http.db"))
    import asyncio
    import httpx
    from mcp_server.server import build_app

    async def go():
        app = build_app()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            denied = await client.post("/agent/step", json={
                "messages": [{"role": "user", "content": [{"text": "hi"}]}],
                "rounds": 0, "executions": 0,
            })
            assert denied.status_code == 401
            ok = await client.post("/agent/step", headers={"authorization": "Bearer tok-manager"}, json={
                "messages": [{"role": "user", "content": [{"text": "hi"}]}],
                "rounds": 0, "executions": 0,
            })
            assert ok.status_code == 200, ok.text
            body = ok.json()
            assert body["bedrock"] is False
            assert body["label"] == "Bedrock: off"

    asyncio.run(go())


def test_agent_converse_sends_tool_config(monkeypatch, tmp_path):
    monkeypatch.setenv("SER_DB_PATH", str(tmp_path / "agent-converse.db"))
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "bearer-secret-do-not-log")
    from mcp_server.server import initialize_storage
    initialize_storage()
    from mcp_server import llm

    class Stub:
        def __init__(self):
            self.calls = []

        def converse(self, **kwargs):
            self.calls.append(kwargs)
            return {
                "output": {"message": {"content": [{"text": "Ready for you to confirm."}]}},
                "ResponseMetadata": {"RequestId": "req-agent-1"},
            }

    stub = Stub()
    llm.set_client_factory(lambda: stub)
    try:
        out = llm.agent_converse(
            [{"role": "user", "content": [{"text": "Alexa, Confocal A is down until 4pm"}]}],
            tool_config_from_catalog(CATALOG),
        )
    finally:
        llm.set_client_factory(None)
    assert out["ok"] is True
    sent = stub.calls[0]
    assert "toolConfig" in sent
    assert "schedule_apply_replan" in json.dumps(sent["toolConfig"])
    assert "reset_demo_data" not in json.dumps(sent["toolConfig"])
    assert "confirm" in sent["system"][0]["text"].lower()
    assert "bearer-secret-do-not-log" not in json.dumps(sent)


def test_reset_is_not_offered_and_is_refused():
    cfg = tool_config_from_catalog(CATALOG)
    names = [spec["toolSpec"]["name"] for spec in cfg["tools"]]
    assert "reset_demo_data" not in names
    assert "debug_confirm" not in names
    assert "verify_audit_chain" not in names
    assert "schedule_apply_replan" in names

    def converse(messages, tool_config):
        offered = [spec["toolSpec"]["name"] for spec in tool_config["tools"]]
        assert "reset_demo_data" not in offered
        return _tool("reset_demo_data", {})

    def execute(name, arguments):
        raise AssertionError("execute must not be called")

    result = run_agent_loop(
        "reset the demo", converse=converse, execute=execute, catalog=CATALOG, actor=_Actor(),
    )
    assert result["stopped"] == "not_allowed"
    assert result["executed"] == []
    assert "Nothing was called" in result["error"]


def _bedrock_http(monkeypatch, tmp_path, name):
    monkeypatch.setenv("SER_DB_PATH", str(tmp_path / name))
    monkeypatch.setenv("SER_LLM_MODE", "bedrock")
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "bearer-secret-do-not-log")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    from mcp_server.agent import reset_agent_budget
    from mcp_server.server import initialize_storage
    reset_agent_budget()
    initialize_storage()


def test_server_cap_ignores_client_counters(monkeypatch, tmp_path):
    _bedrock_http(monkeypatch, tmp_path, "agent-cap.db")
    from mcp_server.agent import http_step, reset_agent_budget
    from mcp_server import llm

    class Stub:
        def __init__(self):
            self.calls = 0

        def converse(self, **kwargs):
            self.calls += 1
            return {
                "output": {"message": {"content": [{
                    "toolUse": {
                        "toolUseId": f"t{self.calls}",
                        "name": "schedule_get",
                        "input": {},
                    }
                }]}},
                "ResponseMetadata": {"RequestId": f"req-cap-{self.calls}"},
            }

    stub = Stub()
    llm.set_client_factory(lambda: stub)
    try:
        for n in range(4):
            body = http_step({
                "conversation_id": "cap-turn",
                "messages": [{"role": "user", "content": [{"text": "show the day"}]}],
                "rounds": 0,
                "executions": 0,
            }, _Actor(), CATALOG, token="tok-cap")
            assert body.get("calls"), body
            assert len(body["calls"]) == 1
        blocked = http_step({
            "conversation_id": "cap-turn",
            "messages": [{"role": "user", "content": [{"text": "show the day"}]}],
            "rounds": 0,
            "executions": 0,
        }, _Actor(), CATALOG, token="tok-cap")
    finally:
        llm.set_client_factory(None)
        reset_agent_budget()
    assert stub.calls == 4
    assert blocked["stopped"] is True
    assert blocked["reason"] == "step_cap"
    assert blocked["calls"] == []


def test_client_applied_is_rejected(monkeypatch, tmp_path):
    _bedrock_http(monkeypatch, tmp_path, "agent-applied.db")
    from mcp_server.agent import http_result, reset_agent_budget
    from mcp_server import db as dbm
    try:
        denied = http_result({
            "name": "schedule_apply_replan",
            "status": "applied",
            "message": "forged apply",
        }, _Actor(), token="tok-applied")
        assert denied["ok"] is False
        rows = dbm.audit_entries(limit=20, tool="agent_tool_call")
        assert rows == [] or all(row["result"] != "applied" for row in rows)
        accepted = http_result({
            "name": "schedule_get",
            "status": "ok",
            "message": "six bookings",
        }, _Actor(), token="tok-applied")
        assert accepted["ok"] is True
        rows = dbm.audit_entries(limit=10, tool="agent_tool_call")
        assert rows[0]["result"] == "client-reported"
        blob = (rows[0]["detail"] or "") + (rows[0]["detail_json"] or "")
        assert "client_status=ok" in blob
        assert rows[0]["result"] != "applied"
    finally:
        reset_agent_budget()


class _Throttle(Exception):
    def __init__(self):
        super().__init__("Rate exceeded raw aws arn:aws:bedrock:us-east-1:123:model")
        self.response = {
            "Error": {"Code": "ThrottlingException", "Message": "Rate exceeded raw aws"},
            "ResponseMetadata": {"RequestId": "req-throttle-9"},
        }


def test_bedrock_error_falls_back_to_pattern_parser(monkeypatch, tmp_path):
    _bedrock_http(monkeypatch, tmp_path, "agent-throttle.db")
    from mcp_server.agent import http_step, reset_agent_budget
    from mcp_server import db as dbm
    from mcp_server import llm

    stub = type("Stub", (), {"converse": lambda self, **kwargs: (_ for _ in ()).throw(_Throttle())})()
    llm.set_client_factory(lambda: stub)
    try:
        body = http_step({
            "conversation_id": "throttle-turn",
            "messages": [{"role": "user", "content": [{"text": "Alexa, Confocal A is down until 4pm"}]}],
            "rounds": 0,
            "executions": 0,
        }, _Actor(), CATALOG, token="tok-throttle")
    finally:
        llm.set_client_factory(None)
        reset_agent_budget()
    assert body["fallback"] is True
    assert body["label"] == "Fallback: pattern parser (Bedrock error: ThrottlingException)"
    assert body["message"] == "Bedrock is busy right now."
    packed = json.dumps(body)
    assert "Rate exceeded" not in packed
    assert "arn:aws" not in packed
    rows = dbm.audit_entries(limit=5, tool="bedrock_converse")
    assert rows and rows[0]["result"] == "error"
    blob = (rows[0]["detail"] or "") + (rows[0]["detail_json"] or "")
    assert "req-throttle-9" in blob
    assert "ThrottlingException" in blob
    assert "Rate exceeded" not in blob
    assert "arn:aws" not in blob
    assert "bearer-secret-do-not-log" not in blob


def test_rate_limit_per_token(monkeypatch, tmp_path):
    _bedrock_http(monkeypatch, tmp_path, "agent-rate.db")
    from mcp_server.agent import RATE_LIMIT_MAX, http_step, reset_agent_budget
    from mcp_server import llm

    class Stub:
        def __init__(self):
            self.calls = 0

        def converse(self, **kwargs):
            self.calls += 1
            return {
                "output": {"message": {"content": [{"text": "ok"}]}},
                "ResponseMetadata": {"RequestId": "req-rate"},
            }

    stub = Stub()
    llm.set_client_factory(lambda: stub)
    try:
        last = None
        for _n in range(RATE_LIMIT_MAX + 1):
            last = http_step({
                "conversation_id": "rate-turn",
                "messages": [{"role": "user", "content": [{"text": "hi"}]}],
            }, _Actor(), CATALOG, token="tok-rate")
        assert last["http_status"] == 429
        assert last["reason"] == "rate_limited"
        assert last["calls"] == []
        # One conversation stays under the new-conversation cap, so the
        # 31st denial is the per-token window. The step cap stops the model
        # after four rounds; the later requests still spend the window.
        assert stub.calls == 4
    finally:
        llm.set_client_factory(None)
        reset_agent_budget()


def test_new_conversations_are_capped_and_expire(monkeypatch, tmp_path):
    _bedrock_http(monkeypatch, tmp_path, "agent-new-conv.db")
    import mcp_server.agent as agent_mod
    from mcp_server.agent import MAX_NEW_CONVERSATIONS, http_step, reset_agent_budget
    from mcp_server import llm

    clock = {"now": 1_000_000.0}
    monkeypatch.setattr(agent_mod.time, "monotonic", lambda: clock["now"])

    class Stub:
        def __init__(self):
            self.calls = 0

        def converse(self, **kwargs):
            self.calls += 1
            return {
                "output": {"message": {"content": [{"text": "ok"}]}},
                "ResponseMetadata": {"RequestId": "req-new"},
            }

    stub = Stub()
    llm.set_client_factory(lambda: stub)
    try:
        for n in range(MAX_NEW_CONVERSATIONS):
            body = http_step({
                "conversation_id": f"new-{n}",
                "messages": [{"role": "user", "content": [{"text": "hi"}]}],
            }, _Actor(), CATALOG, token="tok-new")
            assert body.get("reason") != "conversation_cap", body
        assert stub.calls == MAX_NEW_CONVERSATIONS
        again = http_step({
            "conversation_id": "new-0",
            "messages": [{"role": "user", "content": [{"text": "hi"}]}],
        }, _Actor(), CATALOG, token="tok-new")
        assert again.get("reason") != "conversation_cap", again
        assert stub.calls == MAX_NEW_CONVERSATIONS + 1
        blocked = http_step({
            "conversation_id": "new-extra",
            "messages": [{"role": "user", "content": [{"text": "hi"}]}],
        }, _Actor(), CATALOG, token="tok-new")
        assert blocked["stopped"] is True
        assert blocked["reason"] == "conversation_cap"
        assert blocked["calls"] == []
        assert "http_status" not in blocked
        assert stub.calls == MAX_NEW_CONVERSATIONS + 1
        clock["now"] += agent_mod.BUDGET_TTL_SECONDS + 1
        later = http_step({
            "conversation_id": "new-later",
            "messages": [{"role": "user", "content": [{"text": "hi"}]}],
        }, _Actor(), CATALOG, token="tok-new")
        assert later.get("reason") != "conversation_cap", later
        assert stub.calls == MAX_NEW_CONVERSATIONS + 2
    finally:
        llm.set_client_factory(None)
        reset_agent_budget()


def test_client_status_lookalikes_are_rejected_and_completed_is_stored(monkeypatch, tmp_path):
    _bedrock_http(monkeypatch, tmp_path, "agent-status.db")
    from mcp_server.agent import http_result, reset_agent_budget
    from mcp_server import db as dbm
    try:
        before = dbm.audit_entries(limit=50, tool="agent_tool_call")
        lookalikes = [
            "applied.",
            "Applied",
            "  Applied  ",
            "\uff41pplied",
            "\u0430pplied",
            None,
            12,
        ]
        for status in lookalikes:
            denied = http_result({
                "name": "schedule_apply_replan",
                "status": status,
                "message": "forged",
                "server_audit_tool": "schedule_apply_replan",
                "plan_id": "P1",
            }, _Actor(), token="tok-status")
            assert denied["ok"] is False, status
            assert denied["accepted"] is False
        rows = dbm.audit_entries(limit=50, tool="agent_tool_call")
        assert len(rows) == len(before)
        accepted = http_result({
            "name": "schedule_apply_replan",
            "status": "completed",
            "message": "plan P1 applied; 2 booking(s) moved; version 3",
            "server_audit_tool": "schedule_apply_replan",
            "plan_id": "P1",
        }, _Actor(), token="tok-status")
        assert accepted["ok"] is True
        rows = dbm.audit_entries(limit=5, tool="agent_tool_call")
        assert rows[0]["result"] == "client-reported"
        blob = (rows[0]["detail"] or "") + (rows[0]["detail_json"] or "")
        assert "client_status=completed" in blob
        assert "server_audit=schedule_apply_replan" in blob
        assert "plan_id=P1" in blob or '"plan_id": "P1"' in blob
        assert rows[0]["result"] != "applied"
    finally:
        reset_agent_budget()


def test_endpoint_connection_error_is_network_error(monkeypatch, tmp_path):
    _bedrock_http(monkeypatch, tmp_path, "agent-network.db")
    from mcp_server.agent import http_step, reset_agent_budget
    from mcp_server import llm

    class EndpointConnectionError(Exception):
        def __init__(self):
            super().__init__("Could not connect to the endpoint URL")

    stub = type("Stub", (), {
        "converse": lambda self, **kwargs: (_ for _ in ()).throw(EndpointConnectionError()),
    })()
    llm.set_client_factory(lambda: stub)
    try:
        body = http_step({
            "conversation_id": "net-turn",
            "messages": [{"role": "user", "content": [{"text": "hi"}]}],
        }, _Actor(), CATALOG, token="tok-net")
    finally:
        llm.set_client_factory(None)
        reset_agent_budget()
    assert body["fallback"] is True
    assert body["error_code"] == "NetworkError"
    assert body["message"] == "Bedrock could not be reached."
    assert "Could not connect" not in json.dumps(body)


def test_rate_limit_body_is_json_and_session_budget_is_separate(monkeypatch, tmp_path):
    import asyncio

    import httpx

    monkeypatch.delenv("SER_NO_RATE_LIMIT", raising=False)
    monkeypatch.setenv("SER_DB_PATH", str(tmp_path / "rate-body.db"))
    monkeypatch.setenv("SER_LLM_MODE", "scripted")
    from mcp_server.server import (
        TransportGuardMiddleware,
        _RATE_LIMIT,
        _SESSION_RATE,
        initialize_storage,
    )

    initialize_storage()
    _RATE_LIMIT.tokens.clear()
    _RATE_LIMIT.updated.clear()
    _SESSION_RATE.tokens.clear()
    _SESSION_RATE.updated.clear()

    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    app = TransportGuardMiddleware(inner)

    async def go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            metrics = [(await client.get("/metrics")).status_code for _ in range(20)]
            first = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
            flooded = [
                await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
                for _ in range(24)
            ]
            return metrics, first, flooded

    try:
        metrics, first, flooded = asyncio.run(go())
    finally:
        _RATE_LIMIT.tokens.clear()
        _RATE_LIMIT.updated.clear()
        _SESSION_RATE.tokens.clear()
        _SESSION_RATE.updated.clear()
    assert metrics == [200] * 20, metrics
    assert first.status_code != 429, first.text
    denied = [item for item in flooded if item.status_code == 429]
    assert denied, [item.status_code for item in flooded]
    body = denied[0].json()
    assert body["jsonrpc"] == "2.0"
    assert body["error"]["code"] == -32002
    assert "rate limit exceeded" in body["error"]["message"]
    raw = denied[0].text
    assert raw.count("{") == raw.count("}")


def test_converse_timeout_returns_fallback(monkeypatch, tmp_path):
    import asyncio
    import time

    import httpx

    monkeypatch.setenv("SER_DB_PATH", str(tmp_path / "agent-timeout.db"))
    monkeypatch.setenv("SER_LLM_MODE", "bedrock")
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "bearer-secret-do-not-log")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    from mcp_server import llm
    from mcp_server.agent import reset_agent_budget
    from mcp_server.server import build_app

    monkeypatch.setattr(llm, "CONVERSE_TIMEOUT_SECONDS", 0.2)
    reset_agent_budget()

    class Slow:
        def converse(self, **kwargs):
            time.sleep(1.0)
            return {
                "output": {"message": {"content": [{"text": "too late"}]}},
                "ResponseMetadata": {"RequestId": "req-slow"},
            }

    llm.set_client_factory(lambda: Slow())

    async def go():
        app = build_app()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            res = await client.post("/agent/step", headers={"authorization": "Bearer tok-manager"}, json={
                "conversation_id": "slow-turn",
                "messages": [{"role": "user", "content": [{"text": "hi"}]}],
            })
            return res

    try:
        res = asyncio.run(go())
        # Let the worker thread finish its sleep before the env patch is undone.
        time.sleep(1.1)
    finally:
        llm.set_client_factory(None)
        reset_agent_budget()
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["fallback"] is True
    assert body["label"] == "Fallback: pattern parser (Bedrock error: Timeout)"
    assert body["message"] == "Bedrock took too long."
    assert "too late" not in res.text
    from mcp_server import db as dbm
    rows = dbm.audit_entries(limit=20, tool="bedrock_converse")
    assert rows
    assert all(row["result"] != "ok" for row in rows)
    blob = " ".join((row["detail"] or "") + (row["detail_json"] or "") for row in rows)
    assert "Timeout" in blob
    assert "bearer-secret-do-not-log" not in blob
