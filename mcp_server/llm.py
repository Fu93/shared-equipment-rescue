"""LLM narration layer (plan §7): optional Bedrock Converse, scripted fallback.

Six prohibitions (§7.2) — the LLM NEVER:
1. invents bookings/equipment/users/times,
2. overrides the engine's decisions,
3. silently reorders tool-call arguments,
4. claims authority it doesn't have (manager-only writes stay manager-only),
5. reveals another user's masked data,
6. styles itself as the system of record — the DB is.

Four scripted flows (§7.3): schedule_overview, outage_narrative,
apply_result_narrative, unresolved_narrative. Only schedule_overview is
sent to Bedrock, and only from schedule_get, after the engine has decided.
Mode selection: SER_LLM_MODE=scripted never calls Bedrock. auto (default)
and bedrock call Converse only when AWS_BEARER_TOKEN_BEDROCK or standard
AWS credentials are present. A failure returns the scripted sentence.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Callable, Dict, List, Optional

from .constants import DEMO_DATE, DEMO_TZ, UNIT_NAME

log = logging.getLogger("ser.llm")

MAX_TOKENS = 512
MODEL_ID_DEFAULT = "amazon.nova-lite-v1:0"
REGION_DEFAULT = "us-east-1"
SYSTEM_PROMPT = (
    "You are the explanation layer of a facility scheduling tool. "
    "You receive JSON facts from a rule engine and render short friendly narration. "
    "You must never add, remove, or alter any factual field; never invent "
    "bookings, equipment, or times; never override engine decisions; never "
    "reveal data the requesting viewer is not authorized to see. "
    "You do not choose slots, move bookings, or call tools. "
    "Keep answers under 120 words."
)

# Tests inject a fake bedrock-runtime client. Production leaves this None
# so boto3.client builds the real one and reads AWS_BEARER_TOKEN_BEDROCK itself.
_client_factory: Optional[Callable[[], Any]] = None
_last_error: str = ""


# --------------------------------------------------------------------------
# mode selection
# --------------------------------------------------------------------------


def _mode() -> str:
    mode = os.environ.get("SER_LLM_MODE", "auto").lower()
    assert mode in ("auto", "scripted", "bedrock"), f"bad SER_LLM_MODE {mode!r}"
    return mode


def bedrock_model_id() -> str:
    return (os.environ.get("BEDROCK_MODEL_ID") or MODEL_ID_DEFAULT).strip()


def bedrock_region() -> str:
    return (os.environ.get("AWS_REGION") or REGION_DEFAULT).strip()


def _has_aws_credentials() -> bool:
    """Bearer token (boto3 reads it natively) or the standard credential chain."""
    if (os.environ.get("AWS_BEARER_TOKEN_BEDROCK") or "").strip():
        return True
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
    """Resolved mode: 'bedrock' only when configured and credentialed."""
    m = _mode()
    if m == "scripted":
        return "scripted"
    return "bedrock" if _has_aws_credentials() else "scripted"


def bedrock_label() -> str:
    """Exact UI strings: 'Bedrock: off' or 'Bedrock: on (model, region)'."""
    if llm_mode() != "bedrock":
        return "Bedrock: off"
    return f"Bedrock: on ({bedrock_model_id()}, {bedrock_region()})"


def bedrock_status() -> dict:
    """Status for /metrics and the web label. Never includes a credential."""
    on = llm_mode() == "bedrock"
    return {
        "label": bedrock_label(),
        "on": on,
        "model": bedrock_model_id() if on else None,
        "region": bedrock_region() if on else None,
        "error": _last_error or None,
    }


def set_client_factory(factory: Optional[Callable[[], Any]]) -> None:
    """Install a stub bedrock-runtime client. None restores boto3."""
    global _client_factory, _last_error
    _client_factory = factory
    _last_error = ""


def _redact(text: str) -> str:
    """Strip credential material before it reaches a log, audit row, or UI."""
    redacted = text or ""
    for name in (
        "AWS_BEARER_TOKEN_BEDROCK",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_ACCESS_KEY_ID",
    ):
        secret = os.environ.get(name) or ""
        if secret and secret in redacted:
            redacted = redacted.replace(secret, "[redacted]")
    return redacted[:300]


def _make_client():
    if _client_factory is not None:
        return _client_factory()
    import boto3
    # region_name is explicit. The bearer token stays in the environment:
    # boto3's bedrock-runtime client reads AWS_BEARER_TOKEN_BEDROCK itself.
    return boto3.client("bedrock-runtime", region_name=bedrock_region())


def _audit_bedrock(
    *,
    result: str,
    model: str,
    region: str,
    request_id: str,
    latency_ms: int,
    error: str = "",
) -> None:
    """One audit row per Converse attempt. The token is never a field."""
    try:
        from . import db as dbm
    except Exception:
        return
    timestamp = ""
    try:
        timestamp = dbm.now_iso()
    except Exception:
        timestamp = ""
    request_id = _redact(request_id or "")
    error = _redact(error or "")
    detail = (
        f"model={model} region={region} request_id={request_id} "
        f"latency_ms={latency_ms} timestamp={timestamp}"
    )
    if error:
        detail += f" error={error}"
    extras = {
        "model": model,
        "region": region,
        "request_id": request_id,
        "latency_ms": latency_ms,
        "timestamp": timestamp,
    }
    if error:
        extras["error"] = error
    try:
        dj_s = json.dumps(
            {"tool": "bedrock_converse", "result": result, **extras},
            ensure_ascii=False,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        dj_s = "{}"
    try:
        dbm.record_audit_standalone(
            tool="bedrock_converse",
            result=result,
            actor_name="bedrock",
            actor_role="narration",
            detail=_redact(detail)[:500],
            token_hint="-",
            detail_json=dj_s,
        )
    except Exception:
        return


# --------------------------------------------------------------------------
# bedrock converse
# --------------------------------------------------------------------------


def _bedrock_converse(messages: List[Dict[str, Any]]) -> Optional[str]:
    """One Converse call. None means the caller must use the scripted text.

    Failures are stored on bedrock_status()['error'] and written to the audit
    log. They are not swallowed silently.
    """
    global _last_error
    model = bedrock_model_id()
    region = bedrock_region()
    started = time.perf_counter()
    request_id = ""
    try:
        client = _make_client()
        resp = client.converse(
            modelId=model,
            system=[{"text": SYSTEM_PROMPT}],
            messages=messages,
            inferenceConfig={"maxTokens": MAX_TOKENS, "temperature": 0.0},
        )
        request_id = str((resp.get("ResponseMetadata") or {}).get("RequestId") or "")
        parts = resp.get("output", {}).get("message", {}).get("content", []) or []
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
        latency_ms = int((time.perf_counter() - started) * 1000)
        if not text:
            _last_error = "Bedrock returned no text"
            _audit_bedrock(
                result="error", model=model, region=region, request_id=request_id,
                latency_ms=latency_ms, error=_last_error,
            )
            log.warning(
                "Bedrock Converse empty model=%s region=%s request_id=%s latency_ms=%s",
                model, region, request_id, latency_ms,
            )
            return None
        _last_error = ""
        _audit_bedrock(
            result="ok", model=model, region=region, request_id=request_id,
            latency_ms=latency_ms,
        )
        return text
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        _last_error = _redact(f"{type(exc).__name__}: {exc}")
        _audit_bedrock(
            result="error", model=model, region=region, request_id=request_id,
            latency_ms=latency_ms, error=_last_error,
        )
        log.warning(
            "Bedrock Converse failed model=%s region=%s request_id=%s latency_ms=%s error=%s",
            model, region, _redact(request_id), latency_ms, _last_error,
        )
        return None


def _messages(*user_payloads: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One user turn with JSON payloads."""
    body = json.dumps(user_payloads, ensure_ascii=False, default=str)
    return [{"role": "user", "content": [{"text": body}]}]


def narrate(flow: str, facts: Dict[str, Any], fallback: str) -> str:
    """Phrase `fallback` with Converse when Bedrock is on. Never raises.

    The returned string is narration only. Callers must keep using the engine's
    own decisions for anything that changes a booking.
    """
    global _last_error
    if llm_mode() != "bedrock":
        _last_error = ""
        return fallback
    msgs = _messages({"flow": flow, "facts": facts, "scripted": fallback})
    try:
        text = _bedrock_converse(msgs)
    except Exception as exc:
        _last_error = _redact(f"{type(exc).__name__}: {exc}")
        log.warning("Bedrock narration failed: %s", _last_error)
        return fallback
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
