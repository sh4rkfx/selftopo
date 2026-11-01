"""Bouldering sessions from the watch: one CSV row per logged boulder, one per session.

In bouldering mode the watch stores each boulder as a typed split: `CLIMB_ACTIVE` with the
grade, completed or attempted, the route timer and heart rate, followed by a `CLIMB_REST`
split for the rest. The activity list has none of this, so every session costs one request
for the splits and one for the self evaluation (perceived effort and feel), which sits in
the activity's summary.

The sessions come from garmin_activities.csv, so the `activities` source must run first.
"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Any

from . import config, garmin
from .csvstore import read_rows, write_rows

log = logging.getLogger(__name__)

CLIMB_TYPES = {"bouldering"}  # rope climbing (indoor_climbing) uses route grades, not boulder grades

FIELDS = [
    "date", "activity_id", "climb_no", "start_time_local",
    "grade", "grade_scale", "grade_order", "status",
    "duration_s", "rest_after_s", "avg_hr", "max_hr",
]
SESSION_FIELDS = [
    "date", "activity_id", "start_time_local", "climbs", "completed", "attempted",
    "wall_s", "rest_s", "effort", "feel",
]


def _number(value: Any, digits: int = 0) -> float | int | None:
    if value is None:
        return None
    try:
        result = round(float(value), digits)
    except (TypeError, ValueError):
        return None
    return int(result) if digits == 0 else result


def _local(value: Any) -> str:
    """'2026-10-28T18:02:11.0' -> '2026-10-28 18:02:11'."""
    return str(value or "").replace("T", " ")[:19]


def _status(value: Any) -> str | None:
    """CLIMB_COMPLETED -> completed, CLIMB_ATTEMPTED -> attempted; other values are kept lower case."""
    if not value:
        return None
    return str(value).removeprefix("CLIMB_").lower()


def parse_splits(activity: dict[str, Any], splits: dict[str, Any] | None) -> list[dict[str, Any]]:
    """One row per CLIMB_ACTIVE split, with the length of the rest that follows it."""
    order = lambda s: (_local(s.get("startTimeLocal")), s.get("messageIndex") or 0)  # noqa: E731
    items = sorted((splits or {}).get("splits") or [], key=order)
    rows: list[dict[str, Any]] = []
    for item in items:
        kind = item.get("type")
        if kind == "CLIMB_REST" and rows:
            rows[-1]["rest_after_s"] = (rows[-1]["rest_after_s"] or 0) + (_number(item.get("duration")) or 0)
            continue
        if kind != "CLIMB_ACTIVE":
            continue
        grade = item.get("gradeValue") or {}
        rows.append({
            "date": activity["date"],
            "activity_id": activity["activity_id"],
            "climb_no": len(rows) + 1,
            "start_time_local": _local(item.get("startTimeLocal")),
            "grade": grade.get("valueKey"),
            "grade_scale": grade.get("scale"),
            "grade_order": grade.get("sortOrder"),
            "status": _status(item.get("status")),
            "duration_s": _number(item.get("duration")),
            "rest_after_s": None,
            "avg_hr": _number(item.get("averageHR")),
            "max_hr": _number(item.get("maxHR")),
        })
    return rows


def _self_evaluation(details: dict[str, Any] | None) -> tuple[float | None, int | None]:
    """Perceived effort 1-10 and feel 0-100 (0 very weak, 50 normal, 100 very strong).

    Garmin stores the effort times ten (70 = 7) and the feel in steps of 25.
    """
    summary = (details or {}).get("summaryDTO") or {}
    effort = summary.get("directWorkoutRpe")
    feel = summary.get("directWorkoutFeel")
    return (_number(effort / 10, 1) if isinstance(effort, (int, float)) else None,
            _number(feel) if isinstance(feel, (int, float)) else None)


def summarize(activity: dict[str, Any], climbs: list[dict[str, Any]], details: dict[str, Any] | None) -> dict[str, Any]:
    effort, feel = _self_evaluation(details)
    return {
        "date": activity["date"],
        "activity_id": activity["activity_id"],
        "start_time_local": activity.get("start_time_local"),
        "climbs": len(climbs),
        "completed": sum(1 for c in climbs if c["status"] == "completed"),
        "attempted": sum(1 for c in climbs if c["status"] == "attempted"),
        "wall_s": sum(c["duration_s"] or 0 for c in climbs),
        "rest_s": sum(c["rest_after_s"] or 0 for c in climbs),
        "effort": effort,
        "feel": feel,
    }


def _sessions(start: date) -> list[dict[str, Any]]:
    rows = read_rows(config.ACTIVITIES_CSV)
    return [
        r for r in rows
        if r.get("type") in CLIMB_TYPES and r.get("activity_id") and date.fromisoformat(r["date"]) >= start
    ]


def sync(days: int, refresh: bool = False) -> None:
    """Fetch the boulders of every session in the last `days` days.

    Sessions already in the file are only fetched again when they are at most
    CLIMB_REFRESH_DAYS old (grades and the self evaluation can be edited in the app
    afterwards) or with `refresh`. Older sessions keep their rows.
    """
    end = config.today()
    start = end - timedelta(days=days - 1)
    refresh_from = end - timedelta(days=config.CLIMB_REFRESH_DAYS)
    candidates = _sessions(start)
    known = {str(r["activity_id"]) for r in read_rows(config.CLIMB_SESSIONS_CSV)}
    todo = [
        a for a in candidates
        if refresh or str(a["activity_id"]) not in known or date.fromisoformat(a["date"]) >= refresh_from
    ]
    if not todo:
        log.info("Garmin: no bouldering sessions to fetch (%d in the window)", len(candidates))
        return

    climbs: dict[str, list[dict[str, Any]]] = {}
    sessions: dict[str, dict[str, Any]] = {}
    client = garmin.connect()
    try:
        for activity in todo:
            activity_id = str(activity["activity_id"])
            log.info("Garmin: boulders of %s (%s)", activity["date"], activity_id)
            splits = garmin.safe_call(client.get_activity_typed_splits, activity_id)
            if splits is None:
                continue  # failed request: keep whatever the file already has for this session
            details = garmin.safe_call(client.get_activity, activity_id)
            climbs[activity_id] = parse_splits(activity, splits)
            sessions[activity_id] = summarize(activity, climbs[activity_id], details)
            time.sleep(config.GARMIN_REQUEST_DELAY_S)
    finally:
        garmin.save_tokens(client)
        _write(climbs, sessions)


def _write(climbs: dict[str, list[dict[str, Any]]], sessions: dict[str, dict[str, Any]]) -> None:
    """Replace the rows of every fetched session, keep all others."""
    kept_climbs = [r for r in read_rows(config.CLIMBS_CSV) if str(r["activity_id"]) not in climbs]
    all_climbs = kept_climbs + [row for rows in climbs.values() for row in rows]
    all_climbs.sort(key=lambda r: (str(r["date"]), str(r["activity_id"]), int(r["climb_no"])))
    kept_sessions = [r for r in read_rows(config.CLIMB_SESSIONS_CSV) if str(r["activity_id"]) not in sessions]
    all_sessions = sorted(
        kept_sessions + list(sessions.values()), key=lambda r: (str(r["date"]), str(r["start_time_local"]))
    )
    n_climbs = write_rows(config.CLIMBS_CSV, FIELDS, all_climbs)
    n_sessions = write_rows(config.CLIMB_SESSIONS_CSV, SESSION_FIELDS, all_sessions)
    log.info("Garmin: %d boulders in %d sessions (%d sessions fetched)", n_climbs, n_sessions, len(sessions))
