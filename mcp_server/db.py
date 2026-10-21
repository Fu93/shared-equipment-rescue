"""SQLite persistence: schema, version counter, transactions.

All timestamps persisted as full ISO 8601 strings with timezone offset.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import List, Optional

from . import constants as C

GENESIS_HASH = "0" * 64

_SCHEMA = """
CREATE TABLE IF NOT EXISTS units (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    timezone TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('manager','researcher')),
    token TEXT UNIQUE NOT NULL
);
CREATE TABLE IF NOT EXISTS equipment (
    id TEXT PRIMARY KEY,
    unit_id TEXT NOT NULL REFERENCES units(id),
    name TEXT NOT NULL,
    available_start TEXT NOT NULL,
    available_end TEXT NOT NULL,
    buffer_minutes INTEGER NOT NULL DEFAULT 15
);
CREATE TABLE IF NOT EXISTS bookings (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    equipment_id TEXT NOT NULL REFERENCES equipment(id),
    booking_date TEXT NOT NULL,
    original_start TEXT NOT NULL,
    original_end TEXT NOT NULL,
    current_start TEXT NOT NULL,
    current_end TEXT NOT NULL,
    deadline TEXT,
    movable INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'confirmed'
        CHECK(status IN ('confirmed','blocked','unresolved'))
);
CREATE TABLE IF NOT EXISTS outages (
    id TEXT PRIMARY KEY,
    equipment_id TEXT NOT NULL REFERENCES equipment(id),
    start TEXT NOT NULL,
    end TEXT NOT NULL,
    reason TEXT,
    created_by TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plans (
    id TEXT PRIMARY KEY,
    outage_id TEXT NOT NULL REFERENCES outages(id),
    based_on_version INTEGER NOT NULL,
    changes TEXT NOT NULL,
    unresolved TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'proposed'
        CHECK(status IN ('proposed','applied','stale')),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS change_log (
    id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    booking_id TEXT NOT NULL,
    before_change TEXT NOT NULL,
    after_change TEXT NOT NULL,
    confirmed_by TEXT NOT NULL,
    confirmed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    actor_id TEXT,
    actor_name TEXT,
    actor_role TEXT,
    tool TEXT NOT NULL,
    result TEXT NOT NULL,
    detail TEXT,
    token_hint TEXT,
    detail_json TEXT,
    prev_hash TEXT,
    hash TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_at ON audit_log(at);
CREATE INDEX IF NOT EXISTS idx_audit_id ON audit_log(id);

CREATE TABLE IF NOT EXISTS transport_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    peer TEXT NOT NULL,
    event TEXT NOT NULL,
    why TEXT NOT NULL,
    path TEXT,
    prev_hash TEXT,
    hash TEXT
);
CREATE INDEX IF NOT EXISTS idx_transport_at ON transport_log(at);
"""

_lock = threading.Lock()
_db_path: str = "server.db"
# Thread-local connection cache: each worker thread (uvicorn's thread pool for
# sync handlers / FastAPI's anyio worker threads) reuses one sqlite connection
# instead of opening a fresh one per call. Check_same_thread stays True because
# a thread-local handle is only ever touched by its own thread. configure()
# clears the cache so tests pointing SER_DB_PATH elsewhere never reuse handles.
_local = threading.local()


def configure(db_path: Optional[str] = None) -> None:
    global _db_path
    if db_path is None:
        db_path = os.environ.get("SER_DB_PATH", "server.db")
    if db_path == _db_path:
        return
    _db_path = db_path
    _local.__dict__.pop("conn", None)


def now_iso() -> str:
    """Wall clock for created_at/confirmed_at fields.

    Tests may freeze time by setting SER_FROZEN_NOW (ISO 8601 with offset);
    production never sets it, so this stays the real UTC clock.
    """
    frozen = os.environ.get("SER_FROZEN_NOW")
    if frozen:
        return frozen
    return datetime.now(timezone.utc).isoformat()


def fresh_ids_suffix() -> str:
    return datetime.now(timezone.utc).strftime("%H%M%S%f")[:10]


def connect() -> sqlite3.Connection:
    """Per-thread cached connection (`conn()` style reuse).

    Callers must keep the same ownership contract as before: whoever opens a
    transaction owns committing/closing it. For plain `connect()` handles that
    close() at the end, closing a cached handle would poison the thread's
    later use — so callers that close explicitly go through connect_fresh().
    """
    conn = getattr(_local, "conn", None)
    if conn is not None and _db_path == getattr(_local, "conn_path", None):
        return conn
    fresh = connect_fresh()
    _local.conn = fresh
    _local.conn_path = _db_path
    return fresh


def connect_fresh() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL lets concurrent reads proceed while a write transaction holds the
    # write lock — the demo's 6-parallel-client probe never blocks reads.
    try:
        row = conn.execute("PRAGMA journal_mode=WAL").fetchone()
        if row is None or str(row[0]).lower() != "wal":
            # in-memory DBs (some tests) can't switch; fall back silently
            pass
    except sqlite3.Error:
        pass
    return conn


def init_db(db_path: Optional[str] = None) -> None:
    configure(db_path)
    with _lock:
        conn = connect_fresh()
        try:
            conn.executescript(_SCHEMA)
            _migrate(conn)
            row = conn.execute(
                "SELECT value FROM meta WHERE key=?", (C.DB_KEY_VERSION,)
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO meta(key, value) VALUES (?, '1')",
                    (C.DB_KEY_VERSION,),
                )
            conn.commit()
        finally:
            conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """Additive column migrations for databases created by older builds."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(audit_log)")}
    had_hash = "hash" in cols
    if "prev_hash" not in cols:
        conn.execute("ALTER TABLE audit_log ADD COLUMN prev_hash TEXT")
    if "hash" not in cols:
        conn.execute("ALTER TABLE audit_log ADD COLUMN hash TEXT")
    if "detail_json" not in cols:
        conn.execute("ALTER TABLE audit_log ADD COLUMN detail_json TEXT")
    if not had_hash:
        # not a fresh table — rebuild the chain over existing rows so
        # tamper evidence covers pre-migration history
        rows = conn.execute(
            "SELECT id, at, actor_id, tool, result, detail, token_hint"
            " FROM audit_log ORDER BY id ASC"
        ).fetchall()
        prev = GENESIS_HASH
        for r in rows:
            h = audit_hash(prev, r[0], r[1], r[3], r[4], r[2] or "",
                           r[5] or "", r[6] or "")
            conn.execute("UPDATE audit_log SET prev_hash=?, hash=? WHERE id=?",
                         (prev, h, r[0]))
            prev = h


