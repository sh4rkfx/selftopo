"""Garmin activities (bouldering, hiking, cycling, runs, ...), one CSV row per activity.

The list endpoint returns a summary per activity. Sport-specific details such as
climbing routes are only in the full activity; `python -m selftopo dump-raw`
saves those for one day so they can be added here later.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from . import config, garmin
from .csvstore import read_rows, write_rows

log = logging.getLogger(__name__)

FIELDS = [
    "date", "start_time_local", "activity_id", "type", "name",
    "duration_min", "moving_min", "distance_km", "elevation_gain_m",
    "avg_hr", "max_hr", "calories", "training_load", "aerobic_te", "anaerobic_te",
    "location",
]


def _rounded(value: Any, digits: int = 0, factor: float = 1.0) -> float | int | None:
    if value is None:
        return None
    result = round(value * factor, digits)
    return int(result) if digits == 0 else result


def parse_activity(activity: dict[str, Any]) -> dict[str, Any]:
    start_local = activity.get("startTimeLocal") or ""  # local time at the activity, "YYYY-MM-DD HH:MM:SS"
    return {
        "date": start_local[:10],
        "start_time_local": start_local,
        "activity_id": activity.get("activityId"),
        "type": (activity.get("activityType") or {}).get("typeKey"),  # bouldering, hiking, gravel_cycling
        "name": activity.get("activityName"),
        "duration_min": _rounded(activity.get("duration"), 1, 1 / 60),
        "moving_min": _rounded(activity.get("movingDuration"), 1, 1 / 60),
        "distance_km": _rounded(activity.get("distance") or None, 2, 1 / 1000),
        "elevation_gain_m": _rounded(activity.get("elevationGain")),
        "avg_hr": _rounded(activity.get("averageHR")),
        "max_hr": _rounded(activity.get("maxHR")),
        "calories": _rounded(activity.get("calories")),
        "training_load": _rounded(activity.get("activityTrainingLoad"), 1),
        "aerobic_te": _rounded(activity.get("aerobicTrainingEffect"), 1),
        "anaerobic_te": _rounded(activity.get("anaerobicTrainingEffect"), 1),
        "location": activity.get("locationName"),
    }


def sync(days: int, refresh: bool = False) -> None:  # noqa: ARG001 - the window is always replaced
    """Replace all activities of the last `days` days with fresh data, keep older ones.

    Replacing the window picks up renamed, retyped or deleted activities. A failed
    request raises before anything is written, so it never empties the window.
    """
    end = config.today()
    start = end - timedelta(days=days - 1)
    client = garmin.connect()
    try:
        log.info("Garmin: activities %s to %s", start, end)
        raw = client.get_activities_by_date(start.isoformat(), end.isoformat(), sortorder="asc")
    finally:
        garmin.save_tokens(client)

    fetched = [parse_activity(a) for a in raw or [] if a.get("startTimeLocal")]
    kept = [row for row in read_rows(config.ACTIVITIES_CSV) if date.fromisoformat(row["date"]) < start]
    rows = sorted(kept + fetched, key=lambda r: (str(r["start_time_local"]), str(r["activity_id"])))
    count = write_rows(config.ACTIVITIES_CSV, FIELDS, rows)
    log.info("Garmin: %d activities in %s (%d fetched)", count, config.ACTIVITIES_CSV, len(fetched))
