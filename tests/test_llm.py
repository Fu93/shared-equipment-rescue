"""Tests for the dual-mode LLM layer (§7): mode selection, six prohibitions."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from mcp_server import llm  # noqa: E402


def test_mode_default_scripted_without_credentials(monkeypatch):
    for var in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_PROFILE",
                "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "SER_LLM_MODE"):
        monkeypatch.delenv(var, raising=False)
    assert llm.llm_mode() == "scripted"


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
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    fallback = "fallback text"
    assert llm.narrate("x", {}, fallback) == fallback


def test_narrate_bedrock_mode_graceful_failure(monkeypatch):
    """With bedrock mode + bogus creds, converse fails → fallback returned."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "bogus")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "bogus")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "bogus")
    monkeypatch.setenv("SER_LLM_MODE", "bedrock")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    fallback = "fallback text"
    assert llm.narrate("x", {}, fallback) == fallback