def get_version() -> int:
    conn = connect_fresh()
    try:
        row = conn.execute(
            "SELECT value FROM meta WHERE key=?", (C.DB_KEY_VERSION,)
        ).fetchone()
        return int(row["value"]) if row else 1
    finally:
        conn.close()


def get_version_conn(conn: sqlite3.Connection) -> int:
    """Version read through an existing connection (inside a transaction)."""
    row = conn.execute(
        "SELECT value FROM meta WHERE key=?", (C.DB_KEY_VERSION,)
    ).fetchone()
    return int(row["value"]) if row else 1


def set_version(value: int) -> None:
    with _lock:
        conn = connect_fresh()
        try:
            conn.execute(
                "UPDATE meta SET value=? WHERE key=?", (str(value), C.DB_KEY_VERSION)
            )
            conn.commit()
        finally:
            conn.close()


def bump_version(conn: sqlite3.Connection) -> int:
    conn.execute(
        "UPDATE meta SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT) WHERE key=?",
        (C.DB_KEY_VERSION,),
    )
    row = conn.execute(
        "SELECT value FROM meta WHERE key=?", (C.DB_KEY_VERSION,)
    ).fetchone()
    return int(row["value"])


def users_query() -> List[dict]:
    conn = connect_fresh()
    try:
        rows = conn.execute("SELECT * FROM users").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def equipment_for_unit(unit_id: str, conn: sqlite3.Connection) -> List[dict]:
    rows = conn.execute(
        "SELECT * FROM equipment WHERE unit_id=? ORDER BY id", (unit_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def bookings_for_date(date_str: str, conn: sqlite3.Connection) -> List[dict]:
    rows = conn.execute(
        "SELECT * FROM bookings WHERE booking_date=? ORDER BY current_start",
        (date_str,),
    ).fetchall()
    return [dict(r) for r in rows]


def bookings_for_equipment_date(
    equipment_id: str, date_str: str, conn: sqlite3.Connection
) -> List[dict]:
    rows = conn.execute(
        "SELECT * FROM bookings WHERE equipment_id=? AND booking_date=?"
        " ORDER BY current_start",
        (equipment_id, date_str),
    ).fetchall()
    return [dict(r) for r in rows]


def outages_for_date(date_str: str, conn: sqlite3.Connection) -> List[dict]:
    rows = conn.execute(
        "SELECT * FROM outages WHERE start LIKE ? ORDER BY start",
        (f"{date_str}%",),
    ).fetchall()
    return [dict(r) for r in rows]


def get_outage(outage_id: str, conn: sqlite3.Connection) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM outages WHERE id=?", (outage_id,)
    ).fetchone()
    return dict(row) if row else None


def get_plan(plan_id: str, conn: sqlite3.Connection) -> Optional[dict]:
    row = conn.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
    return dict(row) if row else None


def proposed_plan_for(
    outage_id: str, based_on_version: int, conn: sqlite3.Connection
) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM plans WHERE outage_id=? AND based_on_version=?"
        " AND status='proposed'",
        (outage_id, based_on_version),
    ).fetchone()
    return dict(row) if row else None


