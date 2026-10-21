"""Constants shared across the MCP server.

The seeded day is read once, when this module is imported:
SER_DEMO_DATE, or today's date in SER_DEMO_TZ (default Europe/London).
Audit rows use the real UTC clock and are not rewritten to this date.
"""

from __future__ import annotations

from .timeutil import configured_tz_name, day_window, local_iso, resolve_demo_date

DEMO_DATE = resolve_demo_date()
DEMO_TZ = configured_tz_name()
DEMO_TZ_OFFSET = local_iso(DEMO_DATE, "12:00")[-6:]
DEMO_WINDOW_START, DEMO_WINDOW_END = day_window(DEMO_DATE)

UNIT_ID = "lab-a"
UNIT_NAME = "Research Lab A"

DEFAULT_BUFFER_MINUTES = 15

# Booking status values
STATUS_CONFIRMED = "confirmed"
STATUS_BLOCKED = "blocked"
STATUS_UNRESOLVED = "unresolved"
STATUS_OCCUPIED = "occupied"  # researcher view of other users' bookings

# Auth: demo bearer tokens -> accounts
TOKEN_MANAGER = "tok-manager"
TOKEN_CHEN = "tok-chen"
TOKEN_WANG = "tok-wang"
TOKEN_LI = "tok-li"

DB_KEY_VERSION = "schedule_version"

# Audit tools whose events are public: visible to every authenticated user in
# the audit trail (researchers additionally see their own actions). Single
# source of truth — imported by both db.audit_entries (SQL boundary) and
# server.schedule_audit_get (Python filter); they must never diverge.
PUBLIC_AUDIT_TOOLS = frozenset({
    "equipment_report_outage", "schedule_propose_replan",
    "schedule_apply_replan", "reset_demo_data",
})
