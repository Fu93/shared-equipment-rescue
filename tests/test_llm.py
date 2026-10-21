"""Tests for the dual-mode LLM layer (§7): mode selection, six prohibitions."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from mcp_server import llm  # noqa: E402


def test_mode_default_scripted_without_credentials(monkeypatch):
    for var in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_PROFILE",
                "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "SER_LLM_MODE",
                "AWS_BEARER_TOKEN_BEDROCK"):
        monkeypatch.delenv(var, raising=False)
    assert llm.llm_mode() == "scripted"
    assert llm.bedrock_label() == "Bedrock: off"


def test_mode_env_forces_scripted(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "y")
    monkeypatch.setenv("SER_LLM_MODE", "scripted")
    assert llm.llm_mode() == "scripted"


def test_mode_env_forces_bedrock_with_creds(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "y")
    monkeypatch.setenv("SER_LLM_MODE", "bedrock")
    assert llm.llm_mode() == "bedrock"


def test_mode_auto_with_env_creds(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "y")
    monkeypatch.delenv("SER_LLM_MODE", raising=False)
    assert llm.llm_mode() == "bedrock"


def test_system_prompt_contains_prohibitions():
    sp = llm.SYSTEM_PROMPT
    assert "never invent" in sp
    assert "never override" in sp
    assert "never reveal" in sp


def test_script_overview_no_outage():
    r = {
        "schedule_version": 1,
        "viewer": {"name": "Facility Manager", "user_id": "user-manager", "role": "manager"},
        "bookings": [{"id": f"B{i}" for i in (1,)}],
        "open_outages": [],
    }
    r["bookings"] = [{"id": "B1", "user": "Wang", "user_id": "user-wang"}]
    txt = llm.script_schedule_overview(r)
    assert "1 bookings" in txt and "normally" in txt


def test_script_overview_with_unresolved():
    r = {
        "schedule_version": 3,
        "viewer": {"name": "Facility Manager", "user_id": "user-manager", "role": "manager"},
        "bookings": [],
        "open_outages": [{
            "id": "O1", "equipment": "confocal-a", "equipment_name": "Confocal A",
            "start": "2026-10-20T10:00:00+01:00", "end": "2026-10-20T16:00:00+01:00",
            "affected_booking_ids": ["B2", "B4"],
            "unresolved_booking_ids": ["B2"],
            "resolved": False,
        }],
    }
    txt = llm.script_schedule_overview(r)
    assert "O1" in txt and "B2" in txt and "unresolved" in txt


def test_script_apply_unresolved_includes_would_work_if():
    r = {
        "status": "applied", "plan_id": "P1", "new_version": 3,
        "applied_changes": [{"booking_id": "B4", "to_start": "2026-10-20T16:00:00+01:00",
                             "new_equipment": "confocal-a"}],
        "unresolved": [{
            "booking_id": "B2", "user": "Chen", "reasons": [
                {"code": "original_slot_in_outage"},
                {"code": "deadline_would_need", "at_least": "2026-10-20T12:15:00+01:00"},
            ],
            "earliest_possible": [{
                "equipment_id": "confocal-b", "equipment_name": "Confocal B",
                "status": "available_after_deadline",
                "earliest_start": "2026-10-20T11:15:00+01:00",
                "earliest_finish": "2026-10-20T12:15:00+01:00",
                "blockers": [],
                "would_work_if": [{"code": "deadline_would_need",
                                   "at_least": "2026-10-20T12:15:00+01:00"}],
            }],
        }],
    }
    txt = llm.script_apply_result_narrative(r)
    assert "deadline moves to 12:15" in txt
    assert "B2 could run on Confocal B 11:15" in txt


def test_narrate_falls_back_when_scripted(monkeypatch):
    monkeypatch.setenv("SER_LLM_MODE", "scripted")
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "should-not-be-sent")
    called = []

    def factory():
        called.append(1)
        raise AssertionError("scripted mode must not build a Bedrock client")

    llm.set_client_factory(factory)
    try:
        assert llm.narrate("x", {}, "fallback text") == "fallback text"
        assert called == []
        assert llm.bedrock_label() == "Bedrock: off"
    finally:
        llm.set_client_factory(None)


def test_bearer_token_selects_bedrock(monkeypatch):
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.delenv("SER_LLM_MODE", raising=False)
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "bearer-for-mode-only")
    monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    assert llm.llm_mode() == "bedrock"
    assert llm.bedrock_model_id() == "amazon.nova-lite-v1:0"
    assert llm.bedrock_region() == "us-east-1"
    assert llm.bedrock_label() == "Bedrock: on (amazon.nova-lite-v1:0, us-east-1)"


def test_model_and_region_come_from_env(monkeypatch):
    monkeypatch.setenv("SER_LLM_MODE", "bedrock")
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "bearer-for-mode-only")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    assert llm.bedrock_label() == "Bedrock: on (amazon.nova-lite-v1:0, us-east-1)"


class _StubClient:
    def __init__(self, text="Narrated by the stub.", request_id="req-stub-1", error=None):
        self.text = text
        self.request_id = request_id
        self.error = error
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return {
            "output": {"message": {"content": [{"text": self.text}]}},
            "ResponseMetadata": {"RequestId": self.request_id},
        }


def _init_db(monkeypatch, tmp_path):
    monkeypatch.setenv("SER_DB_PATH", str(tmp_path / "bedrock.db"))
    monkeypatch.delenv("SER_FROZEN_NOW", raising=False)
    from mcp_server.server import initialize_storage
    initialize_storage()


def test_narrate_stubbed_converse_audits_without_token(monkeypatch, tmp_path):
    token = "bearer-secret-do-not-log"
    monkeypatch.setenv("SER_LLM_MODE", "bedrock")
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", token)
    monkeypatch.setenv("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    _init_db(monkeypatch, tmp_path)
    stub = _StubClient()
    llm.set_client_factory(lambda: stub)
    try:
        text = llm.narrate("schedule_overview", {"schedule_version": 1}, "scripted fallback")
    finally:
        llm.set_client_factory(None)
    assert text == "Narrated by the stub."
    assert llm.bedrock_status()["error"] is None
    assert stub.calls and stub.calls[0]["modelId"] == "amazon.nova-lite-v1:0"
    from mcp_server import db as dbm
    rows = dbm.audit_entries(limit=10, tool="bedrock_converse")
    assert len(rows) == 1, rows
    row = rows[0]
    blob = (row["detail"] or "") + (row["detail_json"] or "") + (row["token_hint"] or "")
    assert token not in blob
    assert row["result"] == "ok"
    assert row["at"]
    assert "amazon.nova-lite-v1:0" in blob
    assert "us-east-1" in blob
    assert "req-stub-1" in blob
    assert "latency_ms=" in row["detail"]
    assert "timestamp=" in row["detail"]
    parsed = __import__("json").loads(row["detail_json"])
    assert parsed["request_id"] == "req-stub-1"
    assert isinstance(parsed["latency_ms"], int)
    assert parsed["timestamp"]


def test_narrate_stubbed_failure_falls_back_and_shows_error(monkeypatch, tmp_path):
    token = "bearer-secret-do-not-log"
    monkeypatch.setenv("SER_LLM_MODE", "bedrock")
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", token)
    monkeypatch.setenv("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    _init_db(monkeypatch, tmp_path)
    stub = _StubClient(error=RuntimeError("denied " + token))
    llm.set_client_factory(lambda: stub)
    try:
        text = llm.narrate("schedule_overview", {"schedule_version": 2}, "scripted fallback")
        status = llm.bedrock_status()
    finally:
        llm.set_client_factory(None)
    assert text == "scripted fallback"
    assert status["label"] == "Bedrock: on (amazon.nova-lite-v1:0, us-east-1)"
    assert status["error"]
    assert token not in status["error"]
    assert "denied" in status["error"]
    from mcp_server import db as dbm
    rows = dbm.audit_entries(limit=5, tool="bedrock_converse")
    assert rows and rows[0]["result"] == "error"
    blob = (rows[0]["detail"] or "") + (rows[0]["detail_json"] or "")
    assert token not in blob
    assert "latency_ms=" in rows[0]["detail"]


def test_bedrock_converse_live(monkeypatch, tmp_path):
    """One real Converse call. Skipped unless the bearer token is set.

    Does not print the token. A failure here is a failed call, not a skip.
    """
    import os
    import pytest
    if not (os.environ.get("AWS_BEARER_TOKEN_BEDROCK") or "").strip():
        pytest.skip("AWS_BEARER_TOKEN_BEDROCK is not set")
    token = os.environ["AWS_BEARER_TOKEN_BEDROCK"]
    monkeypatch.setenv("SER_LLM_MODE", "auto")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")
    _init_db(monkeypatch, tmp_path)
    llm.set_client_factory(None)
    fallback = "SCRIPT_FALLBACK_SENTINEL"
    text = llm.narrate(
        "schedule_overview",
        {"schedule_version": 1, "facts": "one booking, no outage"},
        fallback,
    )
    status = llm.bedrock_status()
    assert text and text != fallback, status.get("error")
    assert token not in text
    from mcp_server import db as dbm
    rows = dbm.audit_entries(limit=5, tool="bedrock_converse")
    assert rows and rows[0]["result"] == "ok", status.get("error")
    blob = (rows[0]["detail"] or "") + (rows[0]["detail_json"] or "") + (rows[0]["token_hint"] or "")
    assert token not in blob
    assert "amazon.nova-lite-v1:0" in blob
    assert "us-east-1" in blob
    assert rows[0]["at"]
    assert "latency_ms=" in rows[0]["detail"]
    assert "request_id=" in rows[0]["detail"]
