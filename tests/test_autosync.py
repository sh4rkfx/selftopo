"""Automatic sync when the dashboard opens

GitHub often starts the scheduled sync hours late. The dashboard starts it itself when it opens
after 08:00 and the last sync is from before today, at most once in 3 hours, and pauses for a
week when the token may not start workflows. The helper runs in Node; without Node these tests
are skipped.
"""

# ruff: noqa: E501

import pytest
from jsdashboard import run

HELPERS = ["DAY", "AUTO_SYNC_FROM_H", "autoSyncDue"]
H = 3_600_000


def due(info_at: str, now: str, prefs: str = "{}") -> bool:
    """Times as local "YYYY-MM-DDTHH:MM" (no zone, so the browser's time zone)."""
    return run(HELPERS, f'autoSyncDue({{ at: Date.parse("{info_at}") }}, {prefs}, Date.parse("{now}"))')


@pytest.mark.parametrize(("last", "now", "expected"), [
    ("2026-11-23T07:41", "2026-11-24T08:05", True),   # yesterday's run, now after 08:00
    ("2026-11-23T07:41", "2026-11-24T07:55", False),  # before 08:00: the scheduled run may still come
    ("2026-11-24T00:10", "2026-11-24T10:20", False),  # already synced today
    ("2026-11-20T07:41", "2026-11-24T21:00", True),   # several days old, late in the evening
])
def test_starts_after_eight_when_nothing_ran_today(given, last, now, expected):
    """Due from 08:00 local time as long as no sync finished today."""
    given(last_sync=last, now=now)
    assert due(last, now) is expected


def test_at_most_once_in_three_hours(given):
    """A try at 08:05 that did not bring new data is repeated at 11:05 at the earliest."""
    tried = "Date.parse('2026-11-24T08:05')"
    given(tried="08:05")
    assert due("2026-11-23T07:41", "2026-11-24T11:00", f"{{ tried: {tried} }}") is False
    assert due("2026-11-23T07:41", "2026-11-24T11:06", f"{{ tried: {tried} }}") is True


def test_switched_off_or_paused_without_permission(given):
    """Off by the checkbox it never runs; after a 403 it pauses for seven days."""
    given(prefs=["off", "denied 6 and 8 days ago"])
    assert due("2026-11-23T07:41", "2026-11-24T09:00", "{ off: true }") is False
    assert due("2026-11-23T07:41", "2026-11-24T09:00", "{ denied: Date.parse('2026-11-18T09:00') }") is False
    assert due("2026-11-23T07:41", "2026-11-24T09:00", "{ denied: Date.parse('2026-11-16T09:00') }") is True


def test_no_sync_status_no_automatic_sync(given):
    """Without sync_status.json (older data repository) nothing starts by itself."""
    given(info=None)
    assert run(HELPERS, 'autoSyncDue(null, {}, Date.parse("2026-11-24T09:00"))') is False
