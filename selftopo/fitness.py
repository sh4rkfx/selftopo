"""Garmin fitness metrics: VO2max, race predictions, hill and endurance score, training status.

Time series go to garmin_fitness.csv, one row per day with a value. Most of these change only
after suitable activities, so many days are empty. Values that Garmin only reports for today
(training status, load balance, fitness age, the endurance score's class limits) go to
garmin_fitness_status.json, overwritten on every run; acute and chronic load and the fitness age
are also written into today's CSV row, so their history builds up from the first run on.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any

from . import config, garmin
from .csvstore import read_rows, write_rows

log = logging.getLogger(__name__)

FIELDS = [
    "date", "vo2max", "vo2max_cycling",
    "race_5k_s", "race_10k_s", "race_half_s", "race_marathon_s",
    "hill_score", "hill_strength", "hill_endurance", "endurance_score",
    "acute_load", "chronic_load", "acwr", "fitness_age", "training_status",
]
# Columns each source fills; a fetch replaces them for every day of its window
SOURCE_COLUMNS = {
    "max_metrics": ["vo2max", "vo2max_cycling"],
    "race": ["race_5k_s", "race_10k_s", "race_half_s", "race_marathon_s"],
    "hill": ["hill_score", "hill_strength", "hill_endurance"],
    "endurance": ["endurance_score"],
}
BALANCE_PARTS = [("aerobic_low", "AerobicLow"), ("aerobic_high", "AerobicHigh"), ("anaerobic", "Anaerobic")]
TODAY_COLUMNS = ("acute_load", "chronic_load", "acwr", "fitness_age", "training_status")
MAX_RANGE_DAYS = 365  # race predictions accept at most a year per request


def _num(value: Any, digits: int = 1) -> float | int | None:
    if not isinstance(value, (int, float)):
        return None
    return int(round(value)) if digits == 0 else round(float(value), digits)


def parse_max_metrics(payload: Any) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in payload or []:
        generic, cycling = item.get("generic") or {}, item.get("cycling") or {}
        day = generic.get("calendarDate") or cycling.get("calendarDate")
        if not day:
            continue
        out[day] = {
            "vo2max": _num(generic.get("vo2MaxPreciseValue") or generic.get("vo2MaxValue")),
            "vo2max_cycling": _num(cycling.get("vo2MaxPreciseValue") or cycling.get("vo2MaxValue")),
        }
    return out


def parse_race_predictions(payload: Any) -> dict[str, dict[str, Any]]:
    items = payload if isinstance(payload, list) else [payload] if isinstance(payload, dict) else []
    return {
        item["calendarDate"]: {
            "race_5k_s": _num(item.get("time5K"), 0), "race_10k_s": _num(item.get("time10K"), 0),
            "race_half_s": _num(item.get("timeHalfMarathon"), 0), "race_marathon_s": _num(item.get("timeMarathon"), 0),
        }
        for item in items if item and item.get("calendarDate") and item.get("time5K")
    }


def parse_hill_score(payload: Any) -> dict[str, dict[str, Any]]:
    return {
        item["calendarDate"]: {
            "hill_score": _num(item.get("overallScore"), 0), "hill_strength": _num(item.get("strengthScore"), 0),
            "hill_endurance": _num(item.get("enduranceScore"), 0),
        }
        for item in (payload or {}).get("hillScoreDTOList") or []
        if item.get("calendarDate") and item.get("overallScore") is not None
    }


def parse_endurance_score(payload: Any) -> dict[str, dict[str, Any]]:
    """Weekly means, dated on the week's first day, plus today's value."""
    payload = payload or {}
    out = {
        week: {"endurance_score": _num(group.get("groupAverage"), 0)}
        for week, group in (payload.get("groupMap") or {}).items()
        if isinstance(group, dict) and group.get("groupAverage") is not None
    }
    current = payload.get("enduranceScoreDTO") or {}
    if current.get("calendarDate") and current.get("overallScore") is not None:
        out[current["calendarDate"]] = {"endurance_score": _num(current["overallScore"], 0)}
    return out


def _primary(device_map: Any) -> dict[str, Any]:
    """The entry of the primary training device in Garmin's {deviceId: {...}} maps."""
    entries = [v for v in (device_map or {}).values() if isinstance(v, dict)]
    return next((e for e in entries if e.get("primaryTrainingDevice")), entries[0] if entries else {})


