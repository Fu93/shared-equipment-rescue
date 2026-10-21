"""Bounded Bedrock tool loop for the simulated Alexa+ page.

The model may propose MCP tool calls. This module decides which of those
calls are allowed to run. It does not choose slots, move bookings, or
confirm an apply. The deterministic engine does the first two. A human
Confirm click does the third, in the browser session that executes the call.

MAX_AGENT_STEPS is both the converse-round cap and the tool-execution cap.
The HTTP step handler keeps that budget on the server, per conversation,
and ignores the counters a client sends. A malformed call, an unknown tool,
a tool outside the voice allowlist, or arguments that do not match the tool
schema stops the loop. Nothing from that call is executed.

The model is offered read and propose tools, plus schedule_apply_replan.
reset_demo_data, debug_confirm, and verify_audit_chain stay in the MCP
registry and never appear in toolConfig.
"""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from .llm import _redact

MAX_AGENT_STEPS = 4
RATE_LIMIT_MAX = 30
RATE_WINDOW_SECONDS = 60.0

# Read and propose tools, plus apply through the existing Confirm path.
VOICE_TOOL_ALLOWLIST = (
    "schedule_get",
    "schedule_audit_get",
    "equipment_report_outage",
    "schedule_propose_replan",
    "schedule_apply_replan",
)
# Destructive and admin tools. Checked before unknown_tool so a name that is
# not on the server stays unknown_tool.
VOICE_TOOL_DENY = (
    "reset_demo_data",
    "debug_confirm",
    "verify_audit_chain",
)

_CONV_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_lock = threading.Lock()
_budgets: Dict[tuple, dict] = {}
_hits: Dict[str, List[float]] = {}

_MESSAGES = {
    "malformed": "The model returned a tool call this server cannot read. Nothing was called.",
    "unknown_tool": "The model asked for a tool that is not on this server. Nothing was called.",
    "not_allowed": "The model asked for a tool the voice loop is not allowed to call. Nothing was called.",
    "bad_arguments": "The model sent arguments that do not match the tool schema. Nothing was called.",
    "step_cap": "Stopped after 4 steps. Nothing further was called.",
    "overflow": (
        "That reply asked for more tool calls than the 4-step budget allows. "
        "Nothing from that reply was called."
    ),
    "not_confirmed": "Apply was not confirmed. Nothing was applied.",
    "empty": "The model returned no reply.",
    "model_error": "The model call failed. Nothing was called.",
    "rate_limited": "Too many agent requests. Wait a moment and try again.",
}


def reset_agent_budget() -> None:
    """Drop conversation caps and the per-token window. Tests call this."""
    with _lock:
        _budgets.clear()
        _hits.clear()


def catalog_from_fastmcp(mcp_app) -> List[dict]:
    """Input schemas from the live FastMCP registry, without the Context arg."""
    tools = getattr(mcp_app._tool_manager, "_tools", {}) or {}
    out = []
    for name, tool in tools.items():
        raw = dict(getattr(tool, "parameters", None) or {})
        description = (getattr(tool, "description", None) or name).strip() or name
        out.append({
            "name": name,
            "description": description[:1024],
            "input_schema": _compact_schema(raw),
        })
    return out


def tool_config_from_catalog(catalog: List[dict]) -> dict:
    """Bedrock Converse toolConfig for the voice allowlist only.

    Destructive and admin tools are omitted here, even if the caller passes
    the full registry. A buggy caller cannot put them in front of the model.
    """
    specs = []
    for tool in catalog:
        if tool["name"] not in VOICE_TOOL_ALLOWLIST:
            continue
        specs.append({
            "toolSpec": {
                "name": tool["name"],
                "description": tool["description"] or tool["name"],
                "inputSchema": {"json": tool["input_schema"]},
            }
        })
    return {"tools": specs}


