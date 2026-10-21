"""MCP server: 6 tools, Streamable HTTP, elicitation on apply.

Identity comes exclusively from the Authorization header read off the
per-call starlette Request (ctx.request_context.request) — never from args.
Elicitation requires SSE mode (FastMCP stateless_http=False, json_response=False)
and an async client callback (spike5 evidence).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Dict, List, Optional, Tuple

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from . import constants as C
from . import db as dbm
from . import seed as seedm
from .auth import Principal, principal_from_headers
from .engine import Booking, Equipment, Outage, World, compute_plan
from .models import (
    AffectedBooking,
    AppliedChange,
    ApplyResult,
    AuditEntry,
    AuditGetResult,
    BookingView,
    ChainVerifyResult,
    Change,
    ConfirmResult,
    EarliestPossible,
    EquipmentRef,
    EquipmentView,
    OutageView,
    OutageWindow,
    PendingPlanView,
    ProposeResult,
    ProposalSummary,
    Reason,
    ReportOutageResult,
    ResetResult,
    ScheduleGetResult,
    UnresolvedEntry,
    Viewer,
)
from .timeutil import overlaps, parse_dt

mcp = FastMCP(
    "shared-equipment-rescue",
    host="127.0.0.1",
    port=8765,
    stateless_http=False,
    json_response=False,
)


# --------------------------------------------------------------------------
# audit logging (Phase 1): additive only — never touches tool payloads
# --------------------------------------------------------------------------
log = logging.getLogger("ser.server")
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    log.addHandler(_h)
    log.setLevel(os.environ.get("SER_LOG_LEVEL", "INFO").upper())
    log.propagate = False


# Transport hardening (OWASP MCP Security Cheat Sheet #6): the MCP server is
# bound to 127.0.0.1 and only ever reached via the :8080 web proxy in the demo
# topology, so a Host of anything else indicates direct tampering. A browser
# behind a rebound DNS record would present a foreign Origin — rejected too.

_BASE_ORIGINS = {
    "http://127.0.0.1:8080", "http://localhost:8080",
}


def _load_allowed_origins() -> set:
    """Demo defaults + SER_ALLOWED_ORIGINS (comma-separated absolute origins).

    Lets an alternate deployment (different proxy port, HTTPS, a tunnel)
    whitelist its browser origin without touching code. Only *exact*
    scheme://host[:port] origins are honoured — no wildcards, no trailing
    slashes, and unparseable entries are dropped loudly in the log.
    """
    extra = os.environ.get("SER_ALLOWED_ORIGINS", "").strip()
    if not extra:
        return set(_BASE_ORIGINS)
    allowed = set(_BASE_ORIGINS)
    for part in extra.split(","):
        part = part.strip().rstrip("/")
        if not part:
            continue
        if "://" not in part:
            log.warning("SER_ALLOWED_ORIGINS: ignored non-absolute origin %r", part)
            continue
        allowed.add(part)
    if allowed != _BASE_ORIGINS:
        log.info("allowed origins: %s", sorted(allowed))
    return allowed


_ALLOWED_ORIGINS = _load_allowed_origins()


def _loopback_host_allowed(host: str) -> bool:
    """Host values this server legitimately answers on.

    Production binds 127.0.0.1:8765; tests and tools may use other local
    ports, so any *loopback* host:port pair is acceptable — anything
    non-loopback (a rebound DNS name, a LAN hostname) is exactly the attack
    the guard exists for. Absent Host header (HTTP/1.0-style clients) is
    tolerated by the transport layer above.
    """
    if not host:
        return True
    if host.startswith("["):                      # IPv6 bracket form [::1]:8765
        inside, _, rest = host.partition("]")
        return inside.lstrip("[") in {"::1", "127.0.0.1"} or inside == "localhost"
    name, sep, port = host.rpartition(":")
    if not sep or not port.isdigit():             # bare hostname, no port
        name, port = host, ""
    if name in {"127.0.0.1", "localhost", "::1"}:
        return True
    # hosts that resolve to loopback (e.g. "localhost.localdomain")
    try:
        import ipaddress
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


class _TokenBucket:
    """Per-client token bucket (thread-safe; middleware runs under one loop)."""

    def __init__(self, rate_per_sec: float, burst: int):
        self.rate = rate_per_sec
        self.burst = float(burst)
        self.tokens: Dict[str, float] = {}
        self.updated: Dict[str, float] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        prev = self.updated.get(key)
        if prev is None:
            self.tokens[key] = self.burst
            self.updated[key] = now
            return True
        self.tokens[key] = min(
            self.burst, self.tokens[key] + (now - prev) * self.rate)
        self.updated[key] = now
        if self.tokens[key] >= 1.0:
            self.tokens[key] -= 1.0
            return True
        return False

    def trim(self, max_clients: int = 4096) -> None:
        """Drop state for the oldest idle clients so memory stays bounded."""
        if len(self.updated) <= max_clients:
            return
        for k in sorted(self.updated, key=self.updated.get)[:-max_clients]:
            self.tokens.pop(k, None)
            self.updated.pop(k, None)


# Flood budget: ~4 req/s sustained, burst 16 — far above any legitimate demo
# flow (a browser session issues <2 req/s), far below API-abuse rates.
# Tests disable it via SER_NO_RATE_LIMIT=1, checked per request so the env may
# be set after import (they share one loopback IP and open/close sessions fast).
_RATE_LIMIT = _TokenBucket(rate_per_sec=4.0, burst=16)


def _rate_limit_enabled() -> bool:
    return os.environ.get("SER_NO_RATE_LIMIT") != "1"


_STARTED_MONO = time.monotonic()


def _db_facts() -> dict:
    """Cheap, read-only DB facts for /metrics. Never raises.

    Includes the audit-chain head (id + hash) and the transport-ledger head:
    an external monitor can scrape /metrics and PIN these hashes, so any
    later tampering (edit/delete/splice) is detectable against the pinned
    value even without direct DB access.
    """
    try:
        conn = dbm.connect_fresh()
        try:
            counts = {
                "users": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
                "equipment": conn.execute("SELECT COUNT(*) FROM equipment").fetchone()[0],
                "bookings": conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0],
                "outages": conn.execute("SELECT COUNT(*) FROM outages").fetchone()[0],
                "plans": conn.execute("SELECT COUNT(*) FROM plans").fetchone()[0],
                "audit_rows": conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0],
            }
            mode = conn.execute("PRAGMA journal_mode").fetchone()
        finally:
            conn.close()
        chain = dbm.verify_audit_chain() or {}
        transport = dbm.verify_transport_chain() or {}
        return {"schedule_version": dbm.get_version(),
                "journal_mode": (mode[0] if mode else "unknown"),
                "audit_chain": {
                    "ok": bool(chain.get("ok")),
                    "rows": chain.get("checked", 0),
                    "head_id": chain.get("head_id"),
                    "head_hash": chain.get("head_hash"),
                },
                "transport_ledger": {
                    "ok": bool(transport.get("ok")),
                    "rows": transport.get("checked", 0),
                    "head_id": transport.get("head_id"),
                    "head_hash": transport.get("head_hash"),
                    "events": dbm.transport_counts(),
                },
                **counts}
    except Exception as exc:
        return {"error": str(exc)[:120]}


def _client_key(scope) -> str:
    """Rate-limit bucket key for one request.

    In the demo topology the only trusted proxy is our own web app on loopback
    (and only when the raw socket peer is loopback too). X-Forwarded-For from
    any other peer is attacker-controlled: trusting it would let a flooder
    mint a fresh bucket per request by rotating the header. So the proxy
    header is honoured only for loopback peers; everyone else is keyed by
    their raw socket address, which cannot be spoofed.
    """
    peer = scope.get("client")
    peer_host = peer[0] if peer else "unknown"
    # X-Forwarded-For is accepted as the bucket key ONLY from the demo web
    # proxy (loopback peer that also carries our proxy marker). Any other
    # caller — even on loopback — is keyed by its raw socket address, so a
    # flooder cannot mint fresh buckets by rotating the header. The web proxy
    # itself forwards nothing here (browser clients are all 127.0.0.1), so
    # under the demo topology every bucket stays spoof-proof.
    return peer_host


class TransportGuardMiddleware:
    """Pure-ASGI 403 gate: validates Origin/Host before ANY route handles.

    Pure ASGI middleware (not a Starlette route) so it runs ahead of the
    /mcp protocol route regardless of route registration order. Also serves
    as the single place that decides whether the caller looks like the demo
    web proxy or a legitimate local MCP client, and per-IP rate limits floods.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1")
                   for k, v in scope.get("headers", [])}
        peer = _client_key(scope)
        origin = headers.get("origin")
        if origin is not None and origin not in _ALLOWED_ORIGINS:
            await self._reject(scope, send, peer, "origin",
                               f"unrecognized Origin {origin!r}")
            return
        host = headers.get("host", "")
        if host and not _loopback_host_allowed(host):
            await self._reject(scope, send, peer, "host",
                               f"unrecognized Host {host!r}")
            return
        if _rate_limit_enabled() and not _RATE_LIMIT.allow(peer):
            await self._reject(scope, send, peer, "rate_429",
                               "rate limit exceeded", status=429)
            return
        if _rate_limit_enabled():
            _RATE_LIMIT.trim()
        if scope.get("path") == "/metrics" and scope.get("method") == "GET":
            await self._metrics(send)
            return
        if scope.get("method") == "POST" and scope.get("path", "").rstrip("/") == "/mcp":
            ok, err, receive = await self._strict_arguments(scope, receive)
            if not ok:
                await self._reject(scope, send, peer, "invalid_argument", err)
                return
        await self.app(scope, receive, send)

    @classmethod
    async def _strict_arguments(cls, scope, receive):
        """Buffer the POST body and reject tools/call arguments unknown to the
        registered inputSchema.

        FastMCP's pydantic arg model silently DROPS surplus JSON-RPC arguments
        (default extra=ignore), so a client that sends schedule_get an extra
        `equipment_id` gets an ok result — masking the client bug. The frozen
        contract cannot grow additionalProperties:false, so this guard is the
        server-side rejection point. Returns (ok, error_message, receive): on
        pass-through the receive is replaced by a replaying one, because the
        original stream has already been consumed into the buffer.

        Any non tools/call POST (initialize, notifications, batched legacy…)
        is passed through untouched, and on parse indeterminacy (non-JSON,
        batch arrays…) the MCP protocol layer produces the canonical error.
        """
        body = bytearray()
        while True:
            message = await receive()
            mtype = message.get("type", "")
            if mtype == "http.request":
                body += message.get("body", b"")
                if not message.get("more_body", False):
                    break
            elif mtype == "http.disconnect":
                return False, "client disconnected mid-request", receive
            else:
                # non-body control message; nothing more we can buffer
                break
        buffered = bytes(body)

        replay_receive = cls._make_replay_receive(buffered, receive)

        try:
            rpc = json.loads(buffered)
        except (json.JSONDecodeError, UnicodeDecodeError):
            # non-JSON: the protocol layer's parse error is authoritative
            return True, "", replay_receive
        if not isinstance(rpc, dict) or rpc.get("method") != "tools/call":
            return True, "", replay_receive
        params = rpc.get("params") if isinstance(rpc.get("params"), dict) else {}
        name = params.get("name")
        args = params.get("arguments") or {}
        if not isinstance(args, dict) or not isinstance(name, str):
            # malformed params: let the MCP layer emit its own protocol error
            return True, "", replay_receive
        tool = mcp._tool_manager.get_tool(name)
        if tool is None:
            return True, "", replay_receive
        known = set((tool.parameters or {}).get("properties", {}).keys())
        unknown = sorted(set(args.keys()) - known)
        if not unknown:
            return True, "", replay_receive
        return False, (
            f"{name} received unexpected argument(s) {unknown}; "
            f"expected only {sorted(known)}"
        ), receive

    @staticmethod
    def _make_replay_receive(buffered: bytes, original_receive):
        """Wrap the drained receive so the app reads the buffered body once,
        then any further reads fall through to the original stream."""
        consumed = False

        async def _receive():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request",
                        "body": buffered, "more_body": False}
            return await original_receive()

        return _receive

    @staticmethod
    async def _metrics(send) -> None:
        """Loopback-only observability endpoint (utf-8 JSON, no auth data).

        Served by the guard itself, before the MCP protocol app: a scrape of
        /metrics must not consume MCP session resources and must work even
        while the session manager is warming up. Exposes process health
        (uptime), DB shape (schema row counts, chain integrity summary) and
        rate-limiter state. Only loopback peers reach this ASGI app at all in
        the demo topology (the server binds 127.0.0.1); the Host check above
        stands in front of it, so this is not an information leak surface.
        """
        import time as _t
        stats = {
            "uptime_seconds": round(_t.monotonic() - _STARTED_MONO, 1),
            "rate_limit": {
                "enabled": _rate_limit_enabled(),
                "rate_per_sec": _RATE_LIMIT.rate,
                "burst": _RATE_LIMIT.burst,
                "tracked_clients": len(getattr(_RATE_LIMIT, "updated", {})),
            },
            "database": _db_facts(),
        }
        body = json.dumps(stats, ensure_ascii=False, indent=2).encode()
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"application/json"),
                                (b"cache-control", b"no-store")]})
        await send({"type": "http.response.body", "body": body})

    @staticmethod
    async def _reject(scope, send, peer: str, event: str, message: str,
                      status: int = 403) -> None:
        """Deny the request AND pin it to the transport ledger.

        The ledger write is best-effort and synchronous-in-thread: it must not
        delay the denial meaningfully, and it must never raise into the ASGI
        stack. Every 403/429 the guard emits therefore leaves a hash-chained,
        reset-surviving evidence row keyed by peer address — the accountability
        counterpart of the per-tool audit trail.
        """
        path = scope.get("path", "")
        await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: dbm.record_transport_event_standalone(
                peer=peer, event=event, why=message, path=path
            ),
        )
        body = (
            '{"jsonrpc":"2.0","id":null,"error":{"code":-32002,'
            f'"message":"rejected: {message}"}}'
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send(
            {"type": "http.response.body", "body": body}
        )


class _State:
    db_path: Optional[str] = None


_state = _State()


def _db_path() -> str:
    return os.environ.get("SER_DB_PATH", "server.db")


def ensure_ready() -> None:
    """Configure DB path; the DB must already exist (init at startup/reset)."""
    path = _db_path()
    if _state.db_path != path:
        dbm.configure(path)
        _state.db_path = path
    dbm.configure(path)


def initialize_storage() -> None:
    """Create schema; seed demo data ONLY on a fresh (empty) database.

    Restart persistence: if the db already exists (schema has meta.version),
    the stored outage/plan/booking state is kept — a server restart or crash
    must never silently wipe the manager's work. Explicit reset stays available
    via the reset_demo_data tool. FRESHSEED=1 env forces a reseed (used by
    contract/example regen tooling)."""
    path = _db_path()
    dbm.configure(path)
    dbm.init_db(path)
    if os.environ.get("SER_FRESHSEED") == "1":
        _reseed()
        return
    conn = dbm.connect_fresh()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM bookings"
        ).fetchone()
    finally:
        conn.close()
    if row[0] > 0:
        return  # existing data: keep it (restart persistence)
    _reseed()


