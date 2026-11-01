"""Blood pressure from Garmin Connect, one CSV row per measurement.

Garmin stores readings from the Index BPM cuff and manual entries in the Connect app. The watch
does not measure blood pressure. Notes typed with a reading are not copied.
"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Any

from . import config, garmin
from .csvstore import read_rows, write_rows

log = logging.getLogger(__name__)

FIELDS = ["date", "time_local", "systolic", "diastolic", "pulse", "source", "category"]
CHUNK_DAYS = 90  # one request per 90 days keeps each response small


def _int(value: Any) -> int | None:
    return int(round(value)) if isinstance(value, (int, float)) else None


def _measurements(node: Any) -> list[dict[str, Any]]:
    """Every dict with systolic and diastolic values, wherever Garmin nests it."""
    if isinstance(node, list):
        return [m for item in node for m in _measurements(item)]
    if not isinstance(node, dict):
        return []
    if isinstance(node.get("systolic"), (int, float)) and isinstance(node.get("diastolic"), (int, float)):
        return [node]
    return [m for value in node.values() for m in _measurements(value)]


def parse(payload: Any) -> list[dict[str, Any]]:
    rows = {}
    for m in _measurements(payload):
        stamp = str(m.get("measurementTimestampLocal") or m.get("measurementTimestampGMT") or "").replace("T", " ")[:19]
        if len(stamp) < 10:
            continue
        row = {
            "date": stamp[:10],
            "time_local": stamp[11:16] or None,
            "systolic": _int(m.get("systolic")),
            "diastolic": _int(m.get("diastolic")),
            "pulse": _int(m.get("pulse")),
            "source": m.get("sourceType"),
            "category": m.get("categoryName") or m.get("category"),
        }
        rows[(stamp, row["systolic"], row["diastolic"])] = row  # the same reading can appear twice
    return sorted(rows.values(), key=lambda r: (r["date"], r["time_local"] or ""))


def sync(days: int, refresh: bool = False) -> None:  # noqa: ARG001 - the window is always replaced
    """Replace all readings of the last `days` days, keep older ones. A failed request writes nothing."""
    end = config.today()
    start = end - timedelta(days=days - 1)
    client = garmin.connect()
    fetched: list[dict[str, Any]] = []
    try:
        chunk_start = start
        while chunk_start <= end:
            chunk_end = min(end, chunk_start + timedelta(days=CHUNK_DAYS - 1))
            log.info("Garmin: blood pressure %s to %s", chunk_start, chunk_end)
            fetched += parse(client.get_blood_pressure(chunk_start.isoformat(), chunk_end.isoformat()))
            chunk_start = chunk_end + timedelta(days=1)
            time.sleep(config.GARMIN_REQUEST_DELAY_S)
    finally:
        garmin.save_tokens(client)

    kept = [r for r in read_rows(config.BLOOD_PRESSURE_CSV) if date.fromisoformat(r["date"]) < start]
    rows = sorted(kept + fetched, key=lambda r: (str(r["date"]), str(r["time_local"] or "")))
    count = write_rows(config.BLOOD_PRESSURE_CSV, FIELDS, rows)
    log.info("Garmin: %d blood pressure readings in %s (%d fetched)", count, config.BLOOD_PRESSURE_CSV, len(fetched))
