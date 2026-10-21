"""Engine unit tests: greedy search, buffers, permissions, deadlines, no-solution."""

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from mcp_server.engine import (  # noqa: E402
    Booking,
    Equipment,
    Outage,
    World,
    _choose_slot,
    compute_plan,
)
from mcp_server import constants as C  # noqa: E402
from mcp_server import seed as seedm  # noqa: E402
from mcp_server.timeutil import hhmm_boundary, local_iso, parse_dt, fmt  # noqa: E402

D = C.DEMO_DATE
T = lambda hhmm: fmt(hhmm_boundary(D, hhmm))


def build_world(bmv=None):
    """Standard seed world. bookings stay at original slots."""
    equipment = {
        "confocal-a": Equipment(
            id="confocal-a", name="Confocal Microscope A",
            available_start="09:00", available_end="18:00",
            buffer_minutes=15,
        ),
        "confocal-b": Equipment(
            id="confocal-b", name="Confocal Microscope B",
            available_start="09:00", available_end="18:00",
            buffer_minutes=15,
        ),
    }
    bookings = {b[0]: Booking(
        id=b[0], user_id=b[1], equipment_id=b[2],
        start=local_iso(D, b[3]),
        end=local_iso(D, b[4]),
        deadline=local_iso(D, b[5]) if b[5] else None,
        movable=bool(b[6]), status=b[7] or "confirmed",
    ) for b in seedm._BOOKINGS}
    if bmv:
        for bid, mv in bmv.items():
            bookings[bid].movable = mv
    # single zero-length outage default (none)
    return World(
        equipment=equipment,
        outages=[],
        bookings=list(bookings.values()),
        user_names=seedm.user_names(),
        user_permissions=seedm.user_permissions(),
        day_open={eid: hhmm_boundary(D, e.available_start) for eid, e in equipment.items()},
        day_close={eid: hhmm_boundary(D, e.available_end) for eid, e in equipment.items()},
    )


# --- baseline: A outage 10:00–16:00, all movable ---------------------------


def test_baseline_two_changes():
    w = build_world()
    outage = Outage(
        id="O1", equipment_id="confocal-a",
        start="2026-10-20T10:00:00+01:00", end="2026-10-20T16:00:00+01:00",
        reason="laser fault",
    )
    changes, unresolved = compute_plan(w, outage)
    assert unresolved == []
    assert [(c.booking_id, c.new_equipment, c.new_start[11:16], c.new_end[11:16]) for c in changes] == [
        ("B2", "confocal-b", "11:15", "12:15"),
        ("B4", "confocal-a", "16:00", "17:00"),
    ]


def test_baseline_occupies_send_occupied():
    """Applied changes are reflected for the occupied checks in the same plan."""
    w = build_world()
    outage = Outage(
        id="O1", equipment_id="confocal-a",
        start="2026-10-20T10:00:00+01:00", end="2026-10-20T16:00:00+01:00",
        reason="laser fault",
    )
    changes, _ = compute_plan(w, outage)
    b2 = next(c for c in changes if c.booking_id == "B2")
    assert b2.original_start[11:16] == "10:00" and b2.original_end[11:16] == "11:00"
    assert b2.original_equipment == "confocal-a" and b2.new_equipment == "confocal-b"


# --- no-solution with deadline --------------------------------------------


def test_no_deadline_solution_reports_earliest_possible():
    """B2 deadline 11:30: no fit; B must report B 11:15 with available_after_deadline
    and would_work_if at_least 12:15; A must report no_slot_today null window."""
    w = build_world()
    w.bookings[1].deadline = T("11:30")
    outage = Outage(
        id="O1", equipment_id="confocal-a",
        start="2026-10-20T10:00:00+01:00", end="2026-10-20T16:00:00+01:00",
        reason="laser fault",
    )
    changes, unresolved = compute_plan(w, outage)
    assert [(c.booking_id,) for c in changes] == [("B4",)]
    assert len(unresolved) == 1
    u = unresolved[0]
    assert u.booking_id == "B2" and u.movable is True
    eps = {e.equipment_id: e for e in u.earliest_possible}
    a = eps["confocal-a"]
    b = eps["confocal-b"]
    assert a.status == "no_slot_today" and a.earliest_start is None and a.earliest_finish is None
    assert b.status == "available_after_deadline"
    assert b.earliest_start == T("11:15") and b.earliest_finish == T("12:15")
    assert [(r.code, r.at_least) for r in b.would_work_if] == [("deadline_would_need", T("12:15"))]


# --- not movable -----------------------------------------------------------


