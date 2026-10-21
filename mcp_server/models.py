"""Pydantic output models — must exactly match contracts/tools.json (contract v1).

Every tool returns one of these BaseModel subclasses so MCP structuredOutput
emits `outputSchema` + `structuredContent`. A dict return would yield null.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class Viewer(BaseModel):
    user_id: str
    name: str
    role: str


# ---- schedule_get -----------------------------------------------------------

class OutageWindow(BaseModel):
    """Per-equipment outage window inside schedule_get.equipment[].outages."""

    id: str
    start: str
    end: str
    reason: Optional[str] = None


class EquipmentView(BaseModel):
    id: str
    name: str
    available_start: str  # HH:MM
    available_end: str  # HH:MM
    buffer_minutes: int
    outages: List[OutageWindow] = Field(default_factory=list)


class BookingView(BaseModel):
    id: str
    user: str
    user_id: Optional[str] = None
    role: Optional[str] = None
    equipment: str
    equipment_name: str
    start: str
    end: str
    deadline: Optional[str] = None
    status: str  # confirmed | blocked | unresolved | occupied
    movable: bool
    masked: bool = False
    affected_by_outage: Optional[str] = None


class OutageView(BaseModel):
    id: str
    equipment: str
    equipment_name: str
    start: str
    end: str
    reason: Optional[str] = None
    affected_booking_ids: List[str] = Field(default_factory=list)
    unresolved_booking_ids: List[str] = Field(default_factory=list)
    resolved: bool = False


class PendingPlanView(BaseModel):
    plan_id: str
    outage_id: str
    based_on_version: int
    is_complete: bool
    change_count: int
    unresolved_count: int
    created_at: str


class ScheduleGetResult(BaseModel):
    status: str
    schedule_version: int
    timezone: str
    date: str
    unit_id: str
    unit_name: str
    viewer: Viewer
    equipment: List[EquipmentView]
    bookings: List[BookingView]
    open_outages: List[OutageView]
    pending_plans: List[PendingPlanView]
    message: Optional[str] = None


# ---- report_outage ----------------------------------------------------------

class EquipmentRef(BaseModel):
    id: str
    name: str
    unit_id: str


class AffectedBooking(BaseModel):
    id: str
    user: str
    user_id: str
    start: str
    end: str
    deadline: Optional[str] = None
    status: str


class ReportOutageResult(BaseModel):
    status: str
    outage_id: Optional[str] = None
    equipment: Optional[EquipmentRef] = None
    affected_bookings: List[AffectedBooking] = Field(default_factory=list)
    unaffected_count: int = 0
    schedule_version: int
    message: Optional[str] = None


# ---- Reason (§2.4) ----------------------------------------------------------

class Reason(BaseModel):
    code: str
    outage_id: Optional[str] = None
    until: Optional[str] = None
    from_: Optional[str] = Field(default=None, alias="from")
    to: Optional[str] = None
    equipment_id: Optional[str] = None
    booking_id: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    minutes: Optional[int] = None
    opens: Optional[str] = None
    closes: Optional[str] = None
    deadline: Optional[str] = None
    at_least: Optional[str] = None

    model_config = {"populate_by_name": True}


# ---- propose ----------------------------------------------------------------

class Change(BaseModel):
    booking_id: str
    user: str
    user_id: str
    original_equipment: str
    original_equipment_name: str
    original_start: str
    original_end: str
    new_equipment: str
    new_equipment_name: str
    new_start: str
    new_end: str
    reasons: List[Reason]


class EarliestPossible(BaseModel):
    equipment_id: str
    equipment_name: str
    status: str  # available_after_deadline | unavailable | no_permission | no_slot_today
    earliest_start: Optional[str] = None
    earliest_finish: Optional[str] = None
    blockers: List[Reason] = Field(default_factory=list)
    would_work_if: List[Reason] = Field(default_factory=list)


class UnresolvedEntry(BaseModel):
    booking_id: str
    user: str
    user_id: str
    equipment: str
    equipment_name: str
    original_start: str
    original_end: str
    deadline: Optional[str] = None
    movable: bool
    reasons: List[Reason]
    earliest_possible: List[EarliestPossible]


class ProposalSummary(BaseModel):
    affected: int
    rescheduled: int
    unresolved: int


class ProposeResult(BaseModel):
    status: str
    plan_id: Optional[str] = None
    outage_id: str
    based_on_version: Optional[int] = None
    schedule_version: int
    changes: List[Change] = Field(default_factory=list)
    unresolved: List[UnresolvedEntry] = Field(default_factory=list)
    is_complete: bool = False
    summary: Optional[ProposalSummary] = None
    generated_at: Optional[str] = None
    message: Optional[str] = None


# ---- apply ------------------------------------------------------------------

class AppliedChange(BaseModel):
    booking_id: str
    user: str
    original_equipment: str
    new_equipment: str
    from_start: str
    from_end: str
    to_start: str
    to_end: str
    reasons: List[Reason]


class ApplyResult(BaseModel):
    status: str
    plan_id: Optional[str] = None
    outage_id: Optional[str] = None
    applied_changes: List[AppliedChange] = Field(default_factory=list)
    unresolved: List[UnresolvedEntry] = Field(default_factory=list)
    new_version: int
    confirmed_by: Optional[Viewer] = None
    confirmed_at: Optional[str] = None
    message: Optional[str] = None


# ---- reset / debug ----------------------------------------------------------

class ResetResult(BaseModel):
    status: str
    schedule_version: int
    message: Optional[str] = None


class AuditEntry(BaseModel):
    at: str
    actor_id: str = ""
    actor_name: str = ""
    actor_role: str = ""
    tool: str
    result: str
    detail: str = ""
    token_hint: str = "-"
    # machine-readable mirror of `detail` (parsed JSON object; None = absent)
    detail_json: Optional[dict] = None


class AuditGetResult(BaseModel):
    status: str  # ok | forbidden
    schedule_version: int
    entries: List[AuditEntry] = []
    next_before_id: Optional[int] = None  # cursor: pass to before_id for older rows
    viewer: Optional[Viewer] = None
    message: Optional[str] = None


class ChainVerifyResult(BaseModel):
    status: str  # ok | forbidden
    schedule_version: int
    chain_ok: Optional[bool] = None  # None when forbidden
    checked: int = 0  # rows verified before the break (total when intact)
    head_id: Optional[int] = None
    head_hash: Optional[str] = None  # 64-hex chain head; pin externally to anchor
    broken_at: Optional[int] = None
    reason: Optional[str] = None  # hash mismatch | prev_hash mismatch | row deleted
    message: Optional[str] = None


class ConfirmResult(BaseModel):
    elicited: bool
    action: str  # accepted | declined | cancelled | not_supported
    confirm: Optional[bool] = None
    message: Optional[str] = None