def run_agent_loop(
    user_text: str,
    *,
    converse: Callable[[List[dict], dict], dict],
    execute: Callable[[str, dict], dict],
    catalog: List[dict],
    actor: Any = None,
) -> dict:
    """Run the bounded loop with an injected Converse client and executor.

    `converse(messages, tool_config)` returns one Bedrock Converse response,
    or `{"ok": False, "error": "..."}`. `execute(name, arguments)` performs
    the tool and returns a dict with `status`. This function does not look
    at SER_LLM_MODE: the HTTP handler does that. Tests inject a stub even
    while the suite is pinned to scripted mode.
    """
    messages: List[dict] = [{"role": "user", "content": [{"text": user_text}]}]
    rounds = 0
    executions = 0
    executed: List[dict] = []
    applied = False
    while True:
        step = prepare_step(
            messages,
            rounds=rounds,
            executions=executions,
            converse=converse,
            catalog=catalog,
            actor=actor,
        )
        if step.get("assistant_message"):
            messages.append(step["assistant_message"])
        rounds = int(step.get("rounds", rounds))
        if step.get("fallback"):
            return {
                "ok": False,
                "text": "",
                "error": step.get("message") or "",
                "message": step.get("message") or "",
                "executed": executed,
                "applied": applied,
                "stopped": "model_error",
                "fallback": True,
                "label": step.get("label") or "",
                "error_code": step.get("error_code") or "",
            }
        if step.get("stopped"):
            return {
                "ok": step.get("reason") in (None, "not_confirmed", "step_cap", "empty"),
                "text": step.get("text") or "",
                "error": step.get("message") if step.get("reason") not in (
                    None, "not_confirmed", "step_cap", "empty"
                ) else None,
                "message": step.get("message") or "",
                "executed": executed,
                "applied": applied,
                "stopped": step.get("reason"),
            }
        calls = step.get("calls") or []
        if not calls:
            return {
                "ok": True,
                "text": step.get("text") or "",
                "error": None,
                "message": step.get("text") or "",
                "executed": executed,
                "applied": applied,
                "stopped": None,
            }
        for call in calls:
            result = execute(call["name"], call["input"])
            if not isinstance(result, dict):
                result = {"status": "error", "message": "executor returned no object"}
            executions += 1
            status = str(result.get("status") or "error")
            executed.append({"name": call["name"], "input": call["input"], "status": status})
            _audit_call(
                actor,
                phase="result",
                name=call["name"],
                status=status,
                detail=f"phase=result tool={call['name']} status={status}",
                extra={"arguments": call["input"], "message": str(result.get("message") or "")[:300]},
            )
            if call["name"] == "schedule_apply_replan":
                applied = status == "applied"
                if status != "applied":
                    return {
                        "ok": True,
                        "text": str(result.get("message") or _MESSAGES["not_confirmed"]),
                        "error": None,
                        "message": _MESSAGES["not_confirmed"],
                        "executed": executed,
                        "applied": False,
                        "stopped": "not_confirmed",
                    }
            messages.append(_tool_result_message(call, result))
            if executions >= MAX_AGENT_STEPS:
                break


def prepare_step(
    messages: List[dict],
    *,
    rounds: int,
    executions: int,
    converse: Callable[[List[dict], dict], dict],
    catalog: List[dict],
    actor: Any = None,
) -> dict:
    """One converse round. Returns calls only when every call in the round is valid."""
    if rounds >= MAX_AGENT_STEPS or executions >= MAX_AGENT_STEPS:
        return _stop("step_cap", rounds=rounds, executions=executions)
    raw = converse(messages, tool_config_from_catalog(catalog))
    if isinstance(raw, dict) and raw.get("ok") is False:
        return _fallback_step(raw, rounds=rounds + 1, executions=executions)
    text, uses, assistant = _split_model_message(raw if isinstance(raw, dict) else {})
    if not uses:
        if not text:
            return _stop("empty", rounds=rounds + 1, executions=executions, assistant=assistant)
        return {
            "bedrock": True,
            "stopped": False,
            "reason": None,
            "message": "",
            "text": text,
            "calls": [],
            "assistant_message": assistant,
            "rounds": rounds + 1,
            "executions": executions,
        }
    if executions + len(uses) > MAX_AGENT_STEPS:
        return _stop("overflow", rounds=rounds + 1, executions=executions, assistant=assistant)
    accepted = []
    for tu in uses:
        kind = _classify(tu, catalog)
        if kind:
            name = tu.get("name") if isinstance(tu, dict) else ""
            _audit_call(
                actor,
                phase="rejected",
                name=str(name or ""),
                status="rejected",
                detail=f"phase=rejected tool={name or '-'} reason={kind}",
                extra={"reason": kind},
            )
            return _stop(kind, rounds=rounds + 1, executions=executions, assistant=assistant)
        call = {
            "toolUseId": tu["toolUseId"],
            "name": tu["name"],
            "input": tu["input"],
        }
        _audit_call(
            actor,
            phase="proposed",
            name=call["name"],
            status="proposed",
            detail=f"phase=proposed tool={call['name']}",
            extra={"arguments": call["input"], "tool_use_id": call["toolUseId"]},
        )
        accepted.append(call)
    return {
        "bedrock": True,
        "stopped": False,
        "reason": None,
        "message": "",
        "text": text,
        "calls": accepted,
        "assistant_message": assistant,
        "rounds": rounds + 1,
        "executions": executions,
    }