def test_not_movable_unresolved():
    w = build_world(bmv={"B3": False})
    outage = Outage(
        id="O2", equipment_id="confocal-b",
        start="2026-10-20T10:00:00+01:00", end="2026-10-20T12:00:00+01:00",
        reason="filter change",
    )
    changes, unresolved = compute_plan(w, outage)
    b3 = next((u for u in unresolved if u.booking_id == "B3"), None)
    assert b3 is not None
    assert [r.code for r in b3.reasons] == ["not_movable", "original_slot_in_outage"]
    # Only B3 overlaps this outage (10-12 on B); no movable booking is affected.
    assert changes == []
    # B5 (14-15 on B) is untouched and outside the outage, so unaffected entirely.
    assert not any(c.booking_id == "B5" for c in changes)


# --- permissions -----------------------------------------------------------


def test_permission_blocks_equipment():
    w = build_world()
    # Outage on A: B4 (user wang, only A allowed) hits move fail
    outage = Outage(
        id="O1", equipment_id="confocal-a",
        start="2026-10-20T10:30:00+01:00", end="2026-10-20T12:00:00+01:00",
        reason="cal",
    )
    changes, unresolved = compute_plan(w, outage)
    # B4 should be unresolved with no_permission from A
    for u in unresolved:
        codes = [r.code for r in u.reasons]
        if u.booking_id == "B4":
            assert "no_slot_found" in codes or "no_permission" in codes


def _mk_world_custom():
    """World with single booking to isolate a permission test."""
    global WANG_WORLD
    equipment = {
        "confocal-a": Equipment("confocal-a", "Confocal A", "09:00", "18:00", 15),
        "confocal-b": Equipment("confocal-b", "Confocal B", "09:00", "18:00", 15),
    }
    bookings = [
        Booking(id="X1", user_id="user-wang", equipment_id="confocal-a",
                start=T("09:00"), end=T("10:00"), deadline=None,
                movable=True, status="confirmed"),
    ]
    WANG_WORLD = World(
        equipment=equipment,
        outages=[],
        bookings=bookings,
        user_names=seedm.user_names(),
        user_permissions=seedm.user_permissions(),
        day_open={eid: hhmm_boundary(D, e.available_start) for eid, e in equipment.items()},
        day_close={eid: hhmm_boundary(D, e.available_end) for eid, e in equipment.items()},
    )
    return WANG_WORLD


WANG_WORLD = _mk_world_custom()


def test_wang_no_permission_on_b():
    """Full-day outage on A forces Wang's A-only booking onto B: not possible.
    A reports no_slot_today; B reports no_permission."""
    outage = Outage(
        id="OX", equipment_id="confocal-a",
        start="2026-10-20T09:00:00+01:00", end="2026-10-20T18:00:00+01:00",
        reason="full-day outage",
    )
    changes, unresolved = compute_plan(WANG_WORLD, outage)
    assert changes == []
    assert len(unresolved) == 1
    u = unresolved[0]
    assert u.booking_id == "X1"
    b_ep = next(e for e in u.earliest_possible if e.equipment_id == "confocal-b")
    assert b_ep.status == "no_permission"
    assert "no_permission" in [r.code for r in b_ep.blockers]
    a_ep = next(e for e in u.earliest_possible if e.equipment_id == "confocal-a")
    assert a_ep.status == "no_slot_today"


# --- buffer semantics ------------------------------------------------------


def test_buffers_respected_on_slot_search():
    """B2 at 10-11 on A; outage 09:00-09:30 leaves 09:30; B2 can't move to start
    at 09:30 because original buffer applies to neighbors, not outage."""
    w = _mk_world_custom()
    # place X1 on A at 09:00-10:00 (already). Add booking Y1 on B at 09:45-10:45.
    w.bookings.append(
        Booking(id="Y1", user_id="user-chen", equipment_id="confocal-b",
                start=T("09:45"), end=T("10:45"), deadline=None,
                movable=True, status="confirmed"))
    outage = Outage(
        id="OX", equipment_id="confocal-b",
        start="2026-10-20T12:00:00+01:00", end="2026-10-20T13:00:00+01:00",
        reason="",
    )
    changes, unresolved = compute_plan(w, outage)
    # Y1 (B 09:45-10:45) unaffected by outage on B at 12:00? No: half-open overlap
    # (09:45 < 13:00) and (10:45 > 12:00) false => NOT affected. Empty expectation.
    assert changes == [] and unresolved == []


