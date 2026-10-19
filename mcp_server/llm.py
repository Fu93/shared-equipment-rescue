"""LLM narration layer (plan §7): optional Bedrock Converse, scripted fallback.

Six prohibitions (§7.2) — the LLM NEVER:
1. invents bookings/equipment/users/times,
2. overrides the engine's decisions,
3. silently reorders tool-call arguments,
4. claims authority it doesn't have (manager-only writes stay manager-only),
5. reveals another user's masked data,
6. styles itself as the system of record — the DB is.

Four scripted flows (§7.3) when no AWS credentials: schedule_overview,
outage_narrative, apply_result_narrative, unresolved_narrative.
Mode selection (§7.4): SER_LLM_MODE=auto (default) → bedrock if credentials
+ non-stub check succeed, else scripted; SER_LLM_MODE=scripted|bedrock force.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from .constants import DEMO_DATE, DEMO_TZ, UNIT_NAME

MAX_TOKENS = 512
MODEL_ID_DEFAULT = "anthropic.claude-3-5-haiku-20241022-v1:0"
SYSTEM_PROMPT = (
    "You are the explanation layer of a facility scheduling tool. "
    "You receive JSON facts from a rule engine and render short friendly narration. "
    "You must never add, remove, or alter any factual field; never invent "
    "bookings, equipment, or times; never override engine decisions; never "
    "reveal data the requesting viewer is not authorized to see. "
    "Keep answers under 120 words."
)


# --------------------------------------------------------------------------
# mode selection
# --------------------------------------------------------------------------


def _mode() -> str:
    mode = os.environ.get("SER_LLM_MODE", "auto").lower()
    assert mode in ("auto", "scripted", "bedrock"), f"bad SER_LLM_MODE {mode!r}"
    return mode


def _has_aws_credentials() -> bool:
    """Non-stub credential check per §7.4: env chain or profile presence."""
    if os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY"):
        return True
    if os.environ.get("AWS_PROFILE"):
        # treat existing shared credentials file as credentials
        home = os.environ.get("USERPROFILE") or os.environ.get("HOME") or ""
        candidates = [
            os.path.join(home, ".aws", "credentials"),
            os.path.join(home, ".aws", "config"),
        ]
        return any(os.path.exists(p) for p in candidates)
    if os.environ.get("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI"):
        return True
    return False


def llm_mode() -> str:
    """Resolved mode: 'bedrock' only when configured & credentialed."""
    m = _mode()
    if m == "scripted":
        return "scripted"
    if m == "bedrock":
        return "bedrock" if _has_aws_credentials() else "scripted"
    return "bedrock" if _has_aws_credentials() else "scripted"


# --------------------------------------------------------------------------
# bedrock converse
# --------------------------------------------------------------------------


def _bedrock_converse(messages: List[Dict[str, Any]]) -> Optional[str]:
    """Single converse call. Returns None on any failure (caller falls back)."""
    try:
        import boto3
    except ImportError:
        return None
    try:
        client = boto3.client("bedrock-runtime")
        resp = client.converse(
            modelId=os.environ.get("SER_BEDROCK_MODEL", MODEL_ID_DEFAULT),
            system=[{"text": SYSTEM_PROMPT}],
            messages=messages,
            inferenceConfig={"maxTokens": MAX_TOKENS, "temperature": 0.0},
        )
        parts = resp.get("output", {}).get("message", {}).get("content", [])
        text = "".join(p.get("text", "") for p in parts).strip()
        return text or None
    except Exception:
        return None


def _messages(*user_payloads: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One user turn with JSON payloads."""
    body = json.dumps(user_payloads, ensure_ascii=False, default=str)
    return [{"role": "user", "content": [{"text": body}]}]


def narrate(flow: str, facts: Dict[str, Any], fallback: str) -> str:
    """Public entry: try bedrock when resolved mode allows; else fallback."""
    if llm_mode() != "bedrock":
        return fallback
    msgs = _messages({"flow": flow, "facts": facts})
    text = _bedrock_converse(msgs)
    return text if text else fallback


