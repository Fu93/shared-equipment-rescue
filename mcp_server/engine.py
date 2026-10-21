"""Pure replan engine (plan §10). No I/O, no clocks; all times passed in aware.

Search rules (contract §5.3 / plan §10):
- Candidate slots start from the ORIGINAL start (clamped up to the 15-min grid),
  stepping +15min, forward only.
- Per-booking search order: original equipment first, then the other.
- Choice key: (earliest_start, original-equipment-first tiebreak).
- A slot is valid when ALL hold:
    1. within equipment operating hours (open <= start, end <= close),
    2. not overlapping any outage on that equipment (never buffer vs outage),
    3. user has permission for the equipment,
    4. user free: no overlap with the user's own other bookings,
    5. no overlap with any other booking on that equipment,
    6. buffer: >= buffer_minutes gap to the nearest booking before AND after
       (computed against all occupancy bookings),
    7. end <= deadline when the booking has one.
- Occupancy excludes the booking being moved.
- Unmovable affected bookings are added to unresolved with reason not_movable.
- earliest_possible: SECOND pass after all movable bookings are placed, using
  final occupancy, ignoring the target booking's own deadline. If the found
  finish time exceeds the booking's deadline, status available_after_deadline
  and would_work_if=["extend deadline to ..."]. Otherwise no_slot_today.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from .models import Change, EarliestPossible, Reason, UnresolvedEntry
from .timeutil import LONDON, fmt, overlaps, parse_dt

STEP = timedelta(minutes=15)
DAY_MAX = datetime.max.replace(tzinfo=LONDON)


@dataclass
class Equipment:
    id: str
    name: str
    available_start: str  # HH:MM local
    available_end: str  # HH:MM local
    buffer_minutes: int = 15


@dataclass
class Outage:
    id: str
    equipment_id: str
    start: str
    end: str
    reason: str


@dataclass
class Booking:
    id: str
    user_id: str
    equipment_id: str
    start: str  # current_start ISO
    end: str  # current_end ISO
    deadline: Optional[str] = None
    movable: bool = True
    status: str = "confirmed"


@dataclass
class World:
    equipment: dict  # equipment_id -> Equipment
    outages: List[Outage]
    bookings: List[Booking]
    user_names: dict  # user_id -> display name
    user_permissions: dict  # equipment_id -> set(user_id) (computed by caller)
    day_open: dict  # equipment_id -> aware open datetime
    day_close: dict  # equipment_id -> aware close datetime


def clone_bookings(bookings: List[Booking]) -> List[Booking]:
    return [
        Booking(
            id=b.id,
            user_id=b.user_id,
            equipment_id=b.equipment_id,
            start=b.start,
            end=b.end,
            deadline=b.deadline,
            movable=b.movable,
            status=b.status,
        )
        for b in bookings
    ]


def affected_by(outage: Outage, bookings: List[Booking]) -> List[Booking]:
    os_, oe = parse_dt(outage.start), parse_dt(outage.end)
    return [
        b
        for b in bookings
        if b.equipment_id == outage.equipment_id
        and overlaps(parse_dt(b.start), parse_dt(b.end), os_, oe)
    ]


def _r(code: str, **kw) -> Reason:
    return Reason(code=code, **kw)


def _slot_failures(
    world: World,
    occupancy: List[Booking],
    equipment_id: str,
    user_id: str,
    start: datetime,
    end: datetime,
    moving_id: str,
    deadline: Optional[datetime],
) -> List[Reason]:
    """Reasons why this slot fails. Empty list == placeable."""
    reasons: List[Reason] = []
    eq = world.equipment[equipment_id]

    opens_, closes_ = world.day_open[equipment_id], world.day_close[equipment_id]
    if start < opens_ or end > closes_:
        reasons.append(
            _r("outside_operating_hours", opens_=fmt(opens_), closes_=fmt(closes_))
        )

    for o in world.outages:
        if o.equipment_id == equipment_id and overlaps(
            start, end, parse_dt(o.start), parse_dt(o.end)
        ):
            reasons.append(_r("equipment_down", until=fmt(parse_dt(o.end))))
            break

    if user_id not in world.user_permissions.get(equipment_id, set()):
        reasons.append(_r("no_permission", equipment_id=equipment_id))

    for b in occupancy:
        if b.id == moving_id or b.equipment_id != equipment_id:
            continue
        bs, be = parse_dt(b.start), parse_dt(b.end)
        if overlaps(start, end, bs, be):
            if b.user_id == user_id:
                reasons.append(
                    _r("user_busy", booking_id=b.id, start=b.start, end=b.end)
                )
            else:
                reasons.append(
                    _r("blocked_by_booking", booking_id=b.id, start=b.start, end=b.end)
                )

    buf = timedelta(minutes=eq.buffer_minutes)
    before_end: Optional[datetime] = None
    after_start: Optional[datetime] = None
    for b in occupancy:
        if b.id == moving_id or b.equipment_id != equipment_id:
            continue
        bs, be = parse_dt(b.start), parse_dt(b.end)
        if be <= start and (before_end is None or be > before_end):
            before_end = be
        if bs >= end and (after_start is None or bs < after_start):
            after_start = bs
    if before_end is not None and (start - before_end) < buf:
        reasons.append(_r("buffer", minutes=eq.buffer_minutes))
    if after_start is not None and (after_start - end) < buf:
        reasons.append(_r("buffer", minutes=eq.buffer_minutes))

    if deadline is not None and end > deadline:
        reasons.append(_r("deadline_missed", end=fmt(end), deadline=fmt(deadline)))

    return reasons


def first_fit(
    world: World,
    occupancy: List[Booking],
    equipment_id: str,
    user_id: str,
    original_start: datetime,
    duration: timedelta,
    deadline: Optional[datetime],
    moving_id: str,
) -> Tuple[Optional[datetime], Optional[datetime]]:
    """Earliest valid slot >= original_start on one equipment, or (None, None)."""
    cursor = original_start
    if (cursor.minute % 15) or cursor.second or cursor.microsecond:
        cursor = cursor.replace(second=0, microsecond=0, minute=0)
        cursor += (int(original_start.minute // 15) + 1) * STEP
    close = world.day_close[equipment_id]
    while cursor + duration <= close:
        end = cursor + duration
        fails = _slot_failures(
            world, occupancy, equipment_id, user_id, cursor, end, moving_id, deadline
        )
        if not fails:
            return cursor, end
        cursor += STEP
    return None, None


def _choose_slot(
    world: World,
    occupancy: List[Booking],
    target: Booking,
    deadline: Optional[datetime],
) -> Tuple[Optional[str], Optional[datetime], Optional[datetime]]:
    """Search all equipment: original first. Key (earliest_start, original first)."""
    duration = parse_dt(target.end) - parse_dt(target.start)
    original_start = parse_dt(target.start)
    best: Optional[Tuple[datetime, datetime, str, bool]] = None
    order = [target.equipment_id] + [
        eid for eid in world.equipment if eid != target.equipment_id
    ]
    for eid in order:
        s, e = first_fit(
            world, occupancy, eid, target.user_id, original_start, duration,
            deadline, target.id,
        )
        if s is None:
            continue
        is_original = eid == target.equipment_id
        if best is None or s < best[0] or (s == best[0] and is_original):
            best = (s, e, eid, is_original)
    if best is None:
        return None, None, None
    return best[2], best[0], best[1]


def compute_plan(
    world: World, outage: Outage
) -> Tuple[List[Change], List[UnresolvedEntry]]:
    # Self-contained outage visibility: a caller may pass a world without the
    # newly-reported outage; make the search see it either way.
    outages = list(world.outages)
    if not any(o.id == outage.id for o in outages):
        outages.append(outage)
    search_world = World(
        equipment=world.equipment,
        outages=outages,
        bookings=world.bookings,
        user_names=world.user_names,
        user_permissions=world.user_permissions,
        day_open=world.day_open,
        day_close=world.day_close,
    )
    affected = affected_by(outage, world.bookings)
    _, oe = parse_dt(outage.start), parse_dt(outage.end)
    movable_affected = [b for b in affected if b.movable]
    nonmovable_affected = [b for b in affected if not b.movable]

    def sort_key(b: Booking):
        dl = parse_dt(b.deadline) if b.deadline else None
        return (0, dl, parse_dt(b.start)) if dl else (1, DAY_MAX, parse_dt(b.start))

    movable_affected.sort(key=sort_key)

    occupancy = clone_bookings(world.bookings)
    changes: List[Change] = []
    unresolved: List[UnresolvedEntry] = []

    for target in movable_affected:
        deadline = parse_dt(target.deadline) if target.deadline else None
        eid, s, e = _choose_slot(search_world, occupancy, target, deadline)
        if eid is None:
            reasons = [
                _r("original_slot_in_outage", outage_id=outage.id, until=fmt(oe)),
                _r("no_slot_found"),
            ]
            unresolved.append(
                UnresolvedEntry(
                    booking_id=target.id,
                    user=world.user_names.get(target.user_id, target.user_id),
                    user_id=target.user_id,
                    equipment=target.equipment_id,
                    equipment_name=world.equipment[target.equipment_id].name,
                    original_start=target.start,
                    original_end=target.end,
                    deadline=target.deadline,
                    movable=True,
                    reasons=reasons,
                    earliest_possible=[],
                )
            )
            continue

        eq_old = world.equipment[target.equipment_id]
        eq_new = world.equipment[eid]
        rs: List[Reason] = [_r("original_slot_in_outage", outage_id=outage.id, until=fmt(oe))]
        if eid != target.equipment_id:
            rs.append(_r("switched_equipment", **{"from": target.equipment_id, "to": eid}))
        else:
            rs.append(_r("stayed_on_original_equipment", equipment_id=eid))
        if deadline is not None:
            rs.append(_r("deadline_ok", end=fmt(e), deadline=fmt(deadline)))

        changes.append(
            Change(
                booking_id=target.id,
                user=world.user_names.get(target.user_id, target.user_id),
                user_id=target.user_id,
                original_equipment=target.equipment_id,
                original_equipment_name=eq_old.name,
                original_start=target.start,
                original_end=target.end,
                new_equipment=eid,
                new_equipment_name=eq_new.name,
                new_start=fmt(s),
                new_end=fmt(e),
                reasons=rs,
            )
        )
        for bb in occupancy:
            if bb.id == target.id:
                bb.equipment_id = eid
                bb.start = fmt(s)
                bb.end = fmt(e)
                bb.status = "confirmed"

    for b in nonmovable_affected:
        unresolved.append(
            UnresolvedEntry(
                booking_id=b.id,
                user=world.user_names.get(b.user_id, b.user_id),
                user_id=b.user_id,
                equipment=b.equipment_id,
                equipment_name=world.equipment[b.equipment_id].name,
                original_start=b.start,
                original_end=b.end,
                deadline=b.deadline,
                movable=False,
                reasons=[
                    _r("not_movable"),
                    _r("original_slot_in_outage", outage_id=outage.id, until=fmt(oe)),
                ],
                earliest_possible=[],
            )
        )

    _fill_earliest_possible(search_world, movable_affected, unresolved, changes, outage)
    return changes, unresolved


def _fill_earliest_possible(
    world: World,
    movable_affected: List[Booking],
    unresolved: List[UnresolvedEntry],
    changes: List[Change],
    outage: Outage,
) -> None:
    final_occupancy = clone_bookings(world.bookings)
    applied = {c.booking_id: c for c in changes}
    for bb in final_occupancy:
        c = applied.get(bb.id)
        if c is not None:
            bb.equipment_id = c.new_equipment
            bb.start = c.new_start
            bb.end = c.new_end
            bb.status = "confirmed"

    for entry in unresolved:
        target = next((b for b in movable_affected if b.id == entry.booking_id), None)
        if target is None:
            continue  # unmovable entries get no earliest_possible
        duration = parse_dt(target.end) - parse_dt(target.start)
        grid_start = parse_dt(target.start)
        if (grid_start.minute % 15) or grid_start.second or grid_start.microsecond:
            grid_start = grid_start.replace(second=0, microsecond=0)
            grid_start += (int(grid_start.minute // 15) + 1) * STEP

        deadline = parse_dt(target.deadline) if target.deadline else None
        eps: List[EarliestPossible] = []
        order = [target.equipment_id] + [
            eid for eid in world.equipment if eid != target.equipment_id
        ]
        found_any = False
        for eid in order:
            if target.user_id not in world.user_permissions.get(eid, set()):
                eps.append(
                    EarliestPossible(
                        equipment_id=eid,
                        equipment_name=world.equipment[eid].name,
                        status="no_permission",
                        blockers=[_r("no_permission", equipment_id=eid)],
                        would_work_if=[],  # TODO wwi reason
                    )
                )
                continue
            s, e = first_fit(
                world, final_occupancy, eid, target.user_id, grid_start,
                duration, None, target.id,
            )
            if s is not None:
                found_any = True
                late = deadline is not None and e > deadline
                wwi: List[Reason] = []
                if late:
                    wwi.append(_r("deadline_would_need", at_least=fmt(e)))
                eps.append(
                    EarliestPossible(
                        equipment_id=eid,
                        equipment_name=world.equipment[eid].name,
                        status="available_after_deadline" if late else "no_slot_today",
                        earliest_start=fmt(s),
                        earliest_finish=fmt(e),
                        blockers=[],
                        would_work_if=wwi,
                    )
                )
            else:
                eps.append(
                    EarliestPossible(
                        equipment_id=eid,
                        equipment_name=world.equipment[eid].name,
                        status="no_slot_today",
                        blockers=[_r("no_slot_found")],
                        would_work_if=[],
                    )
                )
        entry.earliest_possible = eps
        if deadline is not None and found_any:
            best_finish = min(
                (
                    parse_dt(ep.earliest_finish)
                    for ep in eps
                    if ep.earliest_finish is not None
                ),
                default=None,
            )
            if best_finish is not None and best_finish > deadline:
                entry.reasons.append(
                    _r("deadline_would_need", at_least=fmt(best_finish))
                )
        elif target.deadline is None and not found_any:
            # The base unresolved reasons built in compute_plan already carry
            # a no_slot_found entry (compute_plan attaches it for every
            # movable-no-fit booking); appending a second copy made the UI
            # narrative print the same sentence twice. Only add it when the
            # base list somehow lacks it.
            if not any(r.code == "no_slot_found" for r in entry.reasons):
                entry.reasons.append(_r("no_slot_found"))


# NOTE on EarliestPossible.status semantics (contract §5): a moved-late slot
# found in the second pass is "available_after_deadline"; a slot the engine
# cannot fit at all today is "no_slot_today"; no other statuses occur here
# besides the explicit no_permission case. Several statuses would only appear
# if computed with stricter day-window semantics, covered by "unavailable".
