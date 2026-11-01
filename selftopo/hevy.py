"""Workout sets from the official Hevy API (requires Hevy Pro), one CSV row per set."""

from __future__ import annotations

import getpass
import logging
import os
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import config
from .csvstore import read_rows, write_rows

log = logging.getLogger(__name__)

FIELDS = [
    "date", "start_time", "workout_id", "workout_title",
    "exercise_index", "exercise", "exercise_template_id",
    "set_index", "set_type", "weight_kg", "reps", "rpe",
    "duration_s", "distance_m",
]
EXERCISE_FIELDS = [
    "exercise_template_id", "title", "type", "primary_muscle_group", "secondary_muscle_groups", "is_custom",
]


def _api_key() -> str:
    key = os.environ.get("HEVY_API_KEY")
    if key:
        return key
    if config.running_in_ci():
        raise config.SetupError("HEVY_API_KEY is not set (repository secret missing?).")
    return getpass.getpass("Hevy API key: ")


def _session() -> requests.Session:
    retry = Retry(
        total=4,
        backoff_factor=2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"api-key": _api_key(), "accept": "application/json"})
    return session


def _local_date(timestamp: str) -> date:
    """Hevy timestamps are UTC. Use the local day so late workouts land on the right date."""
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(config.TIMEZONE).date()


def iter_workouts(session: requests.Session, since: date) -> Iterator[dict[str, Any]]:
    """Yield workouts that started on or after `since`.

    The API lists workouts newest first, so paging stops at the first page
    without any workout in range.
    """
    page, page_count = 1, 1
    while page <= page_count:
        response = session.get(
            config.HEVY_API_URL,
            params={"page": page, "pageSize": config.HEVY_PAGE_SIZE},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        page_count = payload.get("page_count", 0)

        in_range = [
            workout for workout in payload.get("workouts", [])
            if workout.get("start_time") and _local_date(workout["start_time"]) >= since
        ]
        log.info("Hevy: page %d/%d, %d workouts in range", page, page_count, len(in_range))
        yield from in_range
        if not in_range:
            return
        page += 1


def flatten(workout: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Turn one workout into one row per set."""
    start = workout["start_time"]
    day = _local_date(start).isoformat()
    for ex_pos, exercise in enumerate(workout.get("exercises", [])):
        for set_pos, workout_set in enumerate(exercise.get("sets", [])):
            yield {
                "date": day,
                "start_time": start,
                "workout_id": workout.get("id"),
                "workout_title": workout.get("title"),
                "exercise_index": exercise.get("index", ex_pos),
                "exercise": exercise.get("title"),
                "exercise_template_id": exercise.get("exercise_template_id"),
                "set_index": workout_set.get("index", set_pos),
                "set_type": workout_set.get("type"),  # normal, warmup, dropset, failure
                "weight_kg": workout_set.get("weight_kg"),
                "reps": workout_set.get("reps"),
                "rpe": workout_set.get("rpe"),
                "duration_s": workout_set.get("duration_seconds"),
                "distance_m": workout_set.get("distance_meters"),
            }


def _sort_key(row: dict[str, Any]) -> tuple[str, str, int, int]:
    return (
        str(row["start_time"]),
        str(row["workout_id"] or ""),
        int(row["exercise_index"] or 0),
        int(row["set_index"] or 0),
    )


def sync(days: int, refresh: bool = False) -> None:  # noqa: ARG001 - the window is always replaced
    """Replace all sets of the last `days` days with fresh data, keep older ones.

    Replacing the whole window also picks up workouts that were edited or
    deleted in Hevy after the previous run.
    """
    since = config.today() - timedelta(days=days - 1)
    with _session() as session:
        fetched = [row for workout in iter_workouts(session, since) for row in flatten(workout)]

        kept = [row for row in read_rows(config.HEVY_CSV) if date.fromisoformat(row["date"]) < since]
        count = write_rows(config.HEVY_CSV, FIELDS, sorted(kept + fetched, key=_sort_key))
        log.info("Hevy: %d sets in %s (%d fetched)", count, config.HEVY_CSV, len(fetched))
        try:
            sync_exercises(session)
        except requests.RequestException as exc:  # the sets are saved; muscle groups can wait for the next run
            log.warning("Hevy: exercise templates failed: %s", exc)


def parse_template(template: dict[str, Any]) -> dict[str, Any]:
    """One exercise template; secondary muscle groups joined with "|"."""
    return {
        "exercise_template_id": template.get("id"),
        "title": template.get("title"),
        "type": template.get("type"),
        "primary_muscle_group": template.get("primary_muscle_group"),
        "secondary_muscle_groups": "|".join(m for m in template.get("secondary_muscle_groups") or [] if m),
        "is_custom": bool(template.get("is_custom")),
    }


def iter_templates(session: requests.Session) -> Iterator[dict[str, Any]]:
    """All exercise templates, Hevy's own and your custom ones."""
    page, page_count = 1, 1
    while page <= page_count:
        response = session.get(
            config.HEVY_TEMPLATES_URL, params={"page": page, "pageSize": config.HEVY_TEMPLATE_PAGE_SIZE}, timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        page_count = payload.get("page_count", 0)
        yield from payload.get("exercise_templates", [])
        page += 1


def sync_exercises(session: requests.Session) -> None:
    """Muscle groups of every exercise that appears in hevy_sets.csv."""
    used = {row["exercise_template_id"] for row in read_rows(config.HEVY_CSV) if row.get("exercise_template_id")}
    rows = [parse_template(t) for t in iter_templates(session) if t.get("id") in used]
    count = write_rows(config.HEVY_EXERCISES_CSV, EXERCISE_FIELDS, sorted(rows, key=lambda r: str(r["title"])))
    log.info("Hevy: %d exercises with muscle groups in %s", count, config.HEVY_EXERCISES_CSV)
