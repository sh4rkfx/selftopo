"""Daily food intake from YAZIO: calories, protein, carbohydrates, fat and water, one CSV row per day.

YAZIO has no public API. This module talks to the private API of the YAZIO app, the same one the
app uses, with the app's own client credentials. It can break or be blocked without notice, and
YAZIO's terms may not allow it. Only the five daily totals are read, never the individual meals.
"""

from __future__ import annotations

import getpass
import json
import logging
import os
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import config
from .csvstore import read_rows, write_rows

log = logging.getLogger(__name__)

FIELDS = ["date", "calories_kcal", "protein_g", "carbs_g", "fat_g", "water_ml"]

# Nutrient keys in the daily summary: kcal for energy, grams for the macronutrients.
ENERGY, PROTEIN, CARBS, FAT = "energy.energy", "nutrient.protein", "nutrient.carb", "nutrient.fat"

# Client credentials embedded in every YAZIO app installation (they identify the app, not you).
# Override with YAZIO_CLIENT_ID and YAZIO_CLIENT_SECRET if YAZIO ever rotates them.
_APP_CLIENT_ID = "1_4hiybetvfksgw40o0sog4s884kwc840wwso8go4k8c04goo4c"
_APP_CLIENT_SECRET = "6rok2m65xuskgkgogw40wkkk8sw0osg84s8cggsc4woos4s8o"

_TOKEN_FILE_NAME = "yazio_tokens.json"
_EXPIRY_MARGIN_S = 120


# --------------------------------------------------------------------------- tokens


def _token_file() -> Path:
    return config.YAZIO_TOKEN_DIR / _TOKEN_FILE_NAME


def _has_credentials() -> bool:
    return bool(os.environ.get("YAZIO_EMAIL") and os.environ.get("YAZIO_PASSWORD"))


def is_configured() -> bool:
    """True if tokens or login credentials exist, so a plain `sync` includes YAZIO without prompting."""
    return _token_file().exists() or bool(config.YAZIO_TOKENS_JSON) or _has_credentials()


def _load_tokens() -> dict[str, Any] | None:
    if _token_file().exists():
        return json.loads(_token_file().read_text(encoding="utf-8"))
    if config.YAZIO_TOKENS_JSON:
        return json.loads(config.YAZIO_TOKENS_JSON)
    return None


def _save_tokens(tokens: dict[str, Any]) -> None:
    """Persist the tokens (owner-only file). The refresh token may rotate on every refresh."""
    path = _token_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(tokens), encoding="utf-8")
    path.chmod(0o600)


def export_tokens() -> str:
    """Token JSON for the YAZIO_TOKENS_JSON secret. Grants account access: keep it private."""
    tokens = _load_tokens()
    if not tokens:
        raise config.SetupError("No YAZIO tokens found. Run `python -m selftopo yazio-login` first.")
    return json.dumps(tokens)


def _normalize(response: dict[str, Any]) -> dict[str, Any]:
    """Keep what is needed to continue later; add an absolute expiry if the server sent a lifetime."""
    tokens = {key: response[key] for key in ("access_token", "refresh_token", "token_type") if key in response}
    if "access_token" not in tokens:
        raise config.SetupError("YAZIO login response contained no access token.")
    if response.get("expires_in"):
        tokens["expires_at"] = time.time() + float(response["expires_in"])
    return tokens


def _token_request(payload: dict[str, Any]) -> dict[str, Any]:
    body = {
        "client_id": os.environ.get("YAZIO_CLIENT_ID", _APP_CLIENT_ID),
        "client_secret": os.environ.get("YAZIO_CLIENT_SECRET", _APP_CLIENT_SECRET),
        **payload,
    }
    response = requests.post(f"{config.YAZIO_API_URL}/oauth/token", json=body, timeout=30)
    if response.status_code in (400, 401, 403):
        raise config.SetupError(
            f"YAZIO refused the login (HTTP {response.status_code}). "
            "Wrong password, or the tokens expired: run `python -m selftopo yazio-login` again."
        )
    response.raise_for_status()
    return _normalize(response.json())


def login_interactive() -> dict[str, Any]:
    """Log in with email and password and store the tokens. The password is never saved.

    YAZIO_EMAIL and YAZIO_PASSWORD skip the prompts. In CI they come from repository secrets: set
    them for the first run, then delete the password secret again (the tokens are kept in the cache).
    """
    email = os.environ.get("YAZIO_EMAIL") or input("YAZIO email: ").strip()
    password = os.environ.get("YAZIO_PASSWORD") or getpass.getpass("YAZIO password: ")
    tokens = _token_request({"username": email, "password": password, "grant_type": "password"})
    _save_tokens(tokens)
    if "refresh_token" not in tokens:
        log.warning("YAZIO sent no refresh token: the login will stop working when the access token expires.")
    return tokens


