"""Seed data — the plan §3/§8 demo scenario on SER_DEMO_DATE.

Wall times stay 09:00–18:00 in the configured zone. The offset is the real
one for that date (BST or GMT), not a hard-coded +01:00.

Permissions: Wang = confocal-a ONLY (otherwise engine would pick B over
the expected A 16:00 for B4). Chen = researcher [A,B]; Li = researcher [B];
user-manager = manager [A,B] with English display name "Facility Manager"
(merges plan §3 table with §8 account-switcher requirement).
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from . import constants as C
from .timeutil import local_iso

_USERS = [
    ("user-manager", "Facility Manager", "manager", C.TOKEN_MANAGER),
    ("user-chen", "Chen", "researcher", C.TOKEN_CHEN),
    ("user-wang", "Wang", "researcher", C.TOKEN_WANG),
    ("user-li", "Li", "researcher", C.TOKEN_LI),
]

_EQUIPMENT = [
    ("confocal-a", C.UNIT_ID, "Confocal Microscope A", "09:00", "18:00", 15),
    ("confocal-b", C.UNIT_ID, "Confocal Microscope B", "09:00", "18:00", 15),
]

# Wall times only. seed() stamps them onto the demo date in the configured zone.
_BOOKINGS = [
    # B1 Wang on A 09:00-10:00, no deadline, movable
    ("B1", "user-wang", "confocal-a", "09:00", "10:00", None, 1, "confirmed"),
    # B2 Chen on A 10:00-11:00, deadline 13:00, movable
    ("B2", "user-chen", "confocal-a", "10:00", "11:00", "13:00", 1, "confirmed"),
    # B3 Li on B 10:00-11:00, NOT movable, no deadline
    ("B3", "user-li", "confocal-b", "10:00", "11:00", None, 0, "confirmed"),
    # B4 Wang on A 11:00-12:00 (used to test the B12:30 vs A16:00 branch),
    # deadline 18:00, movable
    ("B4", "user-wang", "confocal-a", "11:00", "12:00", "18:00", 1, "confirmed"),
    # B5 Li on B 14:00-15:00
    ("B5", "user-li", "confocal-b", "14:00", "15:00", None, 1, "confirmed"),
    # B6 Chen on B 15:00-16:00
    ("B6", "user-chen", "confocal-b", "15:00", "16:00", None, 1, "confirmed"),
]

_PERMISSIONS = {
    "confocal-a": {"user-manager", "user-chen", "user-wang"},
    "confocal-b": {"user-manager", "user-chen", "user-li"},
}


def seed(conn: sqlite3.Connection, db_path: Optional[str] = None) -> None:
    """Wipe and re-seed the demo database. Caller owns commit/rollback."""
    from . import db as dbm

    dbm.wipe_for_reset(conn)

    conn.execute(
        "INSERT INTO units(id, name, timezone) VALUES (?,?,?)",
        (C.UNIT_ID, C.UNIT_NAME, C.DEMO_TZ),
    )
    for uid, name, role, token in _USERS:
        conn.execute(
            "INSERT INTO users(id, name, role, token) VALUES (?,?,?,?)",
            (uid, name, role, token),
        )
    for eid, unit_id, name, bs, be, buf in _EQUIPMENT:
        conn.execute(
            "INSERT INTO equipment(id, unit_id, name, available_start,"
            " available_end, buffer_minutes) VALUES (?,?,?,?,?,?)",
            (eid, unit_id, name, bs, be, buf),
        )
    for bid, uid, eid, start_hm, end_hm, deadline_hm, movable, status in _BOOKINGS:
        start = local_iso(C.DEMO_DATE, start_hm)
        end = local_iso(C.DEMO_DATE, end_hm)
        deadline = local_iso(C.DEMO_DATE, deadline_hm) if deadline_hm else None
        conn.execute(
            "INSERT INTO bookings(id, user_id, equipment_id, booking_date,"
            " original_start, original_end, current_start, current_end,"
            " deadline, movable, status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                bid,
                uid,
                eid,
                C.DEMO_DATE,
                start,
                end,
                start,
                end,
                deadline,
                movable,
                status,
            ),
        )
    conn.execute(
        "INSERT INTO meta(key, value) VALUES (?, '1')", (C.DB_KEY_VERSION,)
    )


def user_permissions() -> dict[str, set[str]]:
    """equipment_id -> set of user_ids allowed (derived from _PERMISSIONS)."""
    return {k: set(v) for k, v in _PERMISSIONS.items()}


def user_names() -> dict[str, str]:
    return {u[0]: u[1] for u in _USERS}
