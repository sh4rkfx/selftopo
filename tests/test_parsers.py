"""Garmin and Hevy parsers

Mapping of Garmin and Hevy responses to CSV rows, and the Garmin login in the workflow.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from selftopo import activities, config, garmin, hevy

pytestmark = pytest.mark.critical  # wrong values in the CSV files, or a broken login


def epoch_ms(*args: int) -> float:
    return datetime(*args, tzinfo=timezone.utc).timestamp() * 1000


def test_body_composition_keeps_first_weigh_in_and_converts_grams(given):
    """With two weigh-ins on one day the earliest counts; grams become kilograms, fat mass is derived."""
    payload = {"dateWeightList": [
        {"calendarDate": "2026-10-13", "timestampGMT": 9, "weight": 82000},
        {"calendarDate": "2026-10-13", "timestampGMT": 2, "weight": 81200, "bodyFat": 15.0, "muscleMass": 38900},
    ]}
    given(payload=payload)
    day = garmin.parse_body_composition(payload)["2026-10-13"]
    assert day["weight_kg"] == 81.2
    assert day["fat_mass_kg"] == 12.18
    assert day["muscle_mass_kg"] == 38.9


def test_sleep_times_are_local_across_daylight_saving(given):
    """Sleep start and end are stored in local time: UTC+2 in October, UTC+1 in January (Vienna)."""
    given(timezone="Europe/Vienna", summer_utc="2026-10-13 21:12 to 2026-10-14 04:31", winter_utc="2027-01-12 21:45")
    summer = garmin.parse_sleep({"dailySleepDTO": {
        "sleepStartTimestampGMT": epoch_ms(2026, 10, 13, 21, 12),
        "sleepEndTimestampGMT": epoch_ms(2026, 10, 14, 4, 31),
    }})
    winter = garmin.parse_sleep({"dailySleepDTO": {"sleepStartTimestampGMT": epoch_ms(2027, 1, 12, 21, 45)}})
    assert summer["sleep_start_local"] == "2026-10-13 23:12"  # CEST, UTC+2
    assert summer["sleep_end_local"] == "2026-10-14 06:31"
    assert winter["sleep_start_local"] == "2027-01-12 22:45"  # CET, UTC+1


def test_missing_payloads_give_empty_values(given):
    """When Garmin returns nothing for sleep, HRV or the daily summary, the values stay empty."""
    given(payload=None)
    assert garmin.parse_sleep(None)["sleep_score"] is None
    assert garmin.parse_hrv(None)["hrv_last_night_ms"] is None
    assert garmin.parse_daily_summary(None)["steps"] is None


def test_negative_stress_means_not_enough_data(given):
    """Garmin's average stress of −1 means too little data and is stored as empty, not as −1."""
    given(payload={"averageStressLevel": -1})
    assert garmin.parse_daily_summary({"averageStressLevel": -1})["stress_avg"] is None


def test_readiness_prefers_the_morning_value(given):
    """Of several Training Readiness values per day, the one after waking up counts."""
    payload = [
        {"score": 40, "level": "LOW", "timestampLocal": "2026-10-13T18:00", "inputContext": "AFTER_ACTIVITY"},
        {"score": 75, "level": "HIGH", "timestampLocal": "2026-10-13T07:00", "inputContext": "AFTER_WAKEUP_RESET"},
    ]
    given(payload=payload)
    assert garmin.parse_training_readiness(payload) == {"readiness_score": 75, "readiness_level": "HIGH"}


def test_activity_units(given):
    """Activities in minutes, kilometres (2 decimals), whole metres and beats, load and effect to 0.1."""
    activity = {
        "activityId": 7, "startTimeLocal": "2026-10-11 07:15:00", "activityType": {"typeKey": "hiking"},
        "duration": 23400, "movingDuration": 18000, "distance": 14250.7, "elevationGain": 1532.4,
        "averageHR": 117.6, "activityTrainingLoad": 241.26, "aerobicTrainingEffect": 3.94,
    }
    given(activity=activity)
    row = activities.parse_activity(activity)
    assert row["date"] == "2026-10-11"
    assert (row["duration_min"], row["moving_min"]) == (390.0, 300.0)
    assert (row["distance_km"], row["elevation_gain_m"], row["avg_hr"]) == (14.25, 1532, 118)
    assert (row["training_load"], row["aerobic_te"]) == (241.3, 3.9)