def _reseed() -> None:
    conn = dbm.connect_fresh()
    try:
        conn.execute("BEGIN IMMEDIATE")
        seedm.seed(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _plan_json(plan_row: dict) -> Tuple[list, list]:
    """Parse a plans row's JSON columns."""
    return json.loads(plan_row["changes"]), json.loads(plan_row["unresolved"])


def _principal(ctx: Context) -> Optional[Principal]:
    rc = ctx.request_context if ctx is not None else None
    req = getattr(rc, "request", None) if rc is not None else None
    if req is None:
        return None
    return principal_from_headers(req.headers.get)


def _forbidden_ctx(version: int) -> str:
    return "missing or invalid Authorization token"


def _token_hint(ctx: Context) -> str:
    """Non-identifying hint for audit rows (never the secret).

    Demo tokens share the "tok-" prefix, so hinting the first 4 chars yields
    the same useless string on every row ("tok-…"); hint the discriminative
    suffix instead ("manager", "chen"…). Unknown shapes keep a generic hint.
    """
    rc = ctx.request_context if ctx is not None else None
    req = getattr(rc, "request", None) if rc is not None else None
    if req is None:
        return "-"
    auth = req.headers.get("authorization") or ""
    parts = auth.strip().split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        tok = parts[1].strip()
        if tok and len(tok) > 4:
            if tok.startswith("tok-"):
                return tok[4:8] + ("…" if len(tok) > 8 else "")
            return tok[:4] + "…"
        return "…"
    return "none"


def _audit(
    tool: str,
    result: str,
    p: Optional[Principal],
    detail: str = "",
    ctx: Optional[Context] = None,
    extras: Optional[dict] = None,
) -> None:
    """Best-effort structured audit row for one tool call. Never raises.

    Alongside the human-readable `detail` string, a machine-readable mirror is
    stored in `detail_json`: `{tool, result, at, ...extras}`. Callers pass
    structured keys (ids, counts, versions) there so log scrapers / SIEM can
    query without parsing the prose. The JSON mirror is best-effort too — an
    unserializable value degrades to {} and never breaks the tool response.
    """
    dj = {"tool": tool, "result": result}
    if extras:
        for k, v in extras.items():
            try:
                json.dumps(v)
                dj[k] = v
            except (TypeError, ValueError):
                dj[k] = repr(v)
    try:
        dj_s = json.dumps(dj, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        dj_s = "{}"
    dbm.record_audit_standalone(
        tool=tool,
        result=result,
        actor_id=p.user_id if p else "",
        actor_name=p.name if p else "",
        actor_role=p.role if p else "",
        detail=detail[:500],
        token_hint=_token_hint(ctx) if ctx is not None else "-",
        detail_json=dj_s,
    )


def _load_tables(conn) -> Tuple[list, list, list, list]:
    eq_rows = dbm.equipment_for_unit(C.UNIT_ID, conn)
    bk_rows = dbm.bookings_for_date(C.DEMO_DATE, conn)
    out_rows = dbm.outages_for_date(C.DEMO_DATE, conn)
    plan_rows = conn.execute(
        "SELECT * FROM plans ORDER BY created_at"
    ).fetchall()
    return eq_rows, bk_rows, out_rows, plan_rows


def _outage_affects(outage: dict, bk: dict) -> bool:
    return bk["equipment_id"] == outage["equipment_id"] and overlaps(
        parse_dt(bk["current_start"]),
        parse_dt(bk["current_end"]),
        parse_dt(outage["start"]),
        parse_dt(outage["end"]),
    )


def _affected_ids(out_rows: list, bk_rows: list) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for o in out_rows:
        ids = [b["id"] for b in bk_rows if _outage_affects(o, b)]
        result[o["id"]] = ids
    return result


def _name_map(eq_rows: list) -> dict[str, str]:
    return {r["id"]: r["name"] for r in eq_rows}


def _row_to_engine_booking(r) -> Booking:
    return Booking(
        id=r["id"],
        user_id=r["user_id"],
        equipment_id=r["equipment_id"],
        start=r["current_start"],
        end=r["current_end"],
        deadline=r["deadline"],
        movable=bool(r["movable"]),
        status=r["status"],
    )


def _build_world(conn, eq_rows, bk_rows, out_rows) -> World:
    from .timeutil import hhmm_boundary

    equipment = {
        r["id"]: Equipment(
            id=r["id"],
            name=r["name"],
            available_start=r["available_start"],
            available_end=r["available_end"],
            buffer_minutes=r["buffer_minutes"],
        )
        for r in eq_rows
    }
    outages = [
        Outage(
            id=r["id"],
            equipment_id=r["equipment_id"],
            start=r["start"],
            end=r["end"],
            reason=r["reason"] or "",
        )
        for r in out_rows
    ]
    bookings = [_row_to_engine_booking(r) for r in bk_rows]
    day_open = {
        eid: hhmm_boundary(C.DEMO_DATE, eq.available_start)
        for eid, eq in equipment.items()
    }
    day_close = {
        eid: hhmm_boundary(C.DEMO_DATE, eq.available_end)
        for eid, eq in equipment.items()
    }
    return World(
        equipment=equipment,
        outages=outages,
        bookings=bookings,
        user_names=seedm.user_names(),
        user_permissions=seedm.user_permissions(),
        day_open=day_open,
        day_close=day_close,
    )


def _viewer(p: Principal) -> Viewer:
    return Viewer(user_id=p.user_id, name=p.name, role=p.role)


# --------------------------------------------------------------------------
# Tool 1: schedule_get
# --------------------------------------------------------------------------


async def _schedule_get_impl(
    unit_id: str, date: str, ctx: Context
) -> ScheduleGetResult:
    ensure_ready()
    p = _principal(ctx)
    version = dbm.get_version()
    if p is None:
        log.info("call schedule_get unit=%s date=%s actor=- status=forbidden", unit_id, date)
        _audit("schedule_get", "forbidden", None, f"unit={unit_id} date={date}", ctx)
        return ScheduleGetResult(
            status="forbidden",
            schedule_version=version,
            timezone=C.DEMO_TZ,
            date=date,
            unit_id=unit_id,
            unit_name=C.UNIT_NAME,
            viewer=Viewer(user_id="", name="", role=""),
            equipment=[],
            bookings=[],
            open_outages=[],
            pending_plans=[],
            message=_forbidden_ctx(version),
        )
    viewer = _viewer(p)
    if unit_id != C.UNIT_ID:
        return ScheduleGetResult(
            status="invalid_argument",
            schedule_version=version,
            timezone=C.DEMO_TZ,
            date=date,
            unit_id=unit_id,
            unit_name=C.UNIT_NAME,
            viewer=viewer,
            equipment=[],
            bookings=[],
            open_outages=[],
            pending_plans=[],
            message=f"unknown unit {unit_id!r}; demo unit is {C.UNIT_ID!r}",
        )
    if date != C.DEMO_DATE:
        return ScheduleGetResult(
            status="invalid_argument",
            schedule_version=version,
            timezone=C.DEMO_TZ,
            date=date,
            unit_id=unit_id,
            unit_name=C.UNIT_NAME,
            viewer=viewer,
            equipment=[],
            bookings=[],
            open_outages=[],
            pending_plans=[],
            message=f"demo restricted to {C.DEMO_DATE}",
        )

    conn = dbm.connect_fresh()
    try:
        eq_rows, bk_rows, out_rows, plan_rows = _load_tables(conn)
    finally:
        conn.close()

    names = seedm.user_names()
    roles = {u["id"]: u["role"] for u in dbm.users_query()}
    eqn = _name_map(eq_rows)
    is_manager = p.role == "manager"
    affected = _affected_ids(out_rows, bk_rows)

    bookings: List[BookingView] = []
    for bk in bk_rows:
        own = is_manager or bk["user_id"] == p.user_id
        if own:
            bookings.append(
                BookingView(
                    id=bk["id"],
                    user=names.get(bk["user_id"], bk["user_id"]),
                    user_id=bk["user_id"],
                    role=roles.get(bk["user_id"]),
                    equipment=bk["equipment_id"],
                    equipment_name=eqn.get(bk["equipment_id"], bk["equipment_id"]),
                    start=bk["current_start"],
                    end=bk["current_end"],
                    deadline=bk["deadline"],
                    status=bk["status"],
                    movable=bool(bk["movable"]),
                    masked=False,
                    affected_by_outage=(
                        next(
                            (oid for oid, ids in affected.items() if bk["id"] in ids),
                            None,
                        )
                    ),
                )
            )
        else:
            bookings.append(
                BookingView(
                    id=bk["id"],
                    user="Occupied",
                    user_id=None,
                    role=None,
                    equipment=bk["equipment_id"],
                    equipment_name=eqn.get(bk["equipment_id"], bk["equipment_id"]),
                    start=bk["current_start"],
                    end=bk["current_end"],
                    deadline=None,
                    status=C.STATUS_OCCUPIED,
                    movable=False,
                    masked=True,
                    affected_by_outage=None,
                )
            )
    bookings.sort(key=lambda b: b.start)

    equipment = [
        EquipmentView(
            id=er["id"],
            name=er["name"],
            available_start=er["available_start"],
            available_end=er["available_end"],
            buffer_minutes=er["buffer_minutes"],
            outages=[
                OutageWindow(id=o["id"], start=o["start"], end=o["end"], reason=o["reason"])
                for o in out_rows
                if o["equipment_id"] == er["id"]
            ],
        )
        for er in eq_rows
    ]

    open_outages: List[OutageView] = []
    for o in out_rows:
        aff_ids = affected.get(o["id"], [])
        stats = {b["id"]: b["status"] for b in bk_rows}
        unresolved_ids = [
            bid for bid in aff_ids if stats.get(bid) == C.STATUS_UNRESOLVED
        ]
        has_open = any(
            stats.get(bid) in (C.STATUS_BLOCKED, C.STATUS_UNRESOLVED) for bid in aff_ids
        )
        if has_open:
            open_outages.append(
                OutageView(
                    id=o["id"],
                    equipment=o["equipment_id"],
                    equipment_name=eqn.get(o["equipment_id"], o["equipment_id"]),
                    start=o["start"],
                    end=o["end"],
                    reason=o["reason"],
                    affected_booking_ids=aff_ids,
                    unresolved_booking_ids=unresolved_ids,
                    resolved=False,
                )
            )

    pending = [
        PendingPlanView(
            plan_id=pr["id"],
            outage_id=pr["outage_id"],
            based_on_version=pr["based_on_version"],
            is_complete=len(json.loads(pr["unresolved"])) == 0,
            change_count=len(json.loads(pr["changes"])),
            unresolved_count=len(json.loads(pr["unresolved"])),
            created_at=pr["created_at"],
        )
        for pr in plan_rows
        if pr["status"] == "proposed"
    ]

    from .llm import script_schedule_overview

    _snap = {
        "schedule_version": version,
        "viewer": {"name": viewer.name, "user_id": viewer.user_id, "role": viewer.role},
        "bookings": [b.model_dump() for b in bookings],
        "open_outages": [o.model_dump() for o in open_outages],
    }
    log.info("call schedule_get unit=%s date=%s actor=%s status=ok", unit_id, date, viewer.name)
    _audit("schedule_get", "ok", p, f"unit={unit_id} date={date} version={version}", ctx)
    return ScheduleGetResult(
        status="ok",
        schedule_version=version,
        timezone=C.DEMO_TZ,
        date=C.DEMO_DATE,
        unit_id=C.UNIT_ID,
        unit_name=C.UNIT_NAME,
        viewer=viewer,
        equipment=equipment,
        bookings=bookings,
        open_outages=open_outages,
        pending_plans=pending,
        message=script_schedule_overview(_snap),
    )


@mcp.tool()
async def schedule_get(
    unit_id: str = C.UNIT_ID, date: str = C.DEMO_DATE, ctx: Context = None
) -> ScheduleGetResult:
    """Read one unit's schedule for one date with role-based masking."""
    # FastMCP's pydantic arg model silently DROPS surplus arguments (pydantic
    # default extra=ignore), so a stray `equipment_id` never reaches here. To
    # still surface client bugs, TransportGuardMiddleware._strict_arguments
    # re-checks tools/call arguments against the registered inputSchema and
    # rejects surplus keys before the protocol layer sees them. The docstring
    # feeds the FROZEN contract description, so the note lives in code only.
    return await _schedule_get_impl(unit_id, date, ctx)


# --------------------------------------------------------------------------
# Tool 2: equipment_report_outage
# --------------------------------------------------------------------------


async def _report_outage_impl(
    equipment_id: str, start: str, end: str, reason: Optional[str], ctx: Context
) -> ReportOutageResult:
    ensure_ready()
    p = _principal(ctx)
    version = dbm.get_version()
    if p is None or p.role != "manager":
        log.info("call report_outage actor=- status=forbidden")
        _audit("equipment_report_outage", "forbidden", p,
               "manager role required" if p else "no principal", ctx,
               extras={"equipment_id": equipment_id,
                       "window_start": start, "window_end": end})
        return ReportOutageResult(
            status="forbidden",
            outage_id=None,
            equipment=None,
            schedule_version=version,
            message=_forbidden_ctx(version) if p is None else "manager role required",
        )

    conn = dbm.connect_fresh()
    try:
        eq_rows = dbm.equipment_for_unit(C.UNIT_ID, conn)
        eq = next((r for r in eq_rows if r["id"] == equipment_id), None)
        if eq is None:
            _audit("equipment_report_outage", "unknown_equipment", p,
                   f"unknown equipment {equipment_id!r}", ctx,
                   extras={"equipment_id": equipment_id})
            return ReportOutageResult(
                status="unknown_equipment",
                outage_id=None,
                equipment=None,
                schedule_version=version,
                message=f"unknown equipment {equipment_id!r}",
            )
        try:
            s_dt = parse_dt(start)
            e_dt = parse_dt(end)
        except Exception:
            _audit("equipment_report_outage", "invalid_argument", p,
                   "start/end must be ISO 8601 with timezone", ctx,
                   extras={"equipment_id": equipment_id,
                           "window_start": start, "window_end": end})
            return ReportOutageResult(
                status="invalid_argument",
                outage_id=None,
                equipment=None,
                schedule_version=version,
                message="start/end must be ISO 8601 with timezone",
            )
        if e_dt <= s_dt:
            _audit("equipment_report_outage", "invalid_argument", p,
                   "end must be after start", ctx,
                   extras={"equipment_id": equipment_id,
                           "window_start": start, "window_end": end})
            return ReportOutageResult(
                status="invalid_argument",
                outage_id=None,
                equipment=None,
                schedule_version=version,
                message="end must be after start",
            )
        w_start = parse_dt(C.DEMO_WINDOW_START)
        w_end = parse_dt(C.DEMO_WINDOW_END)
        if not (w_start <= s_dt < w_end):
            _audit("equipment_report_outage", "invalid_argument", p,
                   "start outside demo day window", ctx,
                   extras={"equipment_id": equipment_id,
                           "window_start": start, "window_end": end})
            return ReportOutageResult(
                status="invalid_argument",
                outage_id=None,
                equipment=None,
                schedule_version=version,
                message=f"demo day only: start must be within [{C.DEMO_WINDOW_START}, {C.DEMO_WINDOW_END})",
            )
        if not (w_start <= e_dt <= w_end):
            _audit("equipment_report_outage", "invalid_argument", p,
                   "end outside demo day window", ctx,
                   extras={"equipment_id": equipment_id,
                           "window_start": start, "window_end": end})
            return ReportOutageResult(
                status="invalid_argument",
                outage_id=None,
                equipment=None,
                schedule_version=version,
                message=f"demo day only: end must be within [{C.DEMO_WINDOW_START}, {C.DEMO_WINDOW_END})",
            )
        # duplicate: overlapping existing outage on same equipment
        out_rows = dbm.outages_for_date(C.DEMO_DATE, conn)
        for o in out_rows:
            if o["equipment_id"] != equipment_id:
                continue
            if overlaps(s_dt, e_dt, parse_dt(o["start"]), parse_dt(o["end"])):
                bk_rows = dbm.bookings_for_equipment_date(equipment_id, C.DEMO_DATE, conn)
                aff = [b for b in bk_rows if _outage_affects(o, b)]
                log.info("call report_outage eq=%s window=%s..%s actor=%s status=duplicate_outage existing=%s",
                         equipment_id, start, end, p.name, o["id"])
                _audit("equipment_report_outage", "duplicate_outage", p,
                       f"equipment={equipment_id} window={start}..{end} existing={o['id']}", ctx,
                       extras={"outage_id": o["id"], "equipment_id": equipment_id,
                               "window_start": start, "window_end": end})
                return ReportOutageResult(
                    status="duplicate_outage",
                    outage_id=o["id"],
                    equipment=EquipmentRef(id=eq["id"], name=eq["name"], unit_id=C.UNIT_ID),
                    affected_bookings=[
                        AffectedBooking(
                            id=b["id"],
                            user=seedm.user_names().get(b["user_id"], b["user_id"]),
                            user_id=b["user_id"],
                            start=b["current_start"],
                            end=b["current_end"],
                            deadline=b["deadline"],
                            status=b["status"],
                        )
                        for b in aff
                    ],
                    unaffected_count=len(bk_rows) - len(aff),
                    schedule_version=version,
                    message=f"duplicate outage; existing outage {o['id']} already covers this window",
                )
        # record
        n_out = len(out_rows) + 1
        outage_id = f"O{n_out}"
        bk_rows = dbm.bookings_for_equipment_date(equipment_id, C.DEMO_DATE, conn)
        affected_rows = [
            b
            for b in bk_rows
            if overlaps(
                s_dt, e_dt, parse_dt(b["current_start"]), parse_dt(b["current_end"])
            )
        ]
        conn.execute("BEGIN IMMEDIATE")
        try:
            dbm.insert_outage(
                conn,
                outage_id=outage_id,
                equipment_id=equipment_id,
                start=fmt_or(s_dt),
                end=fmt_or(e_dt),
                reason=reason,
                created_by=p.user_id,
            )
            dbm.block_bookings(conn, [b["id"] for b in affected_rows])
            new_version = dbm.bump_version(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        log.info("call report_outage eq=%s window=%s..%s actor=%s status=recorded outage=%s", equipment_id, start, end, p.name, outage_id)
        _audit("equipment_report_outage", "recorded", p,
               f"equipment={equipment_id} window={start}..{end} outage={outage_id} version={new_version}", ctx,
               extras={"outage_id": outage_id, "equipment_id": equipment_id,
                       "window_start": start, "window_end": end,
                       "blocked_count": len(affected_rows),
                       "schedule_version": new_version})
        return ReportOutageResult(
            status="recorded",
            outage_id=outage_id,
            equipment=EquipmentRef(id=eq["id"], name=eq["name"], unit_id=C.UNIT_ID),
            affected_bookings=[
                AffectedBooking(
                    id=b["id"],
                    user=seedm.user_names().get(b["user_id"], b["user_id"]),
                    user_id=b["user_id"],
                    start=b["current_start"],
                    end=b["current_end"],
                    deadline=b["deadline"],
                    status="blocked",
                )
                for b in affected_rows
            ],
            unaffected_count=len(bk_rows) - len(affected_rows),
            schedule_version=new_version,
            message=f"outage {outage_id} recorded on {eq['name']}; {len(affected_rows)} booking(s) blocked; version {new_version}",
        )
    finally:
        conn.close()


def fmt_or(dt) -> str:
    return dt.isoformat()


@mcp.tool()
async def equipment_report_outage(
    equipment_id: str,
    start: str,
    end: str,
    reason: str = "",
    ctx: Context = None,
) -> ReportOutageResult:
    """Record an equipment outage (manager only); affected bookings become blocked."""
    return await _report_outage_impl(
        equipment_id, start, end, reason or None, ctx
    )


# --------------------------------------------------------------------------
# Tool 3: schedule_propose_replan
# --------------------------------------------------------------------------


def _unresolved_to_model(u: dict) -> UnresolvedEntry:
    return UnresolvedEntry(
        booking_id=u["booking_id"],
        user=u["user"],
        user_id=u["user_id"],
        equipment=u["equipment"],
        equipment_name=u["equipment_name"],
        original_start=u["original_start"],
        original_end=u["original_end"],
        deadline=u.get("deadline"),
        movable=u["movable"],
        reasons=[Reason(**r) for r in u["reasons"]],
        earliest_possible=[
            EarliestPossible(
                equipment_id=e["equipment_id"],
                equipment_name=e["equipment_name"],
                status=e["status"],
                earliest_start=e.get("earliest_start"),
                earliest_finish=e.get("earliest_finish"),
                blockers=[Reason(**r) for r in e.get("blockers", [])],
                would_work_if=[Reason(**r) for r in e.get("would_work_if", [])],
            )
            for e in u.get("earliest_possible", [])
        ],
    )


def _changes_to_model(c: dict) -> Change:
    return Change(
        booking_id=c["booking_id"],
        user=c["user"],
        user_id=c["user_id"],
        original_equipment=c["original_equipment"],
        original_equipment_name=c["original_equipment_name"],
        original_start=c["original_start"],
        original_end=c["original_end"],
        new_equipment=c["new_equipment"],
        new_equipment_name=c["new_equipment_name"],
        new_start=c["new_start"],
        new_end=c["new_end"],
        reasons=[Reason(**r) for r in c["reasons"]],
    )


async def _propose_impl(
    outage_id: str, schedule_version: int, ctx: Context
) -> ProposeResult:
    ensure_ready()
    p = _principal(ctx)
    current = dbm.get_version()
    if p is None or p.role != "manager":
        _audit("schedule_propose_replan", "forbidden", p,
               "manager role required" if p else "no principal", ctx,
               extras={"outage_id": outage_id})
        return ProposeResult(
            status="forbidden",
            outage_id=outage_id,
            schedule_version=current,
            message=_forbidden_ctx(current) if p is None else "manager role required",
        )
    conn = dbm.connect_fresh()
    try:
        o = dbm.get_outage(outage_id, conn)
        if o is None:
            _audit("schedule_propose_replan", "unknown_outage", p,
                   f"unknown outage {outage_id!r}", ctx,
                   extras={"outage_id": outage_id})
            return ProposeResult(
                status="unknown_outage",
                outage_id=outage_id,
                schedule_version=current,
                message=f"unknown outage {outage_id!r}",
            )
        bk_rows = dbm.bookings_for_equipment_date(o["equipment_id"], C.DEMO_DATE, conn)
        blocked_ids = [
            b["id"]
            for b in bk_rows
            if b["status"] == C.STATUS_BLOCKED and _outage_affects(o, b)
        ]
        if not blocked_ids:
            _audit("schedule_propose_replan", "outage_resolved", p,
                   f"outage {outage_id} has no blocked bookings", ctx,
                   extras={"outage_id": outage_id})
            return ProposeResult(
                status="outage_resolved",
                outage_id=outage_id,
                schedule_version=current,
                message=f"outage {outage_id} has no blocked bookings",
            )
        if schedule_version != current:
            _audit("schedule_propose_replan", "plan_stale", p,
                   f"schedule_version is now {current}", ctx,
                   extras={"outage_id": outage_id, "client_version": schedule_version,
                           "current_version": current})
            return ProposeResult(
                status="plan_stale",
                outage_id=outage_id,
                schedule_version=current,
                message=f"schedule_version is now {current}; re-propose with the current version",
            )
        existing = dbm.proposed_plan_for(outage_id, schedule_version, conn)
        if existing is not None:
            log.info("call propose outage=%s actor=%s status=proposed idempotent plan=%s", outage_id, p.name, existing["id"])
            changes_j, unresolved_j = _plan_json(existing)
            return ProposeResult(
                status="proposed",
                plan_id=existing["id"],
                outage_id=outage_id,
                based_on_version=existing["based_on_version"],
                schedule_version=current,
                changes=[_changes_to_model(c) for c in changes_j],
                unresolved=[_unresolved_to_model(u) for u in unresolved_j],
                is_complete=len(unresolved_j) == 0,
                summary=ProposalSummary(
                    affected=len(changes_j) + len(unresolved_j) + _other_blocked_count(),
                    rescheduled=len(changes_j),
                    unresolved=len(unresolved_j),
                ),
                generated_at=existing["created_at"],
                message=f"existing plan {existing['id']} reused (idempotent)",
            )

        eq_rows = dbm.equipment_for_unit(C.UNIT_ID, conn)
        all_bk = dbm.bookings_for_date(C.DEMO_DATE, conn)
        out_rows = dbm.outages_for_date(C.DEMO_DATE, conn)
        world = _build_world(conn, eq_rows, all_bk, out_rows)
        eng_outage = Outage(
            id=o["id"],
            equipment_id=o["equipment_id"],
            start=o["start"],
            end=o["end"],
            reason=o["reason"] or "",
        )
        changes, unresolved = compute_plan(world, eng_outage)
        changes_j = [c.model_dump(by_alias=True) for c in changes]
        unresolved_j = [u.model_dump(by_alias=True) for u in unresolved]

        conn.execute("BEGIN IMMEDIATE")
        try:
            # re-verify under the write lock: outage may have been resolved or
            # another outage inserted while the engine was computing outside
            # the txn; the outage id must still exist too.
            if dbm.get_outage(outage_id, conn) is None:
                conn.rollback()
                _audit("schedule_propose_replan", "unknown_outage", p,
                       f"outage {outage_id!r} vanished during propose", ctx,
                       extras={"outage_id": outage_id, "raced": True})
                return ProposeResult(
                    status="unknown_outage",
                    outage_id=outage_id,
                    schedule_version=current,
                    message=f"unknown outage {outage_id!r}",
                )
            if dbm.get_version_conn(conn) != current:
                conn.rollback()
                _audit("schedule_propose_replan", "plan_stale", p,
                       f"schedule_version moved to {dbm.get_version_conn(conn)}"
                       " during propose", ctx,
                       extras={"outage_id": outage_id, "client_version": schedule_version,
                               "current_version": dbm.get_version_conn(conn),
                               "raced": True})
                return ProposeResult(
                    status="plan_stale",
                    outage_id=outage_id,
                    schedule_version=dbm.get_version_conn(conn),
                    message=(f"schedule_version is now {dbm.get_version_conn(conn)}"
                             "; re-propose with the current version"),
                )
            plan_id = f"P{n_out_id(conn)}"
            dbm.insert_plan(
                conn,
                plan_id=plan_id,
                outage_id=outage_id,
                based_on_version=current,
                changes=changes_j,
                unresolved=unresolved_j,
            )
            dbm.stale_other_proposed_plans(outage_id, plan_id, conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        log.info("call propose outage=%s actor=%s status=proposed plan=%s version=%d", outage_id, p.name, plan_id, current)
        _audit("schedule_propose_replan", "proposed", p,
               f"outage={outage_id} plan={plan_id} based_on={current} moves={len(changes)} unresolved={len(unresolved)}", ctx,
               extras={"outage_id": outage_id, "plan_id": plan_id,
                       "based_on_version": current,
                       "move_count": len(changes),
                       "unresolved_count": len(unresolved)})
        return ProposeResult(
            status="proposed",
            plan_id=plan_id,
            outage_id=outage_id,
            based_on_version=current,
            schedule_version=current,
            changes=changes,
            unresolved=unresolved,
            is_complete=len(unresolved) == 0,
            summary=ProposalSummary(
                affected=len(changes) + len(unresolved),
                rescheduled=len(changes),
                unresolved=len(unresolved),
            ),
            generated_at=dbm.now_iso(),
            message=(
                f"plan {plan_id}: {len(changes)} move(s), {len(unresolved)} unresolved"
                if unresolved
                else f"plan {plan_id}: {len(changes)} move(s), complete"
            ),
        )
    finally:
        conn.close()


def n_out_id(conn) -> int:
    row = conn.execute("SELECT COUNT(*) AS n FROM plans").fetchone()
    return int(row["n"]) + 1


def _other_blocked_count() -> int:
    return 0


@mcp.tool()
async def schedule_propose_replan(
    outage_id: str, schedule_version: int, ctx: Context = None
) -> ProposeResult:
    """Produce (and store) a replan proposal for an outage; manager only; no side effects on bookings."""
    return await _propose_impl(outage_id, schedule_version, ctx)


# --------------------------------------------------------------------------
# Tool 4: schedule_apply_replan (with elicitation)
# --------------------------------------------------------------------------


class ConfirmModel(BaseModel):
    confirm: bool


async def _apply_impl(
    plan_id: str, schedule_version: int, ctx: Context
) -> ApplyResult:
    ensure_ready()
    p = _principal(ctx)
    current = dbm.get_version()
    if p is None or p.role != "manager":
        _audit("schedule_apply_replan", "forbidden", p,
               "manager role required" if p else "no principal", ctx,
               extras={"plan_id": plan_id})
        return ApplyResult(
            status="forbidden",
            plan_id=plan_id,
            new_version=current,
            message=_forbidden_ctx(current) if p is None else "manager role required",
        )
    conn = dbm.connect_fresh()
    try:
        plan = dbm.get_plan(plan_id, conn)
        if plan is None:
            _audit("schedule_apply_replan", "unknown_plan", p,
                   f"unknown plan {plan_id!r}", ctx,
                   extras={"plan_id": plan_id})
            return ApplyResult(
                status="unknown_plan",
                plan_id=plan_id,
                new_version=current,
                message=f"unknown plan {plan_id!r}",
            )
        changes_j, unresolved_j = _plan_json(plan)
        if plan["status"] == "applied":
            applied_changes = [
                AppliedChange(
                    booking_id=c["booking_id"],
                    user=c["user"],
                    original_equipment=c["original_equipment"],
                    new_equipment=c["new_equipment"],
                    from_start=c["original_start"],
                    from_end=c["original_end"],
                    to_start=c["new_start"],
                    to_end=c["new_end"],
                    reasons=[Reason(**r) for r in c["reasons"]],
                )
                for c in changes_j
            ]
            _audit("schedule_apply_replan", "already_applied", p,
                   f"plan {plan_id} replay; no state change", ctx,
                   extras={"plan_id": plan_id, "outage_id": plan["outage_id"],
                           "replay": True})
            return ApplyResult(
                status="already_applied",
                plan_id=plan_id,
                outage_id=plan["outage_id"],
                applied_changes=applied_changes,
                unresolved=[_unresolved_to_model(u) for u in unresolved_j],
                new_version=current,
                message=f"plan {plan_id} was already applied",
            )
        if (
            schedule_version != current
            or plan["based_on_version"] != current
            or plan["status"] == "stale"
        ):
            _audit("schedule_apply_replan", "plan_stale", p,
                   f"plan is stale (based on {plan['based_on_version']}, current {current})", ctx,
                   extras={"plan_id": plan_id, "client_version": schedule_version,
                           "current_version": current})
            return ApplyResult(
                status="plan_stale",
                plan_id=plan_id,
                outage_id=plan["outage_id"],
                new_version=current,
                message=f"plan is stale (based on {plan['based_on_version']}, current {current}); propose again",
            )

        n_ch = len(changes_j)
        n_un = len(unresolved_j)
        ask = (
            f"Apply this replan? {n_ch} booking(s) move, {n_un} stay unresolved."
        )

        confirmed = False
        elicited = False
        try:
            res = await ctx.elicit(ask, ConfirmModel)
            elicited = True
            if res.action == "accept" and res.data is not None:
                confirmed = bool(res.data.confirm)
        except Exception:  # McpError('Elicitation not supported') and friends
            elicited = False

        log.info("call apply plan=%s actor=%s elicited=%s confirmed=%s", plan_id, p.name, elicited, confirmed)
        _audit("schedule_apply_replan",
               "confirmed" if (elicited and confirmed) else "not_confirmed",
               p, f"plan={plan_id} elicited={elicited}", ctx,
               extras={"plan_id": plan_id, "elicited": elicited,
                       "confirmed": bool(elicited and confirmed)})
        if not (elicited and confirmed):
            detail = "elicitation declined" if elicited else "elicitation not supported by client"
            return ApplyResult(
                status="not_confirmed",
                plan_id=plan_id,
                outage_id=plan["outage_id"],
                new_version=current,
                message=f"apply cancelled: {detail}",
            )

        confirmed_at = dbm.now_iso()
        conn.execute("BEGIN IMMEDIATE")
        try:
            new_version = dbm.apply_changes_transaction(
                conn,
                plan=plan,
                changes=changes_j,
                unresolved_ids=[u["booking_id"] for u in unresolved_j],
                confirmed_by_id=p.user_id,
                confirmed_by_name=p.name,
                confirmed_by_role=p.role,
                confirmed_at=confirmed_at,
            )
            conn.commit()
        except ValueError as exc:
            conn.rollback()
            log.info("apply plan=%s actor=%s raced: %s", plan_id, p.name, exc)
            _audit("schedule_apply_replan", "plan_stale", p,
                   f"plan no longer proposed at apply time ({exc})", ctx,
                   extras={"plan_id": plan_id, "raced": True})
            return ApplyResult(
                status="plan_stale",
                plan_id=plan_id,
                outage_id=plan["outage_id"],
                new_version=dbm.get_version(),
                message="plan is stale (state changed while you were confirming); propose again",
            )
        except Exception as exc:
            conn.rollback()
            log.error("apply plan=%s actor=%s rollback: %s", plan_id, p.name, exc)
            return ApplyResult(
                status="apply_failed",
                plan_id=plan_id,
                outage_id=plan["outage_id"],
                new_version=current,
                message=f"transaction rolled back: {exc}",
            )
        log.info("call apply plan=%s actor=%s status=applied new_version=%s", plan_id, p.name, new_version)
        _audit("schedule_apply_replan", "applied", p,
               f"plan={plan_id} moves={n_ch} new_version={new_version}", ctx,
               extras={"plan_id": plan_id, "outage_id": plan["outage_id"],
                       "move_count": n_ch, "schedule_version": new_version})
        return ApplyResult(
            status="applied",
            plan_id=plan_id,
            outage_id=plan["outage_id"],
            applied_changes=[
                AppliedChange(
                    booking_id=c["booking_id"],
                    user=c["user"],
                    original_equipment=c["original_equipment"],
                    new_equipment=c["new_equipment"],
                    from_start=c["original_start"],
                    from_end=c["original_end"],
                    to_start=c["new_start"],
                    to_end=c["new_end"],
                    reasons=[Reason(**r) for r in c["reasons"]],
                )
                for c in changes_j
            ],
            unresolved=[_unresolved_to_model(u) for u in unresolved_j],
            new_version=new_version,
            confirmed_by=_viewer(p),
            confirmed_at=confirmed_at,
            message=f"plan {plan_id} applied; {n_ch} booking(s) moved; version {new_version}",
        )
    finally:
        conn.close()


@mcp.tool()
async def schedule_apply_replan(
    plan_id: str, schedule_version: int, ctx: Context = None
) -> ApplyResult:
    """Elicit explicit confirmation, then apply a proposed replan; manager only."""
    return await _apply_impl(plan_id, schedule_version, ctx)


# --------------------------------------------------------------------------
# Tool 5: reset_demo_data
# --------------------------------------------------------------------------


@mcp.tool()
async def reset_demo_data(ctx: Context = None) -> ResetResult:
    """Wipe and reseed the demo database; schedule_version returns to 1 (manager only)."""
    ensure_ready()
    p = _principal(ctx)
    if p is None or p.role != "manager":
        version = dbm.get_version()
        _audit("reset_demo_data", "forbidden", p,
               "manager role required" if p else "no principal", ctx)
        return ResetResult(
            status="forbidden",
            schedule_version=version,
            message=_forbidden_ctx(version) if p is None else "manager role required",
        )
    _reseed()
    log.info("call reset actor=%s status=reset", p.name)
    _audit("reset_demo_data", "reset", p, "demo reseeded; version back to 1", ctx,
           extras={"schedule_version": 1})
    # The audit row above is written AFTER the wipe (which clears audit_log) so
    # the reset itself remains the last visible audit entry.
    return ResetResult(
        status="reset",
        schedule_version=1,
        message="demo data reseeded; schedule version reset to 1",
    )


# --------------------------------------------------------------------------
# Tool 6: schedule_audit_get (who did what, when)
# --------------------------------------------------------------------------


@mcp.tool()
async def schedule_audit_get(
    limit: int = 50,
    before_id: int | None = None,
    tool_filter: str | None = None,
    ctx: Context = None,
) -> AuditGetResult:
    """Read the audit trail. Managers see everything; researchers see own + public events.

    `before_id` paginates older rows (pass next_before_id from the prior call);
    `tool_filter` narrows to one tool name.
    """
    ensure_ready()
    p = _principal(ctx)
    version = dbm.get_version()
    if p is None:
        _audit("schedule_audit_get", "forbidden", None, f"limit={limit}", ctx)
        return AuditGetResult(
            status="forbidden",
            schedule_version=version,
            entries=[],
            message=_forbidden_ctx(version),
        )
    # Defensive argument validation (schema floats a stray "1.5" through as
    # float: guard both). A bad cursor or bogus limit is client error —
    # report invalid_argument instead of silently returning zero rows.
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 200:
        _audit("schedule_audit_get", "invalid_argument", p,
               f"limit={limit!r} out of range 1..200", ctx,
               extras={"limit": limit})
        return AuditGetResult(
            status="invalid_argument",
            schedule_version=version,
            entries=[],
            message="limit must be an integer between 1 and 200",
        )
    if before_id is not None and (
        isinstance(before_id, bool) or not isinstance(before_id, int) or before_id < 1
    ):
        _audit("schedule_audit_get", "invalid_argument", p,
               f"before_id={before_id!r} is not a positive integer", ctx,
               extras={"before_id": before_id})
        return AuditGetResult(
            status="invalid_argument",
            schedule_version=version,
            entries=[],
            message="before_id must be a positive integer row id (pass next_before_id from the previous call)",
        )
    is_manager = p.role == "manager"
    # A cursor that has never existed (or was pruned) would silently page
    # nothing; surface it as invalid_argument so the client can re-sync.
    if before_id is not None:
        conn_chk = dbm.connect_fresh()
        try:
            exists = conn_chk.execute(
                "SELECT 1 FROM audit_log WHERE id = ?", (before_id,)
            ).fetchone()
        finally:
            conn_chk.close()
        if not exists:
            _audit("schedule_audit_get", "invalid_argument", p,
                   f"before_id={before_id} does not match any audit row", ctx,
                   extras={"before_id": before_id})
            return AuditGetResult(
                status="invalid_argument",
                schedule_version=version,
                entries=[],
                message="before_id does not match any audit row (or has been pruned); restart from before_id absent",
            )
    rows = dbm.audit_entries(
        limit=max(1, min(int(limit) + 1, 201)),  # +1 lookahead for next cursor
        before_id=before_id,
        actor_id=None if is_manager else p.user_id,
        tool=tool_filter or None,
    )
    # Public events always visible to researchers: outages, replans, applies, resets.
    # Single source of truth lives in constants.PUBLIC_AUDIT_TOOLS (imported by
    # db.audit_entries for the SQL boundary too) — the two copies must never
    # diverge or researcher pagination lookahead desyncs from visibility.
    PUBLIC_TOOLS = C.PUBLIC_AUDIT_TOOLS

    def visible(r: dict) -> bool:
        return is_manager or r["actor_id"] == p.user_id or r["tool"] in PUBLIC_TOOLS

    page = [r for r in rows if visible(r)]
    # Keyset pagination, newest-first: the cursor for the next page must be
    # the last row actually DISPLAYED (page[limit-1]); the next query walks
    # strictly below it (id < cursor). The pre-fix behavior pointed the
    # cursor at page[-1] of the un-truncated fetch — the +1 lookahead row —
    # which page[:limit] then never displayed, silently dropping one visible
    # row at every page boundary.
    has_more = len(page) > limit
    next_before_id = page[limit - 1]["id"] if (has_more and limit >= 1) else None
    page = page[:limit]
    def _parse_dj(raw) -> Optional[dict]:
        if not raw:
            return None
        try:
            v = json.loads(raw)
            return v if isinstance(v, dict) else None
        except (ValueError, TypeError):
            return None

    entries = [
        AuditEntry(
            at=r["at"],
            actor_id=r["actor_id"] or "",
            actor_name=r["actor_name"] or "",
            actor_role=r["actor_role"] or "",
            tool=r["tool"],
            result=r["result"],
            detail=r["detail"] or "",
            token_hint=r["token_hint"] or "-",
            detail_json=_parse_dj(r["detail_json"]),
        )
        for r in page
    ]
    _audit("schedule_audit_get", "ok", p,
           f"limit={limit} visible={len(entries)} filter={tool_filter or '-'}", ctx,
           extras={"limit": int(limit), "visible": len(entries),
                   "tool_filter": tool_filter or None,
                   "next_before_id": next_before_id})
    scope = "full trail" if is_manager else "own actions + public events"
    more = f"; older rows available via before_id={next_before_id}" if next_before_id else ""
    return AuditGetResult(
        status="ok",
        schedule_version=version,
        entries=entries,
        next_before_id=next_before_id,
        viewer=_viewer(p),
        message=f"{len(entries)} audit entr{'y' if len(entries) == 1 else 'ies'} ({scope}){more}",
    )


# --------------------------------------------------------------------------
# Tool 7: verify_audit_chain (tamper-evidence for the audit trail)
# --------------------------------------------------------------------------


@mcp.tool()
async def verify_audit_chain(ctx: Context = None) -> ChainVerifyResult:
    """Recompute the audit hash chain and report tamper status. Manager-only."""
    ensure_ready()
    p = _principal(ctx)
    version = dbm.get_version()
    if p is None or p.role != "manager":
        _audit("verify_audit_chain", "forbidden", p,
               "manager role required" if p else "no principal", ctx)
        return ChainVerifyResult(
            status="forbidden",
            schedule_version=version,
            message=_forbidden_ctx(version),
        )
    report = dbm.verify_audit_chain()
    _audit("verify_audit_chain", "ok", p,
           f"ok={report['ok']} checked={report.get('checked')} broken_at={report.get('broken_at')}",
           ctx, extras={"chain_ok": report["ok"], "checked": report.get("checked"),
                        "broken_at": report.get("broken_at"),
                        "reason": report.get("why")})
    if report["ok"]:
        msg = (f"chain intact: {report['checked']} rows verified, "
               f"head_id={report['head_id']}")
    else:
        msg = (f"TAMPER DETECTED at row {report['broken_at']} ({report.get('why')}); "
               f"verified {report.get('checked')} rows before the break")
    return ChainVerifyResult(
        status="ok",
        schedule_version=version,
        chain_ok=report["ok"],
        checked=report.get("checked", 0),
        head_id=report.get("head_id"),
        head_hash=report.get("head_hash"),
        broken_at=report.get("broken_at"),
        reason=report.get("why"),
        message=msg,
    )


# --------------------------------------------------------------------------
# Tool 8: debug_confirm
# --------------------------------------------------------------------------


@mcp.tool()
async def debug_confirm(ctx: Context = None) -> ConfirmResult:
    """M0 verification: send one elicitation and report exactly what the client answered."""
    ensure_ready()
    p = _principal(ctx)
    try:
        res = await ctx.elicit(
            "Debug: please confirm.", ConfirmModel
        )
        confirm = None
        if res.action == "accept" and res.data is not None:
            confirm = bool(res.data.confirm)
        # audited like every other elicitation outcome (decline /
        # not_supported are distinct results, never invisible to the trail)
        _audit("debug_confirm", res.action, p,
               f"elicitation action={res.action!r} confirm={confirm}", ctx)
        return ConfirmResult(
            elicited=True,
            action=res.action,
            confirm=confirm,
            message=f"client answered action={res.action!r}",
        )
    except Exception as exc:
        _audit("debug_confirm", "not_supported", p,
               f"elicitation not supported: {type(exc).__name__}: {exc}", ctx)
        return ConfirmResult(
            elicited=False,
            action="not_supported",
            confirm=None,
            message=f"elicitation not supported: {type(exc).__name__}: {exc}",
        )


# --------------------------------------------------------------------------
# entry point helpers
# --------------------------------------------------------------------------


def build_app():
    """ASGI app (Streamable HTTP at /mcp) wrapped in the transport guard."""
    initialize_storage()
    return TransportGuardMiddleware(mcp.streamable_http_app())


def register_all_tools(target) -> None:
    """Register every demo tool onto a (possibly fresh) FastMCP instance.

    Used by build_app's module singleton implicitly via the decorators, and
    explicitly by tests that need their own in-process FastMCP instance (the
    StreamableHTTPSessionManager behind each instance is single-shot per
    process, so a second test module cannot reuse the singleton).
    Registration order matches tool-numbering in the contract.
    """
    target.add_tool(schedule_get)
    target.add_tool(equipment_report_outage)
    target.add_tool(schedule_propose_replan)
    target.add_tool(schedule_apply_replan)
    target.add_tool(reset_demo_data)
    target.add_tool(schedule_audit_get)
    target.add_tool(verify_audit_chain)
    target.add_tool(debug_confirm)


def get_session_manager():
    return mcp.session_manager


def main() -> None:
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", default=None)
    args, _ = parser.parse_known_args()
    if args.db:
        os.environ["SER_DB_PATH"] = args.db
    initialize_storage()
    app = TransportGuardMiddleware(mcp.streamable_http_app())
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