def stale_other_proposed_plans(
    outage_id: str, keep_plan_id: str, conn: sqlite3.Connection
) -> None:
    conn.execute(
        "UPDATE plans SET status='stale' WHERE outage_id=? AND status='proposed'"
        " AND id<>?",
        (outage_id, keep_plan_id),
    )


def stale_all_proposed_plans(outage_id: str, conn: sqlite3.Connection) -> None:
    conn.execute(
        "UPDATE plans SET status='stale' WHERE outage_id=? AND status='proposed'",
        (outage_id,),
    )


def insert_outage(
    conn: sqlite3.Connection,
    *,
    outage_id: str,
    equipment_id: str,
    start: str,
    end: str,
    reason: Optional[str],
    created_by: str,
) -> None:
    conn.execute(
        "INSERT INTO outages(id, equipment_id, start, end, reason, created_by,"
        " created_at) VALUES (?,?,?,?,?,?,?)",
        (outage_id, equipment_id, start, end, reason, created_by, now_iso()),
    )


def block_bookings(conn: sqlite3.Connection, booking_ids: List[str]) -> None:
    for bid in booking_ids:
        conn.execute(
            "UPDATE bookings SET status='blocked' WHERE id=? AND status='confirmed'",
            (bid,),
        )


def insert_plan(
    conn: sqlite3.Connection,
    *,
    plan_id: str,
    outage_id: str,
    based_on_version: int,
    changes: List[dict],
    unresolved: List[dict],
    status: str = "proposed",
) -> None:
    conn.execute(
        "INSERT INTO plans(id, outage_id, based_on_version, changes, unresolved,"
        " status, created_at) VALUES (?,?,?,?,?,?,?)",
        (
            plan_id,
            outage_id,
            based_on_version,
            json.dumps(changes, ensure_ascii=False),
            json.dumps(unresolved, ensure_ascii=False),
            status,
            now_iso(),
        ),
    )


