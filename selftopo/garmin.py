"""Daily health metrics from Garmin Connect, one CSV row per calendar day.

Uses the unofficial `garminconnect` library. The JSON field names mapped below are
not documented by Garmin and may change. If a column stays empty, run
`python -m selftopo dump-raw --date YYYY-MM-DD` and compare the raw responses
with the `parse_*` functions in this module.
"""

from __future__ import annotations

import getpass
import json
import logging
import os
import time
from collections.abc import Callable, Iterator
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from garminconnect import Garmin, GarminConnectTooManyRequestsError

from . import config
from .csvstore import read_rows, write_rows

log = logging.getLogger(__name__)

FIELDS = [
    "date",
    # Body composition (first weigh-in of the day)
    "weight_kg", "body_fat_pct", "fat_mass_kg", "muscle_mass_kg",
    "bone_mass_kg", "body_water_pct", "bmi",
    # Sleep (the night ending on this date)
    "sleep_score", "sleep_hours", "sleep_start_local", "sleep_end_local",
    "deep_sleep_min", "light_sleep_min", "rem_sleep_min", "awake_min",
    # Heart rate variability (overnight)
    "hrv_last_night_ms", "hrv_weekly_avg_ms", "hrv_status",
    "hrv_baseline_low_ms", "hrv_baseline_high_ms",
    # Daily summary
    "resting_hr", "body_battery_wake", "body_battery_high", "body_battery_low",
    "body_battery_charged", "body_battery_drained", "stress_avg", "steps",
    "calories_total", "calories_active",
    # Training readiness (morning value)
    "readiness_score", "readiness_level",
]


# --------------------------------------------------------------------------- auth


_session: Garmin | None = None


def connect() -> Garmin:
    """Return the logged-in client, logging in on first use.

    Daily metrics and activities share one session, so a sync logs in only once.
    """
    global _session
    if _session is None:
        _session = _login()
    return _session


def _login() -> Garmin:
    """Log in, trying credential sources from least to most interactive.

    1. Token file in TOKEN_DIR: local runs, or restored from the CI cache.
    2. GARMIN_TOKENS_JSON: seed tokens from the repository secret (CI).
    3. Email, password and MFA prompt: local runs only; writes a new token file.
    """
    attempts = []
    if (config.TOKEN_DIR / "garmin_tokens.json").exists():
        attempts.append(("token file", str(config.TOKEN_DIR)))
    if config.TOKEN_JSON:
        attempts.append(("GARMIN_TOKENS_JSON", config.TOKEN_JSON))

    for source, tokenstore in attempts:
        client = Garmin()
        try:
            client.login(tokenstore)
        except GarminConnectTooManyRequestsError:
            raise
        except Exception as exc:  # expired, revoked or malformed tokens
            log.warning("Garmin login via %s failed: %s", source, exc)
            continue
        log.info("Garmin: logged in via %s", source)
        return client

    if config.running_in_ci():
        raise config.SetupError(
            "No usable Garmin tokens. Create new ones locally and update the "
            "GARMIN_TOKENS_JSON secret (see README, 'Token renewal')."
        )
    return login_interactive()


def login_interactive() -> Garmin:
    """Log in with email and password, then store tokens in TOKEN_DIR."""
    email = os.environ.get("GARMIN_EMAIL") or input("Garmin email: ").strip()
    password = os.environ.get("GARMIN_PASSWORD") or getpass.getpass("Garmin password: ")
    client = Garmin(email, password, prompt_mfa=lambda: input("Garmin MFA code: ").strip())
    client.login(str(config.TOKEN_DIR))  # the library writes the token file after login
    save_tokens(client)
    return client


def save_tokens(client: Garmin) -> None:
    """Persist the current tokens. Garmin may rotate the refresh token on every run."""
    client.client.dump(str(config.TOKEN_DIR))


def export_tokens() -> str:
    """Token JSON for the GARMIN_TOKENS_JSON secret. Grants account access: keep it private."""
    client = connect()
    save_tokens(client)
    return client.client.dumps()


# --------------------------------------------------------------------------- parsing


def _get(obj: Any, *path: str, default: Any = None) -> Any:
    """Read a nested key, returning `default` as soon as a level is missing."""
    for key in path:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(key)
        if obj is None:
            return default
    return obj


def _grams_to_kg(value: float | None) -> float | None:
    return round(value / 1000, 2) if value else None


def _seconds_to_minutes(value: float | None) -> int | None:
    return round(value / 60) if value is not None else None


