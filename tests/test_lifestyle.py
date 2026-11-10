"""Lifestyle Logging

Parsing Garmin's daily log and fetching day by day. The response shape is assumed (see
selftopo/lifestyle.py), so these tests pin the mapping, not Garmin's real answer.
"""

# ruff: noqa: E501

from datetime import date

import pytest

from selftopo import config, lifestyle
from selftopo.csvstore import read_rows, write_rows

pytestmark = pytest.mark.critical  # wrong or lost habit entries


def entry(behaviour_id, name, status=None, kind="BOOLEAN", details=None, sleep=True):
    e = {"behaviourId": behaviour_id, "name": name, "measurementType": kind, "sleepRelated": sleep}
    if status:
        e["logStatus"] = status
    if details is not None:
        e["details"] = details
    return e


def test_parse_yes_no_amount_and_unanswered(given):
    """Yes is 1, no is 0, an amount is summed over its details, and not answered stays empty.

    A counted behaviour answered yes without an amount counts as 1. Entries without a name are
    skipped, and an empty or unknown response gives no rows.
    """
    payload = {"dailyLogsReport": [
        entry(11, "Alcohol", "YES", "QUANTITY", [{"amount": 2, "subTypeName": "BEER"}, {"amount": 1.5, "subTypeName": "WINE"}]),
        entry(12, "Late caffeine", "NO"),
        entry(13, "Late meal", "YES"),
        entry(14, "Coffee", "YES", "QUANTITY", []),
        entry(15, "Meditation", None, sleep=False),
        {"behaviourId": 16, "name": "  "},
        "junk",
    ]}
    given(payload=payload)
    rows = lifestyle.parse(payload, "2026-11-09")
    assert [(r["name"], r["kind"], r["status"], r["value"], r["sleep_related"]) for r in rows] == [
        ("Alcohol", "count", "yes", 3.5, 1),
        ("Late caffeine", "check", "no", 0, 1),
        ("Late meal", "check", "yes", 1, 1),
        ("Coffee", "count", "yes", 1, 1),
        ("Meditation", "check", None, None, 0),
    ]
    assert rows[0]["behaviour_id"] == "11" and rows[0]["date"] == "2026-11-09"
    assert lifestyle.parse(None, "2026-11-09") == [] and lifestyle.parse({}, "2026-11-09") == []


def _setup(tmp_path, monkeypatch, client):
    monkeypatch.setattr(config, "LIFESTYLE_CSV", tmp_path / "lifestyle.csv")
    monkeypatch.setattr(config, "GARMIN_REQUEST_DELAY_S", 0)
    monkeypatch.setattr(config, "GARMIN_REFRESH_DAYS", 1)
    monkeypatch.setattr(config, "today", lambda: date(2026, 11, 10))
    monkeypatch.setattr(lifestyle.garmin, "connect", lambda: client)
    monkeypatch.setattr(lifestyle.garmin, "save_tokens", lambda c: None)


def test_sync_skips_stored_days_and_keeps_them_on_failure(tmp_path, monkeypatch, given):
    """Stored older days are not fetched again; the newest days are. A failed request keeps the stored rows."""
    calls = []

    class Client:
        def get_lifestyle_logging_data(self, day):
            calls.append(day)
            if day == "2026-11-09":
                raise RuntimeError("HTTP 500")
            return {"dailyLogsReport": [entry(11, "Alcohol", "NO")]}

    _setup(tmp_path, monkeypatch, Client())
    write_rows(config.LIFESTYLE_CSV, lifestyle.FIELDS, [
        {"date": "2026-11-08", "behaviour_id": "11", "name": "Alcohol", "kind": "check", "status": "yes", "value": 1},
        {"date": "2026-11-09", "behaviour_id": "11", "name": "Alcohol", "kind": "check", "status": "yes", "value": 1},
    ])
    given(days=4, today="2026-11-10", stored="08 and 09 stored", garmin="09 fails, others answer no")
    lifestyle.sync(4)
    assert calls == ["2026-11-10", "2026-11-09", "2026-11-07"]
    assert [(r["date"], r["value"]) for r in read_rows(config.LIFESTYLE_CSV)] == [
        ("2026-11-07", "0"), ("2026-11-08", "1"), ("2026-11-09", "1"), ("2026-11-10", "0")]


def test_sync_stops_when_nothing_is_set_up(tmp_path, monkeypatch, given):
    """Without any behaviour, a 365-day sync stops after 7 empty days and remembers them.

    The next run only asks for the refresh window again (today and yesterday here), because the
    remembered empty days count towards the stop, so not using Lifestyle Logging costs little.
    """
    calls = []

    class Client:
        def get_lifestyle_logging_data(self, day):
            calls.append(day)
            return {"dailyLogsReport": []}

    _setup(tmp_path, monkeypatch, Client())
    given(days=365, stored=None, garmin="empty log every day")
    lifestyle.sync(365)
    assert len(calls) == lifestyle.EMPTY_DAYS_STOP
    rows = read_rows(config.LIFESTYLE_CSV)
    assert len(rows) == lifestyle.EMPTY_DAYS_STOP and not any(r["name"] for r in rows)
    calls.clear()
    lifestyle.sync(365)
    assert calls == ["2026-11-10", "2026-11-09"]


def test_sync_remembers_empty_days_before_first_use(tmp_path, monkeypatch, given):
    """Days before the first logged behaviour are stored as empty and not fetched again."""
    calls = []

    class Client:
        def get_lifestyle_logging_data(self, day):
            calls.append(day)
            return {"dailyLogsReport": [entry(11, "Alcohol", "NO")] if day >= "2026-11-09" else []}

    _setup(tmp_path, monkeypatch, Client())
    given(days=10, garmin="behaviour set up from 2026-11-09")
    lifestyle.sync(10)
    assert len(calls) == 10
    calls.clear()
    lifestyle.sync(10)
    assert calls == ["2026-11-10", "2026-11-09"]
    assert [r["date"] for r in read_rows(config.LIFESTYLE_CSV) if r["name"]] == ["2026-11-09", "2026-11-10"]


def test_sync_without_library_support_does_nothing(tmp_path, monkeypatch):
    """An older garminconnect without the method skips the source instead of failing the sync."""
    _setup(tmp_path, monkeypatch, object())
    lifestyle.sync(30)
    assert not config.LIFESTYLE_CSV.exists()