def test_activity_without_distance_has_empty_distance(given):
    """A distance of 0 (strength training, bouldering) is stored as empty, so it does not lower averages."""
    given(activity={"startTimeLocal": "2026-10-14 18:00:00", "distance": 0})
    assert activities.parse_activity({"startTimeLocal": "2026-10-14 18:00:00", "distance": 0})["distance_km"] is None


def test_hevy_dates_use_local_time(given):
    """A Hevy workout at 22:30 UTC counts for the next day in Vienna (00:30), not the day before."""
    workout = {"id": "w", "title": "Pull", "start_time": "2026-10-13T22:30:00+00:00",
               "exercises": [{"title": "Pull Up (Weighted)", "sets": [{"type": "normal", "weight_kg": 10, "reps": 5}]}]}
    given(workout=workout, timezone="Europe/Vienna")
    (row,) = hevy.flatten(workout)
    assert row["date"] == "2026-10-14"  # 00:30 in Vienna


# --------------------------------------------------------------------------- Garmin login in CI


class _FakeGarmin:
    """Stands in for garminconnect.Garmin: login outcome set per test."""

    outcome: object = (None, None)
    created: list = []

    def __init__(self, email=None, password=None, return_on_mfa=False, **_):
        self.email, self.password, self.return_on_mfa = email, password, return_on_mfa
        self.client = self
        _FakeGarmin.created.append(self)

    def login(self, tokenstore=None):
        if tokenstore is not None:
            raise RuntimeError("no tokens")
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome

    def dump(self, path):
        Path(path).mkdir(parents=True, exist_ok=True)
        (Path(path) / "garmin_tokens.json").write_text("{}", encoding="utf-8")


def _ci_login_env(monkeypatch, tmp_path, outcome, password=True):
    monkeypatch.setattr(garmin, "Garmin", _FakeGarmin)
    monkeypatch.setattr(config, "TOKEN_DIR", tmp_path / "tokens")
    monkeypatch.setattr(config, "TOKEN_JSON", None)
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("GARMIN_EMAIL", "a@example.com")
    if password:
        monkeypatch.setenv("GARMIN_PASSWORD", "secret")
    else:
        monkeypatch.delenv("GARMIN_PASSWORD", raising=False)
    _FakeGarmin.outcome = outcome
    _FakeGarmin.created = []
    return garmin, config


def test_ci_password_login_stores_tokens(monkeypatch, tmp_path, given):
    """In the workflow, GARMIN_EMAIL and GARMIN_PASSWORD log in when there are no tokens.

    The login must return on two-step verification instead of waiting for a code, and the tokens
    are stored for the next run.
    """
    garmin, config = _ci_login_env(monkeypatch, tmp_path, (None, None))
    given(environment={"CI": "true", "GARMIN_EMAIL": "a@example.com", "GARMIN_PASSWORD": "(set)"},
          tokens="none", garmin_login="succeeds")
    client = garmin._login()
    assert client.return_on_mfa and client.email == "a@example.com"
    assert (config.TOKEN_DIR / "garmin_tokens.json").exists()


def test_ci_password_login_with_mfa_explains_the_local_way(monkeypatch, tmp_path, given):
    """With two-step verification the workflow stops with instructions and stores no tokens."""
    garmin, config = _ci_login_env(monkeypatch, tmp_path, ("needs_mfa", None))
    given(environment={"CI": "true", "GARMIN_EMAIL": "a@example.com", "GARMIN_PASSWORD": "(set)"},
          garmin_login="asks for two-step verification")
    with pytest.raises(config.SetupError, match="two-step verification"):
        garmin._login()
    assert not (config.TOKEN_DIR / "garmin_tokens.json").exists()


def test_ci_password_login_refused(monkeypatch, tmp_path, given):
    """A refused password login stops with a clear message instead of a stack trace."""
    garmin, config = _ci_login_env(monkeypatch, tmp_path, RuntimeError("401 Unauthorized"))
    given(environment={"CI": "true", "GARMIN_EMAIL": "a@example.com", "GARMIN_PASSWORD": "(set)"},
          garmin_login="RuntimeError('401 Unauthorized')")
    with pytest.raises(config.SetupError, match="refused the login"):
        garmin._login()


def test_ci_without_tokens_or_password_names_both_ways(monkeypatch, tmp_path, given):
    """Without tokens and password the workflow names both ways to log in and does not try one."""
    garmin, config = _ci_login_env(monkeypatch, tmp_path, (None, None), password=False)
    given(environment={"CI": "true", "GARMIN_EMAIL": "a@example.com"}, tokens="none")
    with pytest.raises(config.SetupError, match="GARMIN_PASSWORD secrets"):
        garmin._login()
    assert _FakeGarmin.created == []