# --------------------------------------------------------------------------
# scripted flows (§7.3) — deterministic, from facts only
# --------------------------------------------------------------------------


def _fmt_hhmm(iso: str) -> str:
    return iso[11:16]


def script_schedule_overview(result: Dict[str, Any]) -> str:
    bookings = result.get("bookings", [])
    open_outages = result.get("open_outages", [])
    v = result["schedule_version"]
    who = result["viewer"]["name"]
    head = (
        f"{who}, {UNIT_NAME} has {len(bookings)} bookings on {DEMO_DATE} "
        f"({DEMO_TZ}), schedule version {v}."
    )
    if not open_outages:
        return head + " Everything is running normally."
    o = open_outages[0]
    aff = o["affected_booking_ids"]
    unres = o.get("unresolved_booking_ids", [])
    tail = (
        f" Outage {o['id']} hits {o['equipment_name']} "
        f"{_fmt_hhmm(o['start'])}–{_fmt_hhmm(o['end'])}: {len(aff)} booking(s) "
        f"affected ({', '.join(aff)})"
    )
    if unres:
        tail += f"; {len(unres)} still unresolved ({', '.join(unres)})."
    else:
        tail += ". A replan is proposed — review and apply it."
    return head + tail


def script_outage_narrative(result: Dict[str, Any]) -> str:
    if result["status"] != "recorded":
        return result["message"]
    e = result["equipment"]
    aff = result["affected_bookings"]
    ids = ", ".join(b["id"] for b in aff) if aff else "none"
    return (
        f"Outage {result['outage_id']} recorded on {e['name']} "
        f"({result['schedule_version'] is not None and 'version ' + str(result['schedule_version']) or ''}). "
        f"Affected bookings now blocked: {ids}. "
        "Next: propose a replan and apply it after explicit confirmation."
    )


def script_apply_result_narrative(result: Dict[str, Any]) -> str:
    st = result["status"]
    if st == "applied":
        ids = ", ".join(
            f"{c['booking_id']}→{_fmt_hhmm(c['to_start'])} on {c['new_equipment']}"
            for c in result["applied_changes"]
        )
        unresolved_txt = script_unresolved_narrative(result["unresolved"])
        tail = ""
        if result["unresolved"]:
            tail = f" {unresolved_txt}"
        return (
            f"Plan {result['plan_id']} applied. Moves: {ids}. "
            f"Schedule is now version {result['new_version']}." + tail
        )
    if st == "not_confirmed":
        return (
            "Apply cancelled — no confirmation received and nothing changed. "
            "The plan stays proposed so you can confirm again later."
        )
    if st == "already_applied":
        return f"Plan {result['plan_id']} was already applied; nothing further changed."
    if st == "plan_stale":
        return (
            "This plan is stale because the schedule moved on since it was built. "
            "Propose again with the current version, then confirm."
        )
    return result.get("message", st)


def script_unresolved_narrative(unresolved: List[Dict[str, Any]]) -> str:
    lines = []
    for u in unresolved:
        eps = u.get("earliest_possible", [])
        best = None
        for ep in eps:
            if ep["status"] == "available_after_deadline":
                wwi = ep.get("would_work_if", [])
                at_least = next(
                    (r.get("at_least") for r in wwi if r.get("code") == "deadline_would_need"),
                    None,
                )
                if at_least:
                    best = (
                        f"{u['booking_id']} could run on {ep['equipment_name']} "
                        f"{_fmt_hhmm(ep['earliest_start'])}–{_fmt_hhmm(ep['earliest_finish'])}, "
                        f"but only if the deadline moves to {_fmt_hhmm(at_least)}."
                    )
                break
        codes = "; ".join(r["code"] for r in u["reasons"])
        lines.append(
            f"{u['booking_id']} ({u['user']}): {codes}." + (f" {best}" if best else "")
        )
    return " ".join(lines) if lines else "Nothing unresolved."