def parse_status(training_status: Any, fitness_age: Any, endurance: Any) -> dict[str, Any]:
    """Today's values for garmin_fitness_status.json."""
    ts = training_status or {}
    status = _primary((ts.get("mostRecentTrainingStatus") or {}).get("latestTrainingStatusData"))
    load = status.get("acuteTrainingLoadDTO") or {}
    balance = _primary((ts.get("mostRecentTrainingLoadBalance") or {}).get("metricsTrainingLoadBalanceDTOMap"))
    age = fitness_age or {}
    current = (endurance or {}).get("enduranceScoreDTO") or {}
    limits = {
        key: current.get(f"classificationLowerLimit{name}")
        for key, name in [("intermediate", "Intermediate"), ("trained", "Trained"), ("well_trained", "WellTrained"),
                          ("expert", "Expert"), ("superior", "Superior"), ("elite", "Elite")]
    }
    return {
        "date": status.get("calendarDate") or config.today().isoformat(),
        "training_status": status.get("trainingStatusFeedbackPhrase"),
        "training_paused": status.get("trainingPaused"),
        "acute_load": load.get("dailyTrainingLoadAcute"),
        "chronic_load": load.get("dailyTrainingLoadChronic"),
        "chronic_load_min": load.get("minTrainingLoadChronic"),
        "chronic_load_max": load.get("maxTrainingLoadChronic"),
        "acwr": load.get("dailyAcuteChronicWorkloadRatio"),
        "acwr_status": load.get("acwrStatus"),
        "load_balance": {
            key: {
                "load": _num(balance.get(f"monthlyLoad{name}")),
                "target_min": balance.get(f"monthlyLoad{name}TargetMin"),
                "target_max": balance.get(f"monthlyLoad{name}TargetMax"),
            }
            for key, name in BALANCE_PARTS
        } if balance else None,
        "load_balance_feedback": balance.get("trainingBalanceFeedbackPhrase"),
        "fitness_age": _num(age.get("fitnessAge")),
        "achievable_fitness_age": _num(age.get("achievableFitnessAge")),
        "chronological_age": age.get("chronologicalAge"),
        "fitness_age_components": age.get("components"),
        "endurance_score": current.get("overallScore"),
        "endurance_limits": limits if any(v is not None for v in limits.values()) else None,
    }


def sync(days: int, refresh: bool = False) -> None:  # noqa: ARG001 - the window is always replaced
    end = config.today()
    start = end - timedelta(days=min(days, MAX_RANGE_DAYS) - 1)
    a, b = start.isoformat(), end.isoformat()
    client = garmin.connect()
    try:
        log.info("Garmin: fitness metrics %s to %s", a, b)
        fetched = {
            "max_metrics": parse_max_metrics(garmin.safe_call(client.get_max_metrics_range, a, b)),
            "race": parse_race_predictions(garmin.safe_call(lambda x, y: client.get_race_predictions(x, y, "daily"), a, b)),  # noqa: E501
            "hill": parse_hill_score(garmin.safe_call(client.get_hill_score, a, b)),
        }
        endurance_raw = garmin.safe_call(client.get_endurance_score, a, b)
        fetched["endurance"] = parse_endurance_score(endurance_raw)
        status = parse_status(
            garmin.safe_call(client.get_training_status, b),
            garmin.safe_call(client.get_fitnessage_data, b),
            endurance_raw,
        )
    finally:
        garmin.save_tokens(client)

    rows = {r["date"]: dict(r) for r in read_rows(config.FITNESS_CSV)}
    for source, values in fetched.items():
        if not values:
            continue  # failed or empty request: keep what is stored
        for day, row in rows.items():
            if a <= day <= b and day not in values:
                for col in SOURCE_COLUMNS[source]:
                    row[col] = None
        for day, value in values.items():
            rows.setdefault(day, {"date": day}).update(value)
    today = rows.setdefault(b, {"date": b})
    today.update({key: status.get(key) for key in TODAY_COLUMNS})
    kept = [r for r in rows.values() if any(r.get(c) not in (None, "") for c in FIELDS[1:])]
    count = write_rows(config.FITNESS_CSV, FIELDS, sorted(kept, key=lambda r: r["date"]))
    config.FITNESS_STATUS_JSON.write_text(json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Garmin: %d days with fitness metrics in %s", count, config.FITNESS_CSV)