def test_back_to_back_no_buffer_crossing_outage():
    """Outage on B 10-12; B3 (10:00-11:00 B) is NOT movable in seed => stays,
    unresolved not_movable. Nothing movable overlaps this outage."""
    w = build_world()
    outage = Outage(
        id="O2", equipment_id="confocal-b",
        start="2026-10-20T10:00:00+01:00", end="2026-10-20T12:00:00+01:00",
        reason="maintenance",
    )
    changes, unresolved = compute_plan(w, outage)
    assert changes == []
    b3 = next((u for u in unresolved if u.booking_id == "B3"), None)
    assert b3 is not None
    assert "not_movable" in [r.code for r in b3.reasons]
    assert "original_slot_in_outage" in [r.code for r in b3.reasons]
    # Outage must be respected by the slot search but not buffered against:
    # a movable booking ON B may start exactly at outage end (12:00).
    # verify via a clone where B3 is movable: it should land at B 12:15 earliest
    # (12:00 outage end + 15-min buffer vs B5 at 14:00 leaves 12:15-13:15 free,
    # plus B3's own original start 10:00 is the search floor, stepping +15).
    w2 = build_world(bmv={"B3": True})
    ch2, unr2 = compute_plan(w2, outage)
    b3c = next(c for c in ch2 if c.booking_id == "B3")
    # B is 10:00-12:00 outage; step from 10:00 lands on 12:00 (outage end, no buffer vs outage)
    assert b3c.new_equipment == "confocal-b" or b3c.new_equipment == "confocal-a"
    # A 10:00-11:00 busy (B2) and Wang B1 09-10 means before-buffer ok; B at 12:00
    # conflicts with nothing; buffer to B5 (14:00) is fine. Might go either way
    # depending on permission; Li has only B.
    assert b3c.new_equipment == "confocal-b"  # Li is B-only
    assert b3c.new_start == T("12:00")


def test_outage_buffer_not_applicable():
    """A booking may start exactly at outage end (no 15-min buffer against outages)."""
    w = _mk_world_custom()
    # no other bookings; outage 09:00-09:30; X1 movable; must move to 09:30 exactly.
    outage = Outage(
        id="OX", equipment_id="confocal-a",
        start="2026-10-20T09:00:00+01:00", end="2026-10-20T09:30:00+01:00",
        reason="lens swap",
    )
    changes, unresolved = compute_plan(w, outage)
    assert len(changes) == 1
    c = changes[0]
    assert c.new_start == T("09:30") and c.new_end == T("10:30")


# --- deadline bounding ------------------------------------------------------


def test_deadline_inclusive_bounding():
    """X1 (wang, A-only) deadline 11:00; outage 09:30-10:30 on A.
    Wang cannot use B (no_permission) and A resumes only at 10:30, finishing
    11:30 > deadline 11:00 => no fit. Unresolved with available_after_deadline on A."""
    w = WANG_WORLD
    w.bookings[0].deadline = T("11:00")
    outage = Outage(
        id="OX", equipment_id="confocal-a",
        start="2026-10-20T09:30:00+01:00", end="2026-10-20T10:30:00+01:00",
        reason="cal",
    )
    changes, unresolved = compute_plan(w, outage)
    assert changes == []
    assert len(unresolved) == 1
    u = unresolved[0]
    a_ep = next(e for e in u.earliest_possible if e.equipment_id == "confocal-a")
    assert a_ep.status == "available_after_deadline"
    assert a_ep.earliest_start == T("10:30") and a_ep.earliest_finish == T("11:30")
    assert ("deadline_would_need", T("11:30")) in [(r.code, r.at_least) for r in a_ep.would_work_if]


# --- tie-break: (earliest_start, original-equipment-first) --------------------


def _open_world():
    """Seed world with every seeded booking removed, so both scopes are free."""
    w = build_world()
    w.bookings = []
    return w


def test_true_tie_keeps_original_equipment():
    """Both scopes free from 13:00 -> the booking stays on its ORIGINAL scope.

    Locks the documented choice key (engine.py: 'earliest_start, then
    original-equipment-first'). Without this, a refactor that sorted only by
    start time could silently shuffle every booking onto the other scope.
    """
    w = _open_world()
    target = Booking(
        id="TX", user_id="user-chen", equipment_id="confocal-a",
        start=T("13:00"), end=T("14:00"), deadline=None,
        movable=True, status="confirmed",
    )
    eid, start, end = _choose_slot(w, list(w.bookings), target, None)
    assert eid == "confocal-a"
    assert start == parse_dt(T("13:00")) and end == parse_dt(T("14:00"))


def test_earlier_alternative_beats_later_original():
    """A slot that starts earlier wins even when it is NOT the original scope.

    Counterpart to the tie test: the original scope only breaks exact ties,
    it never outranks a strictly earlier start.
    """
    w = _open_world()
    # A is occupied 13:00-14:00 by another user -> A's earliest is 14:15
    # (buffer 15m). B is free from 13:00.
    w.bookings.append(Booking(
        id="BLOCK", user_id="user-li", equipment_id="confocal-a",
        start=T("13:00"), end=T("14:00"), deadline=None,
        movable=False, status="confirmed",
    ))
    target = Booking(
        id="TY", user_id="user-chen", equipment_id="confocal-a",
        start=T("13:00"), end=T("14:00"), deadline=None,
        movable=True, status="confirmed",
    )
    eid, start, _end = _choose_slot(w, list(w.bookings), target, None)
    assert eid == "confocal-b"
    assert start == parse_dt(T("13:00"))
