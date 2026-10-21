"""LLM narration layer (plan §7): optional Bedrock Converse, scripted fallback.

Six prohibitions (§7.2) — the LLM NEVER:
1. invents bookings/equipment/users/times,
2. overrides the engine's decisions,
3. silently reorders tool-call arguments,
4. claims authority it doesn't have (manager-only writes stay manager-only),
5. reveals another user's masked data,
6. styles itself as the system of record — the DB is.

Four scripted flows (§7.3): schedule_overview, outage_narrative,
apply_result_narrative, unresolved_narrative. schedule_get returns the
scripted overview on a board refresh. It calls Bedrock only when the request
sends x-ser-narrate: 1, after the engine has decided, and only to rephrase
that sentence. A separate agent_converse path proposes MCP tool calls for the
simulated Alexa+ page, once per user turn. That path is bounded and
fail-closed in mcp_server.agent. The model still does not choose slots, move
bookings, or confirm an apply. Mode selection: SER_LLM_MODE=scripted never
calls Bedrock. auto (default) and bedrock call Converse only when
AWS_BEARER_TOKEN_BEDROCK or standard AWS credentials are present. A narration
failure returns the scripted sentence. A failed user turn falls back to the
pattern parser with a short error.
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
AGENT_SYSTEM_PROMPT = (
    "You are Alexa, the voice of a facility scheduling assistant. "
    "You may call only the tools in the tool list. "
    "You do not choose slots, move bookings, invent facts, or confirm an apply. "
    "The scheduling engine decides every move. "
    "schedule_apply_replan waits for a human Confirm click and you must not "
    "claim it has been confirmed. "
    "Narrate only facts that tool results contain. "
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
    global _client_factory, _last_error, _cached_client, _cached_region
    _client_factory = factory
    _last_error = ""
    if factory is None:
        _cached_client = None
        _cached_region = None


# One client per process. Building it probes the AWS credential chain, which
# spends about two seconds on EC2 metadata when nothing else is configured.
_cached_client: Any = None
_cached_region: str = ""
CONVERSE_TIMEOUT_SECONDS = 20


def disable_ec2_metadata_for_bearer() -> None:
    """A bearer token is the credential. Skip the EC2 metadata probe."""
    if (os.environ.get("AWS_BEARER_TOKEN_BEDROCK") or "").strip():
        os.environ["AWS_EC2_METADATA_DISABLED"] = "true"


def warm_client() -> None:
    """Create the cached client once at startup when this process will call Bedrock."""
    if llm_mode() != "bedrock":
        return
    try:
        _make_client()
    except Exception as exc:
        global _last_error
        code, _request_id, short = _failure_details(exc)
        _last_error = short
        log.warning("Bedrock client setup failed code=%s", code)


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
    """Return the stub, or the one cached bedrock-runtime client for this region."""
    global _cached_client, _cached_region
    if _client_factory is not None:
        return _client_factory()
    disable_ec2_metadata_for_bearer()
    region = bedrock_region()
    if _cached_client is not None and _cached_region == region:
        return _cached_client
    import boto3
    # region_name is explicit. The bearer token stays in the environment:
    # boto3's bedrock-runtime client reads AWS_BEARER_TOKEN_BEDROCK itself.
    _cached_client = boto3.client("bedrock-runtime", region_name=region)
    _cached_region = region
    return _cached_client


def _failure_details(exc: BaseException) -> tuple[str, str, str]:
    """Short code, request id, and a sentence safe to show in the chat.

    The request id comes from the error response metadata when botocore
    attached one. The raw exception text stays out of the sentence.
    """
    code = type(exc).__name__
    request_id = ""
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        err = response.get("Error") or {}
        if err.get("Code"):
            code = str(err["Code"])
        meta = response.get("ResponseMetadata") or {}
        if meta.get("RequestId"):
            request_id = str(meta["RequestId"])
    lowered = str(exc).lower()
    if code == type(exc).__name__:
        if "throttl" in lowered or "too many requests" in lowered:
            code = "ThrottlingException"
        elif "validation" in lowered:
            code = "ValidationException"
        elif isinstance(exc, (TimeoutError, ConnectionError, OSError)):
            code = "NetworkError"
    code = "".join(ch for ch in code if ch.isalnum() or ch == "_")[:40] or "Error"
    readable = {
        "ThrottlingException": "Bedrock is busy right now.",
        "ValidationException": "Bedrock rejected this request.",
        "NetworkError": "Bedrock could not be reached.",
        "Timeout": "Bedrock took too long.",
    }.get(code, f"Bedrock could not answer ({code}).")
    return code, _redact(request_id), readable


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
    request_id = ""
    try:
        client = _make_client()
    except Exception as exc:
        code, request_id, short = _failure_details(exc)
        _last_error = short
        _audit_bedrock(
            result="error", model=model, region=region, request_id=request_id,
            latency_ms=0, error=code,
        )
        log.warning("Bedrock client setup failed code=%s", code)
        return None
    started = time.perf_counter()
    try:
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
        log.info(
            "Bedrock Converse latency_ms=%s request_id=%s model=%s",
            latency_ms, _redact(request_id), model,
        )
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
        code, request_id, short = _failure_details(exc)
        if not request_id:
            request_id = ""
        _last_error = short
        _audit_bedrock(
            result="error", model=model, region=region, request_id=request_id,
            latency_ms=latency_ms, error=code,
        )
        log.warning(
            "Bedrock Converse failed model=%s region=%s request_id=%s latency_ms=%s code=%s",
            model, region, request_id, latency_ms, code,
        )
        return None


def timeout_fallback(latency_ms: int = 0) -> dict:
    """Payload when the Converse wait expires before a response arrives."""
    global _last_error
    short = "Bedrock took too long."
    _last_error = short
    _audit_bedrock(
        result="error",
        model=bedrock_model_id(),
        region=bedrock_region(),
        request_id="",
        latency_ms=max(0, int(latency_ms)),
        error="Timeout",
    )
    return {
        "bedrock": True,
        "fallback": True,
        "stopped": False,
        "reason": "model_error",
        "error_code": "Timeout",
        "label": "Fallback: pattern parser (Bedrock error: Timeout)",
        "message": short,
        "text": "",
        "calls": [],
    }


def agent_converse(messages: List[Dict[str, Any]], tool_config: Dict[str, Any]) -> Dict[str, Any]:
    """One tool-using Converse call. Does not consult SER_LLM_MODE.

    The HTTP handler refuses this when Bedrock is off. A stub client injected
    with set_client_factory is used as-is. The bearer token is never logged.
    Returns the Converse response with ok=True, or {ok: False, error: ...}.
    """
    global _last_error
    model = bedrock_model_id()
    region = bedrock_region()
    request_id = ""
    try:
        client = _make_client()
    except Exception as exc:
        code, request_id, short = _failure_details(exc)
        _last_error = short
        _audit_bedrock(
            result="error", model=model, region=region, request_id=request_id,
            latency_ms=0, error=code,
        )
        return {"ok": False, "error": short, "error_code": code, "request_id": request_id}
    started = time.perf_counter()
    try:
        resp = client.converse(
            modelId=model,
            system=[{"text": AGENT_SYSTEM_PROMPT}],
            messages=messages,
            toolConfig=tool_config,
            inferenceConfig={"maxTokens": 1024, "temperature": 0.0},
        )
        request_id = str((resp.get("ResponseMetadata") or {}).get("RequestId") or "")
        latency_ms = int((time.perf_counter() - started) * 1000)
        log.info(
            "Bedrock Converse latency_ms=%s request_id=%s model=%s",
            latency_ms, _redact(request_id), model,
        )
        _last_error = ""
        _audit_bedrock(
            result="ok", model=model, region=region, request_id=request_id,
            latency_ms=latency_ms,
        )
        out = dict(resp)
        out["ok"] = True
        return out
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        code, request_id, short = _failure_details(exc)
        _last_error = short
        _audit_bedrock(
            result="error", model=model, region=region, request_id=request_id,
            latency_ms=latency_ms, error=code,
        )
        log.warning(
            "Bedrock agent Converse failed model=%s region=%s request_id=%s latency_ms=%s code=%s",
            model, region, request_id, latency_ms, code,
        )
        return {"ok": False, "error": short, "error_code": code, "request_id": request_id}


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
        _code, _request_id, short = _failure_details(exc)
        _last_error = short
        log.warning("Bedrock narration failed code=%s", _code)
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