def parse_body_composition(payload: Any) -> dict[str, dict[str, Any]]:
    """Map calendar date to body metrics, keeping the first weigh-in of each day."""
    entries = _get(payload, "dateWeightList", default=[])
    entries = sorted(entries, key=lambda e: e.get("timestampGMT") or e.get("date") or 0)

    by_day: dict[str, dict[str, Any]] = {}
    for entry in entries:
        day = entry.get("calendarDate")
        if not day or day in by_day:
            continue
        weight = _grams_to_kg(entry.get("weight"))
        fat_pct = entry.get("bodyFat")
        by_day[day] = {
            "weight_kg": weight,
            "body_fat_pct": fat_pct,
            "fat_mass_kg": round(weight * fat_pct / 100, 2) if weight and fat_pct else None,
            "muscle_mass_kg": _grams_to_kg(entry.get("muscleMass")),
            "bone_mass_kg": _grams_to_kg(entry.get("boneMass")),
            "body_water_pct": entry.get("bodyWater"),
            "bmi": round(entry["bmi"], 1) if entry.get("bmi") else None,
        }
    return by_day


def _local_time(epoch_ms: float | None) -> str | None:
    """Garmin's GMT epoch milliseconds as local wall time in TIMEZONE, "YYYY-MM-DD HH:MM".

    The GMT timestamps are converted instead of using Garmin's "Local" variants,
    which are not true epochs. On travel days this shows home time.
    """
    if not epoch_ms:
        return None
    moment = datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc).astimezone(config.TIMEZONE)
    return moment.strftime("%Y-%m-%d %H:%M")


def parse_sleep(payload: Any) -> dict[str, Any]:
    dto = _get(payload, "dailySleepDTO", default={})
    total_s = dto.get("sleepTimeSeconds")
    return {
        "sleep_score": _get(dto, "sleepScores", "overall", "value"),
        "sleep_hours": round(total_s / 3600, 2) if total_s else None,
        "sleep_start_local": _local_time(dto.get("sleepStartTimestampGMT")),
        "sleep_end_local": _local_time(dto.get("sleepEndTimestampGMT")),
        "deep_sleep_min": _seconds_to_minutes(dto.get("deepSleepSeconds")),
        "light_sleep_min": _seconds_to_minutes(dto.get("lightSleepSeconds")),
        "rem_sleep_min": _seconds_to_minutes(dto.get("remSleepSeconds")),
        "awake_min": _seconds_to_minutes(dto.get("awakeSleepSeconds")),
    }


def parse_hrv(payload: Any) -> dict[str, Any]:
    summary = _get(payload, "hrvSummary", default={})
    return {
        "hrv_last_night_ms": summary.get("lastNightAvg"),
        "hrv_weekly_avg_ms": summary.get("weeklyAvg"),
        "hrv_status": summary.get("status"),
        "hrv_baseline_low_ms": _get(summary, "baseline", "balancedLow"),
        "hrv_baseline_high_ms": _get(summary, "baseline", "balancedUpper"),
    }


def parse_daily_summary(payload: Any) -> dict[str, Any]:
    summary = payload if isinstance(payload, dict) else {}
    stress = summary.get("averageStressLevel")
    return {
        "resting_hr": summary.get("restingHeartRate"),
        "body_battery_wake": summary.get("bodyBatteryAtWakeTime"),
        "body_battery_high": summary.get("bodyBatteryHighestValue"),
        "body_battery_low": summary.get("bodyBatteryLowestValue"),
        "body_battery_charged": summary.get("bodyBatteryChargedValue"),
        "body_battery_drained": summary.get("bodyBatteryDrainedValue"),
        "stress_avg": stress if stress is not None and stress >= 0 else None,  # -1/-2: too little data
        "steps": summary.get("totalSteps"),
        "calories_total": summary.get("totalKilocalories"),  # resting + active, Garmin's estimate
        "calories_active": summary.get("activeKilocalories"),
    }


def parse_training_readiness(payload: Any) -> dict[str, Any]:
    """Pick the morning value. Garmin recalculates readiness after each activity."""
    entries = payload if isinstance(payload, list) else [payload]
    entries = [e for e in entries if isinstance(e, dict) and e.get("score") is not None]
    if not entries:
        return {"readiness_score": None, "readiness_level": None}

    morning = next((e for e in entries if e.get("inputContext") == "AFTER_WAKEUP_RESET"), None)
    if morning is None:
        morning = min(entries, key=lambda e: e.get("timestampLocal") or e.get("timestamp") or "")
    return {"readiness_score": morning.get("score"), "readiness_level": morning.get("level")}


# --------------------------------------------------------------------------- fetching


def safe_call(endpoint: Callable[..., Any], *args: str) -> Any:
    """Call one endpoint. A single failing metric must not abort the whole day.

    Rate limiting is re-raised: continuing would only make the block last longer.
    The library already retries transient errors itself.
    """
    try:
        return endpoint(*args)
    except GarminConnectTooManyRequestsError:
        raise
    except Exception as exc:
        log.warning("Garmin: %s(%s) failed: %s", endpoint.__name__, ", ".join(args), exc)
        return None


