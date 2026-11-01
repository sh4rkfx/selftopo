"""Blood pressure

Parsing Garmin's nested response and replacing the stored window.
"""

# ruff: noqa: E501

from datetime import date

import pytest

from selftopo import bloodpressure, config
from selftopo.csvstore import read_rows, write_rows

pytestmark = pytest.mark.critical  # wrong or lost readings


def reading(stamp, sys_, dia, pulse=58, source="MANUAL"):
    return {"systolic": sys_, "diastolic": dia, "pulse": pulse, "sourceType": source, "categoryName": "NORMAL",
            "measurementTimestampLocal": stamp, "notes": "private"}


def test_parse_finds_readings_anywhere_and_drops_notes(given):
    """Readings from every summary become rows: whole numbers, duplicates removed, notes dropped.

    The notes field can hold private text and is never stored. Empty responses give no rows.
    """
    payload = {"measurementSummaries": [
        {"startDate": "2026-10-28", "highSystolic": 125, "measurements": [reading("2026-10-28T07:12:00.0", 124, 78)]},
        {"startDate": "2026-10-29", "measurements": [reading("2026-10-29T21:40:00.0", 131.0, 84, None, "INDEX_BPM"),
                                                     reading("2026-10-29T21:40:00.0", 131, 84, None, "INDEX_BPM")]},
    ]}
    given(payload=payload)
    rows = bloodpressure.parse(payload)
    assert rows == [
        {"date": "2026-10-28", "time_local": "07:12", "systolic": 124, "diastolic": 78, "pulse": 58, "source": "MANUAL", "category": "NORMAL"},
        {"date": "2026-10-29", "time_local": "21:40", "systolic": 131, "diastolic": 84, "pulse": None, "source": "INDEX_BPM", "category": "NORMAL"},
    ]
    assert bloodpressure.parse(None) == [] and bloodpressure.parse({"measurementSummaries": []}) == []


def test_sync_replaces_the_window_in_chunks(tmp_path, monkeypatch, given):
    """A 100-day sync asks Garmin in chunks of 90 days and replaces the stored window.

    A reading deleted in Garmin disappears from the CSV, readings before the window stay.
    """
    monkeypatch.setattr(config, "BLOOD_PRESSURE_CSV", tmp_path / "bp.csv")
    monkeypatch.setattr(config, "GARMIN_REQUEST_DELAY_S", 0)
    monkeypatch.setattr(config, "today", lambda: date(2026, 10, 30))
    write_rows(config.BLOOD_PRESSURE_CSV, bloodpressure.FIELDS, [
        {"date": "2025-01-01", "time_local": "08:00", "systolic": 120, "diastolic": 75},  # outside: kept
        {"date": "2026-10-01", "time_local": "08:00", "systolic": 199, "diastolic": 99},  # inside, deleted in Garmin
    ])
    calls = []

    class Client:
        def get_blood_pressure(self, a, b):
            calls.append((a, b))
            return {"measurementSummaries": [{"measurements": [reading("2026-10-29T07:00:00.0", 122, 76)]}]} if b == "2026-10-30" else {}

    monkeypatch.setattr(bloodpressure.garmin, "connect", lambda: Client())
    monkeypatch.setattr(bloodpressure.garmin, "save_tokens", lambda c: None)
    given(days=100, today="2026-10-30", stored=read_rows(config.BLOOD_PRESSURE_CSV),
          garmin="one reading on 2026-10-29 in the last chunk, nothing else")
    bloodpressure.sync(100)
    assert calls == [("2026-07-23", "2026-10-20"), ("2026-10-21", "2026-10-30")]
    assert [(r["date"], r["systolic"]) for r in read_rows(config.BLOOD_PRESSURE_CSV)] == [("2025-01-01", "120"), ("2026-10-29", "122")]
