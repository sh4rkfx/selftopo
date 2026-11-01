"""Bouldering splits: parsing, self evaluation and which sessions a sync fetches again."""

from datetime import date, timedelta

import pytest

from selftopo import climbs, config
from selftopo.csvstore import read_rows, write_rows

ACTIVITY = {"date": "2026-10-28", "activity_id": "111", "start_time_local": "2026-10-28 18:00:00", "type": "bouldering"}


def climb(start, grade, status, duration, hr=120, hr_max=150, scale="FONT", order=9):
    return {
        "type": "CLIMB_ACTIVE", "startTimeLocal": start, "status": status, "duration": duration,
        "averageHR": hr, "maxHR": hr_max, "gradeValue": {"valueKey": grade, "sortOrder": order, "scale": scale},
    }


def rest(start, duration):
    return {"type": "CLIMB_REST", "startTimeLocal": start, "duration": duration}


def test_one_row_per_boulder_with_the_rest_that_follows():
    splits = {"splits": [
        rest("2026-10-28T18:03:10.0", 95.6),  # listed out of order on purpose
        climb("2026-10-28T18:02:11.0", "6B", "CLIMB_COMPLETED", 28.2),
        climb("2026-10-28T18:04:46.0", "6C", "CLIMB_ATTEMPTED", 41.7, hr=131, hr_max=162),
    ]}
    rows = climbs.parse_splits(ACTIVITY, splits)
    assert [r["climb_no"] for r in rows] == [1, 2]
    assert rows[0] == {
        "date": "2026-10-28", "activity_id": "111", "climb_no": 1, "start_time_local": "2026-10-28 18:02:11",
        "grade": "6B", "grade_scale": "FONT", "grade_order": 9, "status": "completed",
        "duration_s": 28, "rest_after_s": 96, "avg_hr": 120, "max_hr": 150,
    }
    assert rows[1]["status"] == "attempted"
    assert rows[1]["rest_after_s"] is None


def test_rest_before_the_first_boulder_and_other_split_types_are_ignored():
    other = {"type": "INTERVAL_ACTIVE", "startTimeLocal": "2026-10-28T18:00:00.0"}
    splits = {"splits": [rest("2026-10-28T17:59:00.0", 60), other]}
    assert climbs.parse_splits(ACTIVITY, splits) == []
    assert climbs.parse_splits(ACTIVITY, None) == []


def test_session_summary_with_self_evaluation():
    rows = climbs.parse_splits(ACTIVITY, {"splits": [
        climb("2026-10-28T18:02:11.0", "6B", "CLIMB_COMPLETED", 30), rest("2026-10-28T18:02:41.0", 120),
        climb("2026-10-28T18:04:41.0", "6C", "CLIMB_ATTEMPTED", 20),
    ]})
    session = climbs.summarize(ACTIVITY, rows, {"summaryDTO": {"directWorkoutRpe": 70, "directWorkoutFeel": 75}})
    assert session == {
        "date": "2026-10-28", "activity_id": "111", "start_time_local": "2026-10-28 18:00:00",
        "climbs": 2, "completed": 1, "attempted": 1, "wall_s": 50, "rest_s": 120, "effort": 7.0, "feel": 75,
    }


def test_missing_self_evaluation_stays_empty():
    session = climbs.summarize(ACTIVITY, [], {"summaryDTO": {}})
    assert session["effort"] is None and session["feel"] is None and session["climbs"] == 0


class FakeClient:
    def __init__(self):
        self.calls = []

    def get_activity_typed_splits(self, activity_id):
        self.calls.append(activity_id)
        return {"splits": [climb(f"{self.dates[activity_id]}T18:00:00.0", "6A", "CLIMB_COMPLETED", 25)]}

    def get_activity(self, activity_id):
        return {"summaryDTO": {"directWorkoutRpe": 60, "directWorkoutFeel": 50}}


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ACTIVITIES_CSV", tmp_path / "garmin_activities.csv")
    monkeypatch.setattr(config, "CLIMBS_CSV", tmp_path / "garmin_climbs.csv")
    monkeypatch.setattr(config, "CLIMB_SESSIONS_CSV", tmp_path / "garmin_climb_sessions.csv")
    monkeypatch.setattr(config, "GARMIN_REQUEST_DELAY_S", 0)
    monkeypatch.setattr(config, "today", lambda: date(2026, 10, 29))
    return tmp_path


def test_sync_fetches_new_and_recent_sessions_and_keeps_older_ones(data_dir, monkeypatch):
    today = date(2026, 10, 29)
    days = {key: today - timedelta(days=n) for key, n in {"old": 20, "recent": 1, "new": 10, "hike": 2}.items()}
    write_rows(config.ACTIVITIES_CSV, ["date", "activity_id", "start_time_local", "type"], [
        {"date": d.isoformat(), "activity_id": key, "start_time_local": f"{d} 18:00:00",
         "type": "hiking" if key == "hike" else "bouldering"}
        for key, d in days.items()
    ])
    # "old" and "recent" were fetched before; "old" keeps its stored rows
    write_rows(config.CLIMB_SESSIONS_CSV, climbs.SESSION_FIELDS, [
        {"date": days["old"].isoformat(), "activity_id": "old", "climbs": 3},
        {"date": days["recent"].isoformat(), "activity_id": "recent", "climbs": 9},
    ])
    write_rows(config.CLIMBS_CSV, climbs.FIELDS, [
        {"date": days["old"].isoformat(), "activity_id": "old", "climb_no": n, "grade": "7A"} for n in (1, 2, 3)
    ])
    client = FakeClient()
    client.dates = {k: d.isoformat() for k, d in days.items()}
    monkeypatch.setattr(climbs.garmin, "connect", lambda: client)
    monkeypatch.setattr(climbs.garmin, "save_tokens", lambda c: None)

    climbs.sync(30)

    assert sorted(client.calls) == ["new", "recent"]
    sessions = {r["activity_id"]: r for r in read_rows(config.CLIMB_SESSIONS_CSV)}
    assert sessions["old"]["climbs"] == "3"
    recent = sessions["recent"]
    assert (recent["climbs"], recent["effort"], recent["feel"]) == ("1", "6.0", "50")
    grades = [(r["activity_id"], r["grade"]) for r in read_rows(config.CLIMBS_CSV)]
    assert grades == [("old", "7A"), ("old", "7A"), ("old", "7A"), ("new", "6A"), ("recent", "6A")]


def test_failed_request_keeps_the_stored_session(data_dir, monkeypatch):
    session = {"date": "2026-10-28", "activity_id": "111"}
    write_rows(config.ACTIVITIES_CSV, ["date", "activity_id", "type"], [{**session, "type": "bouldering"}])
    write_rows(config.CLIMB_SESSIONS_CSV, climbs.SESSION_FIELDS, [{**session, "climbs": 12}])

    class Failing(FakeClient):
        def get_activity_typed_splits(self, activity_id):
            raise RuntimeError("boom")

    monkeypatch.setattr(climbs.garmin, "connect", lambda: Failing())
    monkeypatch.setattr(climbs.garmin, "save_tokens", lambda c: None)
    climbs.sync(30)
    assert read_rows(config.CLIMB_SESSIONS_CSV)[0]["climbs"] == "12"
