"""Garmin fitness metrics: parsing the endpoints and merging the window into the CSV."""

import json
from datetime import date

from selftopo import config, fitness
from selftopo.csvstore import read_rows, write_rows

# ruff: noqa: E501

DEVICE = {"1": {"primaryTrainingDevice": True, "calendarDate": "2026-10-29", "trainingStatusFeedbackPhrase": "PRODUCTIVE_1",
                "trainingPaused": False, "acuteTrainingLoadDTO": {
                    "dailyTrainingLoadAcute": 198, "dailyTrainingLoadChronic": 176, "minTrainingLoadChronic": 140.8,
                    "maxTrainingLoadChronic": 264.0, "dailyAcuteChronicWorkloadRatio": 1.1, "acwrStatus": "OPTIMAL"}}}


def test_parsers():
    assert fitness.parse_max_metrics([
        {"generic": {"calendarDate": "2026-09-18", "vo2MaxPreciseValue": 45.24, "vo2MaxValue": 45.0}, "cycling": None},
        {"generic": None, "cycling": None},
    ]) == {"2026-09-18": {"vo2max": 45.2, "vo2max_cycling": None}}
    assert fitness.parse_race_predictions([{"calendarDate": "2026-10-29", "time5K": 1704, "time10K": 3729,
                                            "timeHalfMarathon": 8667, "timeMarathon": 19922}]) == {
        "2026-10-29": {"race_5k_s": 1704, "race_10k_s": 3729, "race_half_s": 8667, "race_marathon_s": 19922}}
    assert fitness.parse_hill_score({"hillScoreDTOList": [
        {"calendarDate": "2026-08-06", "overallScore": 28, "strengthScore": 14, "enduranceScore": 17},
        {"calendarDate": "2026-08-07", "overallScore": None},
    ]}) == {"2026-08-06": {"hill_score": 28, "hill_strength": 14, "hill_endurance": 17}}
    assert fitness.parse_endurance_score({
        "groupMap": {"2026-10-16": {"groupAverage": 4840}, "2026-10-23": {"groupAverage": 4829}},
        "enduranceScoreDTO": {"calendarDate": "2026-10-29", "overallScore": 4821},
    }) == {"2026-10-16": {"endurance_score": 4840}, "2026-10-23": {"endurance_score": 4829}, "2026-10-29": {"endurance_score": 4821}}


def test_status_of_the_primary_device():
    status = fitness.parse_status(
        {"mostRecentTrainingStatus": {"latestTrainingStatusData": DEVICE}},
        {"fitnessAge": 37.1029, "achievableFitnessAge": 32.58, "chronologicalAge": 38},
        {"enduranceScoreDTO": {"overallScore": 4821, "classificationLowerLimitTrained": 5800}},
    )
    assert (status["training_status"], status["acute_load"], status["chronic_load"], status["acwr"]) == ("PRODUCTIVE_1", 198, 176, 1.1)
    assert (status["fitness_age"], status["endurance_limits"]["trained"]) == (37.1, 5800)
    assert status["load_balance"] is None


def test_sync_replaces_the_window_and_writes_today(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "FITNESS_CSV", tmp_path / "garmin_fitness.csv")
    monkeypatch.setattr(config, "FITNESS_STATUS_JSON", tmp_path / "garmin_fitness_status.json")
    monkeypatch.setattr(config, "today", lambda: date(2026, 10, 29))
    write_rows(config.FITNESS_CSV, fitness.FIELDS, [
        {"date": "2026-01-05", "vo2max": 47.0},  # outside the window: kept
        {"date": "2026-10-20", "vo2max": 99.0},  # inside, no longer reported: cleared, row dropped
    ])

    class Client:
        def get_max_metrics_range(self, a, b):
            return [{"generic": {"calendarDate": "2026-10-22", "vo2MaxPreciseValue": 45.2}}]

        def get_race_predictions(self, a, b, kind):
            return [{"calendarDate": "2026-10-29", "time5K": 1704}]

        def get_hill_score(self, a, b):
            return None  # failed

        def get_endurance_score(self, a, b):
            return {}

        def get_training_status(self, day):
            return {"mostRecentTrainingStatus": {"latestTrainingStatusData": DEVICE}}

        def get_fitnessage_data(self, day):
            return {"fitnessAge": 37.1}

    monkeypatch.setattr(fitness.garmin, "connect", lambda: Client())
    monkeypatch.setattr(fitness.garmin, "save_tokens", lambda c: None)
    fitness.sync(30)
    rows = {r["date"]: r for r in read_rows(config.FITNESS_CSV)}
    assert sorted(rows) == ["2026-01-05", "2026-10-22", "2026-10-29"]
    assert rows["2026-10-22"]["vo2max"] == "45.2"
    assert (rows["2026-10-29"]["race_5k_s"], rows["2026-10-29"]["acute_load"], rows["2026-10-29"]["fitness_age"]) == ("1704", "198", "37.1")
    assert json.loads(config.FITNESS_STATUS_JSON.read_text())["training_status"] == "PRODUCTIVE_1"
