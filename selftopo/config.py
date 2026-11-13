"""Settings shared by all modules. Everything can be overridden via environment variables."""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _env(name: str, default: str | None = None) -> str | None:
    """SELFTOPO_<name>, or HEALTHSYNC_<name> from before the project was renamed."""
    return os.environ.get(f"SELFTOPO_{name}", os.environ.get(f"HEALTHSYNC_{name}", default))


# Output
DATA_DIR = Path(_env("DATA_DIR", "data"))
GARMIN_CSV = DATA_DIR / "garmin_daily.csv"
ACTIVITIES_CSV = DATA_DIR / "garmin_activities.csv"
CLIMBS_CSV = DATA_DIR / "garmin_climbs.csv"  # one row per logged boulder
CLIMB_SESSIONS_CSV = DATA_DIR / "garmin_climb_sessions.csv"  # one row per bouldering session
BLOOD_PRESSURE_CSV = DATA_DIR / "garmin_blood_pressure.csv"  # one row per reading
LIFESTYLE_CSV = DATA_DIR / "garmin_lifestyle.csv"  # one row per Lifestyle Logging behaviour and day
FITNESS_CSV = DATA_DIR / "garmin_fitness.csv"  # VO2max, race predictions, hill and endurance score
FITNESS_STATUS_JSON = DATA_DIR / "garmin_fitness_status.json"  # today's training status and fitness age
HEVY_CSV = DATA_DIR / "hevy_sets.csv"
HEVY_EXERCISES_CSV = DATA_DIR / "hevy_exercises.csv"  # muscle groups of the exercises in hevy_sets.csv
NUTRITION_CSV = DATA_DIR / "nutrition_daily.csv"
INSIGHTS_JSON = DATA_DIR / "insights.json"
SETTINGS_JSON = DATA_DIR / "settings.json"  # personal settings, shared with the dashboard
SYNC_STATUS_JSON = DATA_DIR / "sync_status.json"  # when each source was last fetched, for the dashboard
DEBUG_DIR = Path("debug")

# Problems found in settings.json or the environment, logged once by the command line
SETTINGS_PROBLEMS: list[str] = []


def load_settings(path: Path) -> dict[str, Any]:
    """settings.json as a dict; missing or unreadable means no settings."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        SETTINGS_PROBLEMS.append(f"{path} is not valid JSON ({exc}); using the defaults")
        return {}
    if not isinstance(data, dict):
        SETTINGS_PROBLEMS.append(f"{path} must hold a JSON object; using the defaults")
        return {}
    return data


def resolve_timezone(env_value: str | None, settings: dict[str, Any]) -> tuple[ZoneInfo, str]:
    """Time zone and where it came from: environment, settings.json or the UTC default."""
    for value, source in ((env_value, "environment"), (settings.get("timezone"), "settings.json")):
        if not value:
            continue
        try:
            return ZoneInfo(str(value)), source
        except (ZoneInfoNotFoundError, ValueError):
            SETTINGS_PROBLEMS.append(f"Unknown time zone {value!r} in the {source}")
    return ZoneInfo("UTC"), "default"


DEFAULT_GRIP_EXERCISES = {
    "left": ["Left-hand Grip Strength", "Handkraft links"],
    "right": ["Right-hand Grip Strength", "Handkraft rechts"],
}


def resolve_grip_exercises(settings: dict[str, Any]) -> tuple[str, ...]:
    """Names of the Hevy exercises that hold grip-strength measurements, both hands."""
    grip = settings.get("grip_exercises")
    if grip is None:
        grip = DEFAULT_GRIP_EXERCISES
    if not isinstance(grip, dict):
        SETTINGS_PROBLEMS.append('"grip_exercises" in settings.json must be {"left": [...], "right": [...]}')
        grip = DEFAULT_GRIP_EXERCISES
    names = [n for side in ("left", "right") for n in grip.get(side) or [] if isinstance(n, str) and n.strip()]
    return tuple(n.strip() for n in names)


SETTINGS = load_settings(SETTINGS_JSON)

# Garmin uses local calendar days; Hevy timestamps are converted to the same zone. Set it in
# settings.json ("timezone": "Europe/Vienna") or with SELFTOPO_TZ; without either it is UTC.
TIMEZONE, TIMEZONE_SOURCE = resolve_timezone(_env("TZ"), SETTINGS)

# Garmin authentication
TOKEN_DIR = Path(os.environ.get("GARMIN_TOKEN_DIR", Path.home() / ".garminconnect"))
TOKEN_JSON = os.environ.get("GARMIN_TOKENS_JSON")  # seed tokens for CI, from `export-tokens`

# Garmin fetching
GARMIN_REQUEST_DELAY_S = 0.6  # pause between days to stay well below rate limits
GARMIN_REFRESH_DAYS = 3  # always re-fetch today and the previous N days (late syncs)
CLIMB_REFRESH_DAYS = 7  # bouldering sessions this recent are fetched again (grades can be edited later)

# Hevy fetching
HEVY_API_URL = "https://api.hevyapp.com/v1/workouts"
HEVY_TEMPLATES_URL = "https://api.hevyapp.com/v1/exercise_templates"
HEVY_TEMPLATE_PAGE_SIZE = 100  # maximum allowed by the API
HEVY_PAGE_SIZE = 10  # maximum allowed by the API
# Hevy exercises that hold grip-strength measurements, not training sets: left out of hard sets,
# tonnage and strength form. "grip_exercises" in settings.json, read by the dashboard as well.
GRIP_EXERCISES = resolve_grip_exercises(SETTINGS)

# YAZIO: unofficial app API. Tokens live in a file (local runs, CI cache) or in YAZIO_TOKENS_JSON (CI seed).
YAZIO_API_URL = os.environ.get("YAZIO_API_URL", "https://yzapi.yazio.com/v15")
YAZIO_TOKEN_DIR = Path(os.environ.get("YAZIO_TOKEN_DIR", Path.home() / ".yazio"))
YAZIO_TOKENS_JSON = os.environ.get("YAZIO_TOKENS_JSON")
YAZIO_REQUEST_DELAY_S = 0.3


class SetupError(RuntimeError):
    """Missing or invalid credentials. Printed without a traceback."""


def today() -> date:
    return datetime.now(TIMEZONE).date()


def running_in_ci() -> bool:
    return os.environ.get("CI", "").lower() == "true"