def fetch_raw_day(client: Garmin, day: date) -> dict[str, Any]:
    iso = day.isoformat()
    return {
        "sleep": safe_call(client.get_sleep_data, iso),
        "hrv": safe_call(client.get_hrv_data, iso),
        "daily_summary": safe_call(client.get_stats, iso),
        "training_readiness": safe_call(client.get_training_readiness, iso),
    }


def parse_day(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        **parse_sleep(raw["sleep"]),
        **parse_hrv(raw["hrv"]),
        **parse_daily_summary(raw["daily_summary"]),
        **parse_training_readiness(raw["training_readiness"]),
    }


def _days(start: date, end: date) -> Iterator[date]:
    for offset in range((end - start).days + 1):
        yield start + timedelta(days=offset)


def _merge(existing: dict[str, Any] | None, day: str, update: dict[str, Any]) -> dict[str, Any]:
    """Overlay new values; a failed request (None) never erases an earlier value."""
    row = dict(existing or {"date": day})
    row.update({key: value for key, value in update.items() if value is not None})
    return row


def sync(days: int, refresh: bool = False) -> None:
    """Fetch the last `days` days. Days already stored are skipped, except the newest ones.

    `refresh` fetches every day again, for example to fill columns added later.
    """
    end = config.today()
    start = end - timedelta(days=days - 1)
    refresh_from = end - timedelta(days=config.GARMIN_REFRESH_DAYS)
    rows = {row["date"]: row for row in read_rows(config.GARMIN_CSV)}

    client = connect()
    try:
        log.info("Garmin: body composition %s to %s", start, end)
        body = parse_body_composition(
            safe_call(client.get_body_composition, start.isoformat(), end.isoformat())
        )
        for iso, metrics in body.items():
            rows[iso] = _merge(rows.get(iso), iso, metrics)

        for day in _days(start, end):
            iso = day.isoformat()
            # Skip complete older days. Rows that so far only hold a weigh-in, or
            # nights without a sleep score (watch not worn), are fetched again.
            if not refresh and iso in rows and day < refresh_from and rows[iso].get("sleep_score"):
                continue
            log.info("Garmin: %s", iso)
            rows[iso] = _merge(rows.get(iso), iso, parse_day(fetch_raw_day(client, day)))
            time.sleep(config.GARMIN_REQUEST_DELAY_S)
    except GarminConnectTooManyRequestsError:
        log.error("Garmin: rate limit reached, saving the days fetched so far")
        raise
    finally:
        count = write_rows(config.GARMIN_CSV, FIELDS, (rows[key] for key in sorted(rows)))
        log.info("Garmin: %d days in %s", count, config.GARMIN_CSV)
        save_tokens(client)


def dump_fitness(days: int = 120) -> Path:
    """Raw responses of the fitness endpoints (VO2max, race predictions, hill and endurance score,
    training status, fitness age) for checking the field mapping. Written next to the data files."""
    client = connect()
    end = config.today()
    start = (end - timedelta(days=days - 1)).isoformat()
    iso = end.isoformat()
    raw = {
        "max_metrics": safe_call(client.get_max_metrics_range, start, iso),
        "race_predictions": safe_call(lambda a, b: client.get_race_predictions(a, b, "daily"), start, iso),
        "race_predictions_latest": safe_call(lambda: client.get_race_predictions()),
        "hill_score": safe_call(client.get_hill_score, start, iso),
        "endurance_score": safe_call(client.get_endurance_score, start, iso),
        "training_status": safe_call(client.get_training_status, iso),
        "fitness_age": safe_call(client.get_fitnessage_data, iso),
    }
    save_tokens(client)
    path = config.DATA_DIR / "debug" / "garmin_fitness_raw.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw, indent=1, ensure_ascii=False), encoding="utf-8")
    return path


def dump_raw(day: date) -> Path:
    """Write all raw responses for one day to DEBUG_DIR, for checking the field mapping."""
    client = connect()
    raw = fetch_raw_day(client, day)
    raw["body_composition"] = safe_call(client.get_body_composition, day.isoformat(), day.isoformat())
    # Activity summaries plus full details, e.g. to find climbing-specific fields
    activities = safe_call(client.get_activities_by_date, day.isoformat(), day.isoformat()) or []
    raw["activities"] = activities
    raw["activity_details"] = {
        str(a["activityId"]): safe_call(client.get_activity, str(a["activityId"]))
        for a in activities if a.get("activityId")
    }
    # One split per boulder for bouldering sessions, see climbs.py
    raw["typed_splits"] = {
        str(a["activityId"]): safe_call(client.get_activity_typed_splits, str(a["activityId"]))
        for a in activities if a.get("activityId") and (a.get("activityType") or {}).get("typeKey") == "bouldering"
    }
    save_tokens(client)

    config.DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    path = config.DEBUG_DIR / f"garmin_raw_{day.isoformat()}.json"
    path.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