def apply_changes_transaction(
    conn: sqlite3.Connection,
    *,
    plan: dict,
    changes: List[dict],
    unresolved_ids: List[str],
    confirmed_by_id: str,
    confirmed_by_name: str,
    confirmed_by_role: str,
    confirmed_at: str,
) -> int:
    """Single BEGIN IMMEDIATE-per-call transaction body; caller wraps.

    Re-reads the plan row under the write lock and refuses to apply unless it
    is still 'proposed' — the pre-check in server._apply_impl happens before
    elicitation, so two concurrent applies (or an apply racing a reset) could
    otherwise both pass and double-bump the schedule version.
    Raises ValueError('plan not proposed live') when the plan is no longer
    applicable; the caller must treat the whole txn as failed (rollback).
    """
    live = conn.execute(
        "SELECT status, based_on_version FROM plans WHERE id=?", (plan["id"],)
    ).fetchone()
    if live is None or live["status"] != "proposed":
        raise ValueError("plan not proposed live")
    for ch in changes:
        before = conn.execute(
            "SELECT current_start, current_end, equipment_id FROM bookings WHERE id=?",
            (ch["booking_id"],),
        ).fetchone()
        if before is None:
            raise RuntimeError(f"apply: booking {ch['booking_id']} vanished")
        conn.execute(
            "UPDATE bookings SET current_start=?, current_end=?, equipment_id=?,"
            " status='confirmed' WHERE id=?",
            (
                ch["new_start"],
                ch["new_end"],
                ch["new_equipment"],
                ch["booking_id"],
            ),
        )
        after = {
            "booking_id": ch["booking_id"],
            "equipment_id": ch["new_equipment"],
            "current_start": ch["new_start"],
            "current_end": ch["new_end"],
            "status": "confirmed",
        }
        conn.execute(
            "INSERT INTO change_log(id, plan_id, booking_id, before_change,"
            " after_change, confirmed_by, confirmed_at) VALUES (?,?,?,?,?,?,?)",
            (
                f"chg-{plan['id']}-{ch['booking_id']}",
                plan["id"],
                ch["booking_id"],
                json.dumps(dict(before), ensure_ascii=False),
                json.dumps(after, ensure_ascii=False),
                f"{confirmed_by_id}|{confirmed_by_name}|{confirmed_by_role}",
                confirmed_at,
            ),
        )
    for bid in unresolved_ids:
        conn.execute(
            "UPDATE bookings SET status='unresolved' WHERE id=?", (bid,)
        )
    conn.execute(
        "UPDATE plans SET status='applied' WHERE id=?", (plan["id"],)
    )
    return bump_version(conn)


def wipe_for_reset(conn: sqlite3.Connection) -> None:
    for table in (
        "change_log",
        "plans",
        "outages",
        "bookings",
        "equipment",
        "users",
        "units",
        "meta",
        "audit_log",
    ):
        conn.execute(f"DELETE FROM {table}")
    # transport_log is deliberately NOT wiped: transport rejections are keyed
    # by peer address, not by demo actor, so they are not part of the demo
    # workspace state a reset restores. An operator clearing the demo must not
    # erase the evidence of who was hammering the door.


# ---------------------------------------------------------------------------
# audit log (Phase 2): every tool call gets one row — who, what, outcome.
# Additive only: audit failures are swallowed so they can never break a tool
# response (the log must observe, not intervene).
# ---------------------------------------------------------------------------


def audit_hash(prev_hash: str, audit_id: int, at: str, tool: str, result: str,
               actor_id: str, detail: str, token_hint: str) -> str:
    """Chain hash: each row's hash covers its content and the prior row's hash.

    Tampering with any row (edit, delete, reorder, splice) breaks every hash
    after it, which verify_audit_chain() detects. `detail` participates but
    `detail_json` does not: the JSON blob is a derived, machine-readable mirror
    of the human string, and keeping it out of the hash lets the detail
    structure evolve without invalidating the chain.
    """
    h = hashlib.sha256()
    h.update(prev_hash.encode())
    h.update(f"|{audit_id}|{at}|{tool}|{result}|{actor_id}|{detail}|{token_hint}".encode())
    return h.hexdigest()


