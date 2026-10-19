"""MCP server: 6 tools, Streamable HTTP, elicitation on apply.

Identity comes exclusively from the Authorization header read off the
per-call starlette Request (ctx.request_context.request) — never from args.
Elicitation requires SSE mode (FastMCP stateless_http=False, json_response=False)
and an async client callback (spike5 evidence).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import List, Optional, Tuple

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
    BookingView,
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
    """Create schema and seed demo data (version=1). Called at startup."""
    path = _db_path()
    dbm.configure(path)
    dbm.init_db(path)
    _reseed()


def _reseed() -> None:
    conn = dbm.connect()
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

    conn = dbm.connect()
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

    n_msg = f"{len(bookings)} bookings"
    if open_outages:
        o0 = open_outages[0]
        n_msg += f"; outage {o0.id} on {o0.equipment_name} affects {len(o0.affected_booking_ids)} booking(s)"
    n_msg += f"; schedule version {version}"
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
        message=n_msg,
    )


@mcp.tool()
async def schedule_get(
    unit_id: str = C.UNIT_ID, date: str = C.DEMO_DATE, ctx: Context = None
) -> ScheduleGetResult:
    """Read one unit's schedule for one date with role-based masking."""
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
        return ReportOutageResult(
            status="forbidden",
            outage_id=None,
            equipment=None,
            schedule_version=version,
            message=_forbidden_ctx(version) if p is None else "manager role required",
        )

    conn = dbm.connect()
    try:
        eq_rows = dbm.equipment_for_unit(C.UNIT_ID, conn)
        eq = next((r for r in eq_rows if r["id"] == equipment_id), None)
        if eq is None:
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
            return ReportOutageResult(
                status="invalid_argument",
                outage_id=None,
                equipment=None,
                schedule_version=version,
                message="start/end must be ISO 8601 with timezone",
            )
        if e_dt <= s_dt:
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
            return ReportOutageResult(
                status="invalid_argument",
                outage_id=None,
                equipment=None,
                schedule_version=version,
                message=f"demo day only: start must be within [{C.DEMO_WINDOW_START}, {C.DEMO_WINDOW_END})",
            )
        if not (w_start <= e_dt <= w_end):
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
        return ProposeResult(
            status="forbidden",
            outage_id=outage_id,
            schedule_version=current,
            message=_forbidden_ctx(current) if p is None else "manager role required",
        )
    conn = dbm.connect()
    try:
        o = dbm.get_outage(outage_id, conn)
        if o is None:
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
            return ProposeResult(
                status="outage_resolved",
                outage_id=outage_id,
                schedule_version=current,
                message=f"outage {outage_id} has no blocked bookings",
            )
        if schedule_version != current:
            return ProposeResult(
                status="plan_stale",
                outage_id=outage_id,
                schedule_version=current,
                message=f"schedule_version is now {current}; re-propose with the current version",
            )
        existing = dbm.proposed_plan_for(outage_id, schedule_version, conn)
        if existing is not None:
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
        return ApplyResult(
            status="forbidden",
            plan_id=plan_id,
            new_version=current,
            message=_forbidden_ctx(current) if p is None else "manager role required",
        )
    conn = dbm.connect()
    try:
        plan = dbm.get_plan(plan_id, conn)
        if plan is None:
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
        except Exception as exc:  # McpError('Elicitation not supported') and friends
            elicited = False
            _elicitation_error = exc

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
        except Exception as exc:
            conn.rollback()
            return ApplyResult(
                status="apply_failed",
                plan_id=plan_id,
                outage_id=plan["outage_id"],
                new_version=current,
                message=f"transaction rolled back: {exc}",
            )
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
        return ResetResult(
            status="forbidden",
            schedule_version=version,
            message=_forbidden_ctx(version) if p is None else "manager role required",
        )
    _reseed()
    return ResetResult(
        status="reset",
        schedule_version=1,
        message="demo data reseeded; schedule version reset to 1",
    )


# --------------------------------------------------------------------------
# Tool 6: debug_confirm
# --------------------------------------------------------------------------


@mcp.tool()
async def debug_confirm(ctx: Context = None) -> ConfirmResult:
    """M0 verification: send one elicitation and report exactly what the client answered."""
    ensure_ready()
    try:
        res = await ctx.elicit(
            "Debug: please confirm.", ConfirmModel
        )
        confirm = None
        if res.action == "accept" and res.data is not None:
            confirm = bool(res.data.confirm)
        return ConfirmResult(
            elicited=True,
            action=res.action,
            confirm=confirm,
            message=f"client answered action={res.action!r}",
        )
    except Exception as exc:
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
    """ASGI app (Streamable HTTP at /mcp). Must be created before session_manager use."""
    initialize_storage()
    return mcp.streamable_http_app()


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
    app = mcp.streamable_http_app()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
