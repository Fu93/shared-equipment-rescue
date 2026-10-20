"""Engine boundary supplements (Phase 1/3): behavior-locked assertions for
degenerate/out-of-window/boundary conditions that current tests don't pin."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import pytest  # noqa: E402

from mcp_server.engine import (  # noqa: E402
    Booking,
    Equipment,
    Outage,
    compute_plan,
)
from mcp_server import constants as C  # noqa: E402
from mcp_server import seed as seedm  # noqa: E402
from mcp_server.timeutil import hhmm_boundary, fmt  # noqa: E402

D = C.DEMO_DATE
T = lambda hhmm: fmt(hhmm_boundary(D, hhmm))


def _mini(booking_hhmm=("10:00", "11:00")):
    """Minimal world: one A-only user, one booking, two equipment."""
    equipment = {
        "confocal-a": Equipment("confocal-a", "Confocal A", "09:00", "18:00", 15),
        "confocal-b": Equipment("confocal-b", "Confocal B", "09:00", "18:00", 15),
    }
    s, e = booking_hhmm
    bookings = [Booking(
        id="X1", user_id="user-wang", equipment_id="confocal-a",
        start=T(s), end=T(e), deadline=None, movable=True, status="confirmed",
    )]
    return __import__("mcp_server.engine", fromlist=["World"]).World(
        equipment=equipment,
        outages=[],
        bookings=bookings,
        user_names=seedm.user_names(),
        user_permissions=seedm.user_permissions(),
        day_open={eid: hhmm_boundary(D, eq.available_start) for eid, eq in equipment.items()},
        day_close={eid: hhmm_boundary(D, eq.available_end) for eid, eq in equipment.items()},
    )


def _outage(eid, s, e):
    return Outage(id="OZ", equipment_id=eid, start=T(s), end=T(e), reason="probe")


def test_zero_duration_outage_moves_booking_within_outage_instant():
    """Zero-length outage [10:30,10:30) half-open-overlaps X1 (10-11), so the
    engine moves it to the outage instant (10:30). NOTE: tool layer rejects
    end<=start before this can happen (invalid_argument) — this pins the PURE
    engine semantics for degenerate direct input, no server path touches it."""
    w = _mini()
    changes, unresolved = compute_plan(w, _outage("confocal-a", "10:30", "10:30"))
    assert unresolved == []
    assert len(changes) == 1
    c = changes[0]
    assert c.booking_id == "X1"
    assert c.new_start == T("10:30") and c.new_end == T("11:30")


def test_outage_completely_outside_booking_leaves_it():
    """Outage disjoint from booking window => no effect at all."""
    w = _mini(("10:00", "11:00"))
    changes, unresolved = compute_plan(w, _outage("confocal-a", "12:00", "13:00"))
    assert changes == [] and unresolved == []


def test_outage_touching_booking_end_half_open_not_affected():
    """Half-open semantics: outage starting exactly at booking end does NOT
    overlap the booking ([10,11) vs [11,12))."""
    w = _mini(("10:00", "11:00"))
    changes, unresolved = compute_plan(w, _outage("confocal-a", "11:00", "12:00"))
    assert changes == [] and unresolved == []


def test_outage_touching_booking_start_half_open_not_affected():
    """Outage ending exactly at booking start does NOT overlap ([09,10) vs [10,11))."""
    w = _mini(("10:00", "11:00"))
    changes, unresolved = compute_plan(w, _outage("confocal-a", "09:00", "10:00"))
    assert changes == [] and unresolved == []


def test_full_day_outage_moves_only_then_reports():
    """Whole-day outage on A: Wang is A-only => unresolved no_permission on B,
    no_slot_today on A (booked-out day)."""
    import mcp_server.engine as eng
    w = _mini(("11:00", "12:00"))
    changes, unresolved = compute_plan(
        w, _outage("confocal-a", "09:00", "18:00"))
    assert changes == []
    assert len(unresolved) == 1
    u = unresolved[0]
    assert u.booking_id == "X1"
    statuses = {e.equipment_id: e.status for e in u.earliest_possible}
    assert statuses["confocal-b"] == "no_permission"
    assert statuses["confocal-a"] == "no_slot_today"


def test_buffer_zero_equipment_allows_back_to_back():
    """buffer_minutes=0: a moved booking may start exactly when the previous ends."""
    equipment = {
        "confocal-a": Equipment("confocal-a", "Confocal A", "09:00", "18:00", 0),
        "confocal-b": Equipment("confocal-b", "Confocal B", "09:00", "18:00", 0),
    }
    bookings = [
        Booking(id="X1", user_id="user-wang", equipment_id="confocal-a",
                start=T("10:00"), end=T("11:00"), movable=True),
        Booking(id="X2", user_id="user-chen", equipment_id="confocal-a",
                start=T("11:00"), end=T("12:00"), movable=True),
    ]
    import mcp_server.engine as eng
    w = eng.World(
        equipment=equipment, outages=[], bookings=bookings,
        user_names=seedm.user_names(), user_permissions=seedm.user_permissions(),
        day_open={eid: hhmm_boundary(D, eq.available_start) for eid, eq in equipment.items()},
        day_close={eid: hhmm_boundary(D, eq.available_end) for eid, eq in equipment.items()},
    )
    # X1 must vacate 10:00-11:00 (outage), and X2 (11:00-12:00) unaffected:
    o = Outage(id="OZ", equipment_id="confocal-a",
               start=T("10:00"), end=T("11:00"), reason="probe")
    changes, unresolved = compute_plan(w, o)
    # with zero buffers and B free, earliest is 10:00 on B or staying on A at
    # 11:00 (outage ends then, no buffer vs outage). Search order is original
    # equipment first and the key is earliest start — but A at 11:00 and B at
    # 10:00: B is earlier, so B wins.
    x1 = next(c for c in changes if c.booking_id == "X1")
    assert x1.new_equipment in ("confocal-a", "confocal-b")
    if x1.new_equipment == "confocal-b":
        assert x1.new_start == T("10:00") and x1.new_end == T("11:00")
    else:
        # A at 11:00 collides with X2 (11:00-12:00, zero buffer)): lands 12:00
        assert x1.new_start == T("12:00") and x1.new_end == T("13:00")
    assert all(c.booking_id != "X2" for c in changes)
    assert unresolved == []
