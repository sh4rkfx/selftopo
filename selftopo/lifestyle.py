"""Lifestyle Logging from Garmin Connect: one CSV row per behaviour and day.

Lifestyle Logging is the habit diary in the Garmin Connect app (alcohol, caffeine, late meals and
behaviours you add yourself). Garmin does not document the response. The mapping below follows
the `garminconnect` library and other projects that read the same endpoint, not real data from
this project: if columns stay empty, run `python -m selftopo dump-raw --date YYYY-MM-DD` and
compare the `lifestyle` part of the dump with `parse`.

Assumed shape: `{"dailyLogsReport": [{"behaviourId", "name", "measurementType", "logStatus",
"sleepRelated", "details": [{"amount", ...}]}]}`. Garmin lists every behaviour set up in the app on
every day; `logStatus` is "YES", "NO" or missing (not answered that day).
"""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from . import config, garmin
from .csvstore import read_rows, write_rows

log = logging.getLogger(__name__)

FIELDS = ["date", "behaviour_id", "name", "kind", "status", "value", "sleep_related"]
# Days with nothing set up in a row, newest first, after which a first sync stops asking:
# without this, a user who never set up Lifestyle Logging would cost one request per day.
EMPTY_DAYS_STOP = 7


def _amount(detail: Any) -> float:
    value = detail.get("amount") if isinstance(detail, dict) else None
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def parse(payload: Any, day: str) -> list[dict[str, Any]]:
    """Rows of one day. `value`: 1/0 for a yes/no behaviour, the logged amount for a counted one
    (a yes without an amount counts as 1), empty when the behaviour was not answered that day.
    Never 0 for "not answered": no entry is not the same as "no"."""
    report = payload.get("dailyLogsReport") if isinstance(payload, dict) else None
    if not isinstance(report, list):
        return []
    rows = []
    for index, entry in enumerate(report):
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        behaviour_id = entry.get("behaviourId")
        kind = "count" if entry.get("measurementType") == "QUANTITY" else "check"
        status = entry.get("logStatus")
        value: float | None = None
        if status == "NO":
            value = 0
        elif status == "YES":
            details = entry.get("details") if isinstance(entry.get("details"), list) else []
            total = sum(_amount(d) for d in details) if kind == "count" else 0
            value = total if total > 0 else 1
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        rows.append({
            "date": day,
            "behaviour_id": str(behaviour_id) if behaviour_id not in (None, "") else f"#{index}",
            "name": name,
            "kind": kind,
            "status": status.lower() if status in ("YES", "NO") else None,
            "value": value,
            "sleep_related": {True: 1, False: 0}.get(entry.get("sleepRelated")),
        })
    return rows


def sync(days: int, refresh: bool = False) -> None:
    """Fetch the last `days` days, one request per day, newest first.

    Days already stored are skipped except the newest ones (answers are often logged the next
    morning), unless `refresh`. A failed request leaves the stored rows of that day untouched.
    """
    end = config.today()
    start = end - timedelta(days=days - 1)
    refresh_from = end - timedelta(days=config.GARMIN_REFRESH_DAYS)
    stored = read_rows(config.LIFESTYLE_CSV)
    by_day: dict[str, list[dict[str, Any]]] = {}
    for row in stored:
        by_day.setdefault(row["date"], []).append(row)

    client = garmin.connect()
    endpoint = getattr(client, "get_lifestyle_logging_data", None)
    if endpoint is None:
        log.warning("Lifestyle Logging: the installed garminconnect has no get_lifestyle_logging_data, skipped")
        return
    fetched = empty_run = 0
    try:
        day = end
        while day >= start:
            iso = day.isoformat()
            if refresh or day >= refresh_from or iso not in by_day:
                payload = garmin.safe_call(endpoint, iso)
                time.sleep(config.GARMIN_REQUEST_DELAY_S)
                if payload is not None:
                    rows = parse(payload, iso)
                    fetched += 1
                    if rows:
                        by_day[iso] = rows
                        empty_run = 0
                    else:
                        by_day.pop(iso, None)
                        empty_run += 1
                    if not stored and empty_run >= EMPTY_DAYS_STOP and fetched == empty_run:
                        log.info("Lifestyle Logging: nothing set up in the last %d days, stopped", EMPTY_DAYS_STOP)
                        break
            day -= timedelta(days=1)
    finally:
        garmin.save_tokens(client)
        rows = [r for key in sorted(by_day) for r in sorted(by_day[key], key=lambda r: str(r["name"]))]
        if rows or stored:
            count = write_rows(config.LIFESTYLE_CSV, FIELDS, rows)
            log.info("Lifestyle Logging: %d rows in %s (%d days fetched)", count, config.LIFESTYLE_CSV, fetched)