def record_audit(
    conn: sqlite3.Connection,
    *,
    tool: str,
    result: str,
    actor_id: str = "",
    actor_name: str = "",
    actor_role: str = "",
    detail: str = "",
    token_hint: str = "",
    detail_json: str = "",
) -> None:
    prev = conn.execute(
        "SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    prev_hash = (prev[0] if prev else GENESIS_HASH) or GENESIS_HASH
    at = now_iso()
    conn.execute(
        "INSERT INTO audit_log(at, actor_id, actor_name, actor_role, tool,"
        " result, detail, token_hint, detail_json, prev_hash)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (at, actor_id, actor_name, actor_role, tool, result,
         detail, token_hint, detail_json[:800], prev_hash),
    )
    # backfill hash on the row we just added (id is now known)
    row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    h = audit_hash(prev_hash, row_id, at, tool, result, actor_id, detail,
                   token_hint)
    conn.execute("UPDATE audit_log SET hash=? WHERE id=?", (h, row_id))


def record_audit_standalone(
    *,
    tool: str,
    result: str,
    actor_id: str = "",
    actor_name: str = "",
    actor_role: str = "",
    detail: str = "",
    token_hint: str = "",
    detail_json: str = "",
) -> None:
    """Best-effort audit write with its own connection. Never raises."""
    try:
        conn = connect_fresh()
        try:
            conn.execute("BEGIN IMMEDIATE")
            record_audit(
                conn,
                tool=tool,
                result=result,
                actor_id=actor_id,
                actor_name=actor_name,
                actor_role=actor_role,
                detail=detail,
                token_hint=token_hint,
                detail_json=detail_json,
            )
            prune_audit_log(conn)
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error:
        pass


def audit_entries(
    limit: int = 100,
    before_id: Optional[int] = None,
    actor_id: Optional[str] = None,
    tool: Optional[str] = None,
) -> List[dict]:
    """Audit entries newest-first with cursor pagination + optional filters.

    `before_id` returns rows with id < before_id (for "load older" paging).
    When `actor_id` is set (researcher view) the query returns that actor's
    rows PLUS the public tools anyone may see — mirroring the visibility rule
    in server.schedule_audit_get, so the "own + public events" contract holds
    even when the whole page is filtered at the SQL boundary.
    """
    conn = connect_fresh()
    try:
        sql = ("SELECT id, at, actor_id, actor_name, actor_role, tool, result,"
               " detail, token_hint, detail_json FROM audit_log")
        where, params = [], []
        if before_id is not None:
            where.append("id < ?")
            params.append(before_id)
        if actor_id:
            where.append("(actor_id = ? OR tool IN (?,?,?,?))")
            params.extend([
                actor_id,
                "equipment_report_outage", "schedule_propose_replan",
                "schedule_apply_replan", "reset_demo_data",
            ])
        if tool:
            where.append("tool = ?")
            params.append(tool)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


AUDIT_RETENTION_ROWS = 10000

def prune_audit_log(conn: sqlite3.Connection) -> None:
    """Keep the newest AUDIT_RETENTION_ROWS rows; roll off older ones.

    Called opportunistically after audit inserts; cheap when under budget.
    The chain verifier treats the rolled-off boundary as a new chain head, so
    pruning (which always removes a contiguous oldest prefix) never reads as
    tampering.
    """
    conn.execute(
        "DELETE FROM audit_log WHERE id <= ("
        " SELECT id FROM audit_log ORDER BY id DESC LIMIT 1 OFFSET ?)",
        (AUDIT_RETENTION_ROWS,),
    )


