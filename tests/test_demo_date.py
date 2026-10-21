"""The seeded demo day follows SER_DEMO_DATE. Audit timestamps stay on the real clock."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest


def test_suite_pins_the_published_demo_day():
    from mcp_server import constants as C

    assert C.DEMO_DATE == "2026-10-20"
    assert C.DEMO_TZ == "Europe/London"
    assert C.DEMO_TZ_OFFSET == "+01:00"
    assert C.DEMO_WINDOW_START == "2026-10-20T00:00:00+01:00"


def test_winter_and_summer_offsets_follow_the_zone(monkeypatch):
    monkeypatch.setenv("SER_DEMO_TZ", "Europe/London")
    from mcp_server.timeutil import local_iso

    assert local_iso("2026-10-20", "09:00") == "2026-10-20T09:00:00+01:00"
    assert local_iso("2026-01-15", "09:00") == "2026-01-15T09:00:00+00:00"


def test_unset_demo_date_is_today_in_the_configured_zone(monkeypatch):
    monkeypatch.delenv("SER_DEMO_DATE", raising=False)
    monkeypatch.setenv("SER_DEMO_TZ", "Europe/London")
    from mcp_server.timeutil import resolve_demo_date

    expected = datetime.now(ZoneInfo("Europe/London")).date().isoformat()
    assert resolve_demo_date() == expected


def test_bad_demo_date_is_rejected(monkeypatch):
    from mcp_server.timeutil import resolve_demo_date

    monkeypatch.setenv("SER_DEMO_DATE", "20-10-2026")
    with pytest.raises(ValueError):
        resolve_demo_date()
    monkeypatch.setenv("SER_DEMO_DATE", "2026-02-31")
    with pytest.raises(ValueError):
        resolve_demo_date()


def test_audit_clock_is_the_real_utc_clock(monkeypatch):
    monkeypatch.delenv("SER_FROZEN_NOW", raising=False)
    from mcp_server.db import now_iso

    stamp = now_iso()
    parsed = datetime.fromisoformat(stamp)
    assert parsed.tzinfo is not None
    delta = abs((datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds())
    assert delta < 5
