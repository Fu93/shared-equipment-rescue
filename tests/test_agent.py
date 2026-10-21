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
    assert sorted(spec["toolSpec"]["name"] for spec in cfg["tools"]) == names


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
    assert seen["names"] == sorted(tool["name"] for tool in CATALOG)


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
    assert "confirm" in sent["system"][0]["text"].lower()
    assert "bearer-secret-do-not-log" not in json.dumps(sent)