def audit_rows_ascending() -> List[dict]:
    """All audit rows oldest-first with hash fields — the whole chain."""
    conn = connect_fresh()
    try:
        rows = conn.execute(
            "SELECT id, at, actor_id, actor_name, actor_role, tool, result,"
            " detail, token_hint, detail_json, prev_hash, hash"
            " FROM audit_log ORDER BY id ASC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def verify_audit_chain() -> dict:
    """Validate the hash chain end-to-end.

    Tamper detection relies on two invariants:
    1. each row's stored hash must recompute from its own content + prev_hash;
    2. prev_hash linkage must be unbroken *and ids contiguous* inside the run —
       retention removes only a contiguous oldest prefix, so the single allowed
       gap is at the head of the surviving run (id k+1 whose predecessor k was
       rolled off, i.e. every lower id absent).
    """
    rows = audit_rows_ascending()
    prev_hash_seen: Optional[str] = None
    prev_id: Optional[int] = None
    for i, r in enumerate(rows):
        expected = audit_hash(
            r["prev_hash"] or GENESIS_HASH, r["id"], r["at"], r["tool"],
            r["result"], r["actor_id"] or "", r["detail"] or "",
            r["token_hint"] or "",
        )
        if (r["hash"] or "") != expected:
            return {"ok": False, "head_id": rows[-1]["id"] if rows else None,
                    "broken_at": r["id"], "checked": i, "why": "hash mismatch",
                    "head_hash": rows[-1]["hash"] if rows else None}
        if prev_hash_seen is not None:
            link_ok = (r["prev_hash"] or "") == prev_hash_seen
            ids_contiguous = prev_id is not None and r["id"] == prev_id + 1
            if ids_contiguous and not link_ok:
                return {"ok": False, "head_id": rows[-1]["id"] if rows else None,
                        "broken_at": r["id"], "checked": i,
                        "why": "prev_hash mismatch",
                        "head_hash": rows[-1]["hash"] if rows else None}
            if not ids_contiguous and i != 0:
                # interior id gap = a middle row was deleted (retention may
                # only remove the contiguous oldest prefix, i.e. before row 0)
                return {"ok": False, "head_id": rows[-1]["id"] if rows else None,
                        "broken_at": r["id"], "checked": i, "why": "row deleted",
                        "head_hash": rows[-1]["hash"] if rows else None}
        prev_hash_seen = r["hash"]
        prev_id = r["id"]
    return {"ok": True, "head_id": rows[-1]["id"] if rows else None,
            "broken_at": None, "checked": len(rows), "why": None,
            "head_hash": rows[-1]["hash"] if rows else None}


# ---------------------------------------------------------------------------
# transport ledger: a SECOND hash-chained log, one row per transport-layer
# rejection (403 origin / 403 host / 429 rate). It is deliberately separate
# from audit_log:
#   * transport events are per-peer-address, not per-demo-actor;
#   * they can be high-frequency (rate limiting), which would drown the tool
#     trail if interleaved;
#   * wipe_for_reset must NOT erase them (retained evidence).
# Same tamper-evidence mechanism: sha256(prev|id|at|peer|event|why|path).
# ---------------------------------------------------------------------------

TRANSPORT_PRUNE_ROWS = 5000


def transport_hash(prev_hash: str, tid: int, at: str, peer: str,
                   event: str, why: str, path: str) -> str:
    h = hashlib.sha256()
    h.update(prev_hash.encode())
    h.update(f"|{tid}|{at}|{peer}|{event}|{why}|{path}".encode())
    return h.hexdigest()


def record_transport_event(
    conn: sqlite3.Connection,
    *,
    peer: str,
    event: str,
    why: str,
    path: str = "",
) -> None:
    """Append one transport rejection to the transport ledger (inside caller txn)."""
    prev = conn.execute(
        "SELECT hash FROM transport_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    prev_hash = (prev[0] if prev else GENESIS_HASH) or GENESIS_HASH
    at = now_iso()
    conn.execute(
        "INSERT INTO transport_log(at, peer, event, why, path, prev_hash)"
        " VALUES (?,?,?,?,?,?)",
        (at, peer, event, why, path[:200], prev_hash),
    )
    row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    h = transport_hash(prev_hash, row_id, at, peer, event, why, path[:200])
    conn.execute("UPDATE transport_log SET hash=? WHERE id=?", (h, row_id))


_transport_write_lock = threading.Lock()


def record_transport_event_standalone(
    *,
    peer: str,
    event: str,
    why: str,
    path: str = "",
) -> None:
    """Best-effort transport-ledger write with its own connection. Never raises.

    Called from TransportGuardMiddleware._reject on the request path — it must
    be fast (own short txn, no long lock) and must NEVER break or delay the
    HTTP response itself.
    """
    try:
        with _transport_write_lock:
            conn = connect_fresh()
            try:
                conn.execute("BEGIN IMMEDIATE")
                record_transport_event(
                    conn, peer=peer, event=event, why=why, path=path
                )
                conn.execute(
                    "DELETE FROM transport_log WHERE id <= ("
                    " SELECT id FROM transport_log ORDER BY id DESC LIMIT 1"
                    " OFFSET ?)",
                    (TRANSPORT_PRUNE_ROWS,),
                )
                conn.commit()
            finally:
                conn.close()
    except sqlite3.Error:
        pass


def transport_events(limit: int = 50) -> List[dict]:
    """Newest-first snapshot of transport-layer rejections (metrics/diagnostics)."""
    conn = connect_fresh()
    try:
        rows = conn.execute(
            "SELECT id, at, peer, event, why, path FROM transport_log"
            " ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def verify_transport_chain() -> dict:
    """Same two-invariant check as verify_audit_chain, over transport_log."""
    conn = connect_fresh()
    try:
        rows = conn.execute(
            "SELECT id, at, peer, event, why, path, prev_hash, hash"
            " FROM transport_log ORDER BY id ASC"
        ).fetchall()
    finally:
        conn.close()
    prev_hash_seen: Optional[str] = None
    prev_id: Optional[int] = None
    for i, r in enumerate(rows):
        expected = transport_hash(
            r["prev_hash"] or GENESIS_HASH, r["id"], r["at"], r["peer"],
            r["event"], r["why"], r["path"] or "",
        )
        if (r["hash"] or "") != expected:
            return {"ok": False, "head_id": rows[-1]["id"] if rows else None,
                    "broken_at": r["id"], "checked": i, "why": "hash mismatch",
                    "head_hash": rows[-1]["hash"] if rows else None}
        if prev_hash_seen is not None:
            link_ok = (r["prev_hash"] or "") == prev_hash_seen
            ids_contiguous = prev_id is not None and r["id"] == prev_id + 1
            if ids_contiguous and not link_ok:
                return {"ok": False, "head_id": rows[-1]["id"] if rows else None,
                        "broken_at": r["id"], "checked": i,
                        "why": "prev_hash mismatch",
                        "head_hash": rows[-1]["hash"] if rows else None}
            if not ids_contiguous and i != 0:
                return {"ok": False, "head_id": rows[-1]["id"] if rows else None,
                        "broken_at": r["id"], "checked": i, "why": "row deleted",
                        "head_hash": rows[-1]["hash"] if rows else None}
        prev_hash_seen = r["hash"]
        prev_id = r["id"]
    return {"ok": True, "head_id": rows[-1]["id"] if rows else None,
            "broken_at": None, "checked": len(rows), "why": None,
            "head_hash": rows[-1]["hash"] if rows else None}


def transport_counts() -> dict:
    """Event-type counters over transport_log (whole ledger, incl. pruned head)."""
    conn = connect_fresh()
    try:
        rows = conn.execute(
            "SELECT event, COUNT(*) AS n FROM transport_log GROUP BY event"
        ).fetchall()
        counts = {r["event"]: r["n"] for r in rows}
        counts["total"] = sum(counts.values())
        return counts
    finally:
        conn.close()
