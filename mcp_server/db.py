"""SQLite persistence: schema, version counter, transactions.

All timestamps persisted as full ISO 8601 strings with timezone offset.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, List, Optional

from . import constants as C

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
"""

_lock = threading.Lock()
_db_path: str = "server.db"


def configure(db_path: Optional[str] = None) -> None:
    global _db_path
    if db_path is None:
        db_path = os.environ.get("SER_DB_PATH", "server.db")
    _db_path = db_path


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
    conn = sqlite3.connect(_db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Optional[str] = None) -> None:
    configure(db_path)
    with _lock:
        conn = connect()
        try:
            conn.executescript(_SCHEMA)
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


def get_version() -> int:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT value FROM meta WHERE key=?", (C.DB_KEY_VERSION,)
        ).fetchone()
        return int(row["value"]) if row else 1
    finally:
        conn.close()


def set_version(value: int) -> None:
    with _lock:
        conn = connect()
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
    conn = connect()
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
    """Single BEGIN IMMEDIATE-per-call transaction body; caller wraps."""
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
    ):
        conn.execute(f"DELETE FROM {table}")