def http_step(body: dict, principal, catalog: List[dict], token: str = "") -> dict:
    """POST /agent/step body. Bedrock off returns the fallback flag and does not call the model.

    Client rounds and executions are ignored. The server counts converse
    rounds and approved calls for (user, conversation_id).
    """
    from . import llm

    if llm.llm_mode() != "bedrock":
        return {"bedrock": False, "label": "Bedrock: off", "error": None}
    if not _charge(token or getattr(principal, "user_id", "") or ""):
        return _rate_limited_payload()
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        return _stop("malformed", message="messages must be a non-empty list")
    if len(messages) > 40:
        return _stop("malformed", message="too many messages")
    conversation_id = body.get("conversation_id")
    if not isinstance(conversation_id, str) or not _CONV_RE.fullmatch(conversation_id):
        return _stop("malformed", message="conversation_id is required")
    key = (getattr(principal, "user_id", "") or "", conversation_id)
    with _lock:
        state = _budgets.setdefault(key, {"rounds": 0, "executions": 0})
        rounds = int(state["rounds"])
        executions = int(state["executions"])

    def converse(msgs, tool_config):
        return llm.agent_converse(msgs, tool_config)

    step = prepare_step(
        messages,
        rounds=rounds,
        executions=executions,
        converse=converse,
        catalog=catalog,
        actor=principal,
    )
    approved = len(step.get("calls") or [])
    with _lock:
        state = _budgets.setdefault(key, {"rounds": 0, "executions": 0})
        state["rounds"] = int(step.get("rounds", rounds))
        state["executions"] = int(state["executions"]) + approved
    return step


def http_result(body: dict, principal, token: str = "") -> dict:
    """POST /agent/result. Records a client-reported execution. Does not run a tool.

    status=applied is refused and writes no audit row. Only schedule_apply_replan
    on the server records an apply. Any other client status is stored as
    client-reported, with the client's status kept in the detail text.
    """
    if not _charge(token or getattr(principal, "user_id", "") or ""):
        return _rate_limited_payload()
    name = body.get("name") if isinstance(body.get("name"), str) else ""
    status = body.get("status") if isinstance(body.get("status"), str) else ""
    message = body.get("message") if isinstance(body.get("message"), str) else ""
    if status.lower() == "applied":
        return {
            "ok": False,
            "accepted": False,
            "error": "client-reported apply is not accepted",
        }
    _audit_call(
        principal,
        phase="result",
        name=name[:80],
        status="client-reported",
        detail=f"phase=result tool={name[:80]} client_status={status[:80]}",
        extra={
            "message": _redact(message)[:300],
            "tool_use_id": str(body.get("tool_use_id") or "")[:80],
            "client_status": status[:80],
        },
    )
    return {"ok": True, "accepted": True}


def _charge(token: str) -> bool:
    """True when this bearer still has room in the 30-request window."""
    key = token or "anonymous"
    now = time.monotonic()
    with _lock:
        fresh = [stamp for stamp in _hits.get(key, []) if stamp >= now - RATE_WINDOW_SECONDS]
        if len(fresh) >= RATE_LIMIT_MAX:
            _hits[key] = fresh
            return False
        fresh.append(now)
        _hits[key] = fresh
        return True


def _rate_limited_payload() -> dict:
    return {
        "bedrock": True,
        "stopped": True,
        "reason": "rate_limited",
        "message": _MESSAGES["rate_limited"],
        "text": "",
        "calls": [],
        "http_status": 429,
    }


def _fallback_step(raw: dict, *, rounds: int, executions: int) -> dict:
    """Short, readable failure. The page runs the pattern parser for this turn."""
    code = str(raw.get("error_code") or "Error")
    code = "".join(ch for ch in code if ch.isalnum() or ch == "_")[:40] or "Error"
    readable = {
        "ThrottlingException": "Bedrock is busy right now.",
        "ValidationException": "Bedrock rejected this request.",
        "NetworkError": "Bedrock could not be reached.",
        "Timeout": "Bedrock took too long.",
    }.get(code)
    message = readable or str(raw.get("error") or f"Bedrock could not answer ({code}).")
    if "arn:" in message.lower() or len(message) > 200:
        message = readable or f"Bedrock could not answer ({code})."
    return {
        "bedrock": True,
        "fallback": True,
        "stopped": False,
        "reason": "model_error",
        "error_code": code,
        "label": f"Fallback: pattern parser (Bedrock error: {code})",
        "message": message,
        "text": "",
        "calls": [],
        "assistant_message": None,
        "rounds": rounds,
        "executions": executions,
    }


def _stop(reason: str, *, rounds: int = 0, executions: int = 0,
          message: str = "", assistant=None) -> dict:
    return {
        "bedrock": True,
        "stopped": True,
        "reason": reason,
        "message": message or _MESSAGES.get(reason, reason),
        "text": "",
        "calls": [],
        "assistant_message": assistant,
        "rounds": rounds,
        "executions": executions,
    }


