"""Time utilities. All datetimes are timezone-aware; London demo day = BST +01:00."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")
UTC = timezone.utc


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
    """Combine demo date + 'HH:MM' into an aware London datetime."""
    h, m = hhmm.split(":")
    naive = datetime.fromisoformat(f"{date_str}T{int(h):02d}:{int(m):02d}:00")
    return naive.replace(tzinfo=LONDON)


def next_quarter(dt: datetime) -> datetime:
    """Round dt UP to the next 15-minute boundary (dt itself if exact)."""
    minute = dt.minute
    add = (15 - minute % 15) % 15
    base = dt.replace(second=0, microsecond=0)
    return base + timedelta(minutes=add)


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """Half-open intersection: (a_start < b_end) and (a_end > b_start)."""
    return a_start < b_end and a_end > b_start
