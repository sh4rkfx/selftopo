"""Mapping of Garmin and Hevy responses to CSV rows."""

from datetime import datetime, timezone

from selftopo import activities, garmin, hevy


def epoch_ms(*args: int) -> float:
    return datetime(*args, tzinfo=timezone.utc).timestamp() * 1000


def test_body_composition_keeps_first_weigh_in_and_converts_grams():
    payload = {"dateWeightList": [
        {"calendarDate": "2026-10-13", "timestampGMT": 9, "weight": 82000},
        {"calendarDate": "2026-10-13", "timestampGMT": 2, "weight": 81200, "bodyFat": 15.0, "muscleMass": 38900},
    ]}
    day = garmin.parse_body_composition(payload)["2026-10-13"]
    assert day["weight_kg"] == 81.2
    assert day["fat_mass_kg"] == 12.18
    assert day["muscle_mass_kg"] == 38.9


def test_sleep_times_are_local_across_daylight_saving():
    summer = garmin.parse_sleep({"dailySleepDTO": {
        "sleepStartTimestampGMT": epoch_ms(2026, 10, 13, 21, 12),
        "sleepEndTimestampGMT": epoch_ms(2026, 10, 14, 4, 31),
    }})
    winter = garmin.parse_sleep({"dailySleepDTO": {"sleepStartTimestampGMT": epoch_ms(2027, 1, 12, 21, 45)}})
    assert summer["sleep_start_local"] == "2026-10-13 23:12"  # CEST, UTC+2
    assert summer["sleep_end_local"] == "2026-10-14 06:31"
    assert winter["sleep_start_local"] == "2027-01-12 22:45"  # CET, UTC+1


def test_missing_payloads_give_empty_values():
    assert garmin.parse_sleep(None)["sleep_score"] is None
    assert garmin.parse_hrv(None)["hrv_last_night_ms"] is None
    assert garmin.parse_daily_summary(None)["steps"] is None


def test_negative_stress_means_not_enough_data():
    assert garmin.parse_daily_summary({"averageStressLevel": -1})["stress_avg"] is None


def test_readiness_prefers_the_morning_value():
    payload = [
        {"score": 40, "level": "LOW", "timestampLocal": "2026-10-13T18:00", "inputContext": "AFTER_ACTIVITY"},
        {"score": 75, "level": "HIGH", "timestampLocal": "2026-10-13T07:00", "inputContext": "AFTER_WAKEUP_RESET"},
    ]
    assert garmin.parse_training_readiness(payload) == {"readiness_score": 75, "readiness_level": "HIGH"}


def test_activity_units():
    row = activities.parse_activity({
        "activityId": 7, "startTimeLocal": "2026-10-11 07:15:00", "activityType": {"typeKey": "hiking"},
        "duration": 23400, "movingDuration": 18000, "distance": 14250.7, "elevationGain": 1532.4,
        "averageHR": 117.6, "activityTrainingLoad": 241.26, "aerobicTrainingEffect": 3.94,
    })
    assert row["date"] == "2026-10-11"
    assert (row["duration_min"], row["moving_min"]) == (390.0, 300.0)
    assert (row["distance_km"], row["elevation_gain_m"], row["avg_hr"]) == (14.25, 1532, 118)
    assert (row["training_load"], row["aerobic_te"]) == (241.3, 3.9)


def test_activity_without_distance_has_empty_distance():
    assert activities.parse_activity({"startTimeLocal": "2026-10-14 18:00:00", "distance": 0})["distance_km"] is None


def test_hevy_dates_use_local_time():
    workout = {"id": "w", "title": "Pull", "start_time": "2026-10-13T22:30:00+00:00",
               "exercises": [{"title": "Pull Up (Weighted)", "sets": [{"type": "normal", "weight_kg": 10, "reps": 5}]}]}
    (row,) = hevy.flatten(workout)
    assert row["date"] == "2026-10-14"  # 00:30 in Vienna