def _split_model_message(resp: dict):
    message = (resp.get("output") or {}).get("message") or {}
    content = message.get("content") or []
    if not isinstance(content, list):
        return "", [{"malformed": True}], None
    texts = []
    uses = []
    for block in content:
        if not isinstance(block, dict):
            uses.append({"malformed": True})
            continue
        if isinstance(block.get("text"), str) and block["text"].strip():
            texts.append(block["text"].strip())
        if "toolUse" in block:
            tu = block.get("toolUse")
            uses.append(tu if isinstance(tu, dict) else {"malformed": True})
    assistant = {"role": "assistant", "content": content} if content else None
    return " ".join(texts).strip(), uses, assistant


def _classify(tu: Any, catalog: List[dict]) -> Optional[str]:
    if not isinstance(tu, dict) or tu.get("malformed"):
        return "malformed"
    name = tu.get("name")
    inp = tu.get("input")
    tool_use_id = tu.get("toolUseId")
    if not isinstance(name, str) or not name:
        return "malformed"
    if not isinstance(inp, dict):
        return "malformed"
    if not isinstance(tool_use_id, str) or not tool_use_id:
        return "malformed"
    if name in VOICE_TOOL_DENY:
        return "not_allowed"
    known = {tool["name"]: tool for tool in catalog}
    if name not in known:
        return "unknown_tool"
    if name not in VOICE_TOOL_ALLOWLIST:
        return "not_allowed"
    if _schema_error(known[name]["input_schema"], inp):
        return "bad_arguments"
    return None


def _schema_error(schema: dict, value: Any, path: str = "$") -> Optional[str]:
    if not isinstance(schema, dict):
        return None
    if "anyOf" in schema:
        for alt in schema["anyOf"]:
            if _schema_error(alt, value, path) is None:
                return None
        return f"{path} does not match"
    if schema.get("type") == "null":
        return None if value is None else f"{path} must be null"
    kind = schema.get("type")
    if kind == "object" or "properties" in schema:
        if not isinstance(value, dict):
            return f"{path} must be an object"
        props = schema.get("properties") or {}
        missing = [key for key in (schema.get("required") or []) if key not in value]
        if missing:
            return f"{path} missing {missing}"
        unknown = sorted(key for key in value if key not in props)
        if unknown:
            return f"{path} unexpected {unknown}"
        for key, item in value.items():
            err = _schema_error(props[key], item, f"{path}.{key}")
            if err:
                return err
        return None
    if kind == "string":
        return None if isinstance(value, str) else f"{path} must be a string"
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            return f"{path} must be an integer"
        return None
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"{path} must be a number"
        return None
    if kind == "boolean":
        return None if isinstance(value, bool) else f"{path} must be a boolean"
    if kind == "array":
        if not isinstance(value, list):
            return f"{path} must be an array"
        item_schema = schema.get("items") or {}
        for index, item in enumerate(value):
            err = _schema_error(item_schema, item, f"{path}[{index}]")
            if err:
                return err
        return None
    return None


def _compact_schema(schema: dict) -> dict:
    props = {}
    for key, raw in (schema.get("properties") or {}).items():
        if key == "ctx" or not isinstance(raw, dict):
            continue
        kept = {}
        for field in ("type", "description", "enum", "items", "anyOf", "default"):
            if field in raw:
                kept[field] = raw[field]
        props[key] = kept or {"type": "string"}
    required = [key for key in (schema.get("required") or []) if key != "ctx" and key in props]
    compact = {"type": "object", "properties": props}
    if required:
        compact["required"] = required
    return compact


def _tool_result_message(call: dict, result: dict) -> dict:
    try:
        text = json.dumps(result, ensure_ascii=False, default=str)[:4000]
    except (TypeError, ValueError):
        text = "{}"
    status = "error" if result.get("status") in ("transport_error", "forbidden") else "success"
    return {
        "role": "user",
        "content": [{
            "toolResult": {
                "toolUseId": call["toolUseId"],
                "content": [{"text": text}],
                "status": status,
            }
        }],
    }


def _audit_call(actor, *, phase: str, name: str, status: str, detail: str, extra: dict) -> None:
    try:
        from . import db as dbm
    except Exception:
        return
    try:
        payload = {"phase": phase, "tool": name, "status": status, **extra}
        blob = _redact(json.dumps(payload, ensure_ascii=False, default=str)[:800])
    except (TypeError, ValueError):
        blob = "{}"
    try:
        dbm.record_audit_standalone(
            tool="agent_tool_call",
            result=_redact(status)[:80] or "error",
            actor_id=getattr(actor, "user_id", "") or "",
            actor_name=getattr(actor, "name", "") or "agent",
            actor_role=getattr(actor, "role", "") or "",
            detail=_redact(detail)[:500],
            token_hint="-",
            detail_json=blob,
        )
    except Exception:
        return