def _refresh(tokens: dict[str, Any]) -> dict[str, Any]:
    if not tokens.get("refresh_token"):
        raise config.SetupError("YAZIO access token expired and no refresh token is stored. Log in again.")
    fresh = _token_request({"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]})
    fresh.setdefault("refresh_token", tokens["refresh_token"])  # some servers do not rotate it
    _save_tokens(fresh)
    log.info("YAZIO: access token refreshed")
    return fresh


def _expired(tokens: dict[str, Any]) -> bool:
    return "expires_at" in tokens and tokens["expires_at"] - time.time() < _EXPIRY_MARGIN_S


# --------------------------------------------------------------------------- API


class _Api:
    """Authenticated GET requests; refreshes the token once on 401 and retries."""

    def __init__(self) -> None:
        tokens = _load_tokens()
        if tokens is None:
            if config.running_in_ci() and not _has_credentials():
                raise config.SetupError(
                    "No YAZIO tokens. Run `python -m selftopo yazio-login` locally and store the output of "
                    "`yazio-tokens` in the YAZIO_TOKENS_JSON secret, or set the YAZIO_EMAIL and "
                    "YAZIO_PASSWORD secrets for one run."
                )
            tokens = login_interactive()
        elif _expired(tokens):
            tokens = self._renew(tokens)
        else:
            _save_tokens(tokens)  # also seeds the token file from the secret, so rotations persist
        self.tokens = tokens
        retry = Retry(total=4, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",))
        self.session = requests.Session()
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    @staticmethod
    def _renew(tokens: dict[str, Any]) -> dict[str, Any]:
        """Refresh the tokens; log in again with YAZIO_EMAIL and YAZIO_PASSWORD if that fails and they are set."""
        try:
            return _refresh(tokens)
        except config.SetupError:
            if not _has_credentials():
                raise
            log.warning("YAZIO: token refresh failed, logging in again with the stored credentials")
            return login_interactive()

    def get(self, path: str, **params: str) -> Any:
        for attempt in (1, 2):
            response = self.session.get(
                f"{config.YAZIO_API_URL}/{path}", params=params, timeout=30,
                headers={"Authorization": f"Bearer {self.tokens['access_token']}"},
            )
            if response.status_code == 401 and attempt == 1:
                self.tokens = self._renew(self.tokens)
                continue
            if response.status_code == 401:
                raise config.SetupError("YAZIO rejected the refreshed token. Run `yazio-login` again.")
            response.raise_for_status()
            return response.json()

    def close(self) -> None:
        self.session.close()


# --------------------------------------------------------------------------- parsing


def parse_daily_summary(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Daily totals from `widgets/daily-summary`, or None for a day without any entry.

    The summary lists nutrients per meal; they are summed here. A day with water but no food keeps
    the nutrient columns empty instead of 0, so it does not look like a day of fasting.
    """
    payload = payload or {}
    meals = payload.get("meals") or {}
    totals = {ENERGY: 0.0, PROTEIN: 0.0, CARBS: 0.0, FAT: 0.0}
    for meal in meals.values() if isinstance(meals, dict) else []:
        nutrients = (meal or {}).get("nutrients") or {}
        for key in totals:
            if nutrients.get(key) is not None:
                totals[key] += float(nutrients[key])

    water = payload.get("water_intake")
    water_ml = round(float(water)) if water else None
    has_food = totals[ENERGY] > 0
    if not has_food and not water_ml:
        return None
    return {
        "calories_kcal": round(totals[ENERGY]) if has_food else None,
        "protein_g": round(totals[PROTEIN], 1) if has_food else None,
        "carbs_g": round(totals[CARBS], 1) if has_food else None,
        "fat_g": round(totals[FAT], 1) if has_food else None,
        "water_ml": water_ml,
    }


# --------------------------------------------------------------------------- sync


def sync(days: int, refresh: bool = False) -> None:  # noqa: ARG001 - the window is always replaced
    """Replace the last `days` days with fresh data and keep older rows.

    The window is replaced as a whole, so entries edited or deleted in YAZIO are picked up. Days
    without any entry produce no row.
    """
    today = config.today()
    since = today - timedelta(days=days - 1)
    api = _Api()
    fetched: list[dict[str, Any]] = []
    try:
        for offset in range(days):
            day = since + timedelta(days=offset)
            row = parse_daily_summary(api.get("user/widgets/daily-summary", date=day.isoformat()))
            if row:
                fetched.append({"date": day.isoformat(), **row})
            if offset % 50 == 49:
                log.info("YAZIO: %d/%d days", offset + 1, days)
            time.sleep(config.YAZIO_REQUEST_DELAY_S)
    finally:
        api.close()

    kept = [row for row in read_rows(config.NUTRITION_CSV) if date.fromisoformat(row["date"]) < since]
    count = write_rows(config.NUTRITION_CSV, FIELDS, sorted(kept + fetched, key=lambda row: row["date"]))
    log.info("YAZIO: %d days in %s (%d logged in the last %d days)", count, config.NUTRITION_CSV, len(fetched), days)


def dump_raw(day: date) -> Path:
    """Save the raw responses of one day, to check the field mapping against the real app data."""
    api = _Api()
    try:
        data = {
            "daily-summary": api.get("user/widgets/daily-summary", date=day.isoformat()),
            "water-intake": api.get("user/water-intake", date=day.isoformat()),
        }
    finally:
        api.close()
    config.DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    path = config.DEBUG_DIR / f"yazio_raw_{day.isoformat()}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
