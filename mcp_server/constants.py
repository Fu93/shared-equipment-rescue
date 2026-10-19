"""Constants shared across the MCP server.

Demo day: 2026-10-20, Europe/London (BST, +01:00).
All persisted timestamps are full ISO 8601 strings with timezone offset.
"""

from __future__ import annotations

DEMO_DATE = "2026-10-20"
DEMO_TZ = "Europe/London"
DEMO_TZ_OFFSET = "+01:00"

# Demo-day validity window: [2026-10-20T00:00, 2026-10-21T00:00)
DEMO_WINDOW_START = "2026-10-20T00:00:00+01:00"
DEMO_WINDOW_END = "2026-10-21T00:00:00+01:00"

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
