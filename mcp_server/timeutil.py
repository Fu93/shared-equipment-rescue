"""Time utilities. All datetimes are timezone-aware.

The seeded demo day is SER_DEMO_DATE, or today in SER_DEMO_TZ (default
Europe/London). Audit timestamps do not use this clock.
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")
UTC = timezone.utc
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def configured_tz_name() -> str:
    """SER_DEMO_TZ, or Europe/London. Raises if the name is not a real zone."""
    name = (os.environ.get("SER_DEMO_TZ") or "Europe/London").strip() or "Europe/London"
    ZoneInfo(name)
    return name


def configured_zone() -> ZoneInfo:
    return ZoneInfo(configured_tz_name())


def resolve_demo_date() -> str:
    """ISO date for the seeded schedule.

    SER_DEMO_DATE wins when it is set. Otherwise this is today's date in
    the configured zone, read from the real clock.
    """
    raw = (os.environ.get("SER_DEMO_DATE") or "").strip()
    if raw:
        if not _ISO_DATE.match(raw):
            raise ValueError(f"SER_DEMO_DATE must be YYYY-MM-DD, got {raw!r}")
        date.fromisoformat(raw)
        return raw
    return datetime.now(configured_zone()).date().isoformat()


def local_iso(date_str: str, hhmm: str) -> str:
    """Wall time on date_str in the configured zone, with that instant's offset."""
    hour, minute = hhmm.split(":")
    year, month, day = (int(part) for part in date_str.split("-"))
    dt = datetime(year, month, day, int(hour), int(minute), tzinfo=configured_zone())
    return dt.isoformat()


def day_window(date_str: str) -> tuple[str, str]:
    """[local midnight, next local midnight) as ISO strings."""
    start = local_iso(date_str, "00:00")
    year, month, day = (int(part) for part in date_str.split("-"))
    nxt = (date(year, month, day) + timedelta(days=1)).isoformat()
    return start, local_iso(nxt, "00:00")


def parse_dt(s: str) -> datetime:
    """Parse an ISO 8601 string. Accepts 'Z'. Rejects naive datetimes."""
    s = s.strip()
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"naive datetime not allowed: {s!r}")
    return dt


def fmt(dt: datetime) -> str:
    """Format an aware datetime as ISO 8601 with offset."""
    if dt.tzinfo is None:
        raise ValueError("refusing to format naive datetime")
    return dt.isoformat()


def to_london(dt: datetime) -> datetime:
    return dt.astimezone(LONDON)


def hhmm_boundary(date_str: str, hhmm: str) -> datetime:
    """Combine a date + 'HH:MM' into an aware datetime in the configured zone."""
    return datetime.fromisoformat(local_iso(date_str, hhmm))


def next_quarter(dt: datetime) -> datetime:
    """Round dt UP to the next 15-minute boundary (dt itself if exact)."""
    minute = dt.minute
    add = (15 - minute % 15) % 15
    base = dt.replace(second=0, microsecond=0)
    return base + timedelta(minutes=add)


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """Half-open intersection: (a_start < b_end) and (a_end > b_start)."""
    return a_start < b_end and a_end > b_start
