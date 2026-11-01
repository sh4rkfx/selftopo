"""YAZIO

Parsing the daily summary, token handling and the replace-the-window sync.
"""

import json
import time
from datetime import date

import pytest

from selftopo import config, yazio
from selftopo.csvstore import read_rows, write_rows

pytestmark = pytest.mark.critical  # wrong nutrition values, lost days, or a broken or leaking login


def meal(kcal, protein=0, carb=0, fat=0):
    return {"nutrients": {
        "energy.energy": kcal, "nutrient.protein": protein, "nutrient.carb": carb, "nutrient.fat": fat,
    }}


def test_meals_are_summed_to_daily_totals(given):
    """All meals are summed per day: calories whole, grams to one decimal, water in millilitres."""
    summary = {
        "meals": {
            "breakfast": meal(450.4, 20.04, 55, 12),
            "lunch": meal(700, 45, 60, 30.26),
            "snack": meal(120, 2, 25, 1),
        },
        "water_intake": 2250.0,
    }
    given(summary=summary)
    row = yazio.parse_daily_summary(summary)
    assert row == {"calories_kcal": 1270, "protein_g": 67.0, "carbs_g": 140.0, "fat_g": 43.3, "water_ml": 2250}


def test_missing_nutrients_count_as_zero_and_nulls_are_ignored(given):
    """Missing nutrients and null values count as zero; a missing water value stays empty."""
    summary = {"meals": {
        "dinner": meal(600, 30, 70, 20), "snack": {"nutrients": {"energy.energy": None}}, "lunch": None,
    }}
    given(summary=summary)
    row = yazio.parse_daily_summary(summary)
    assert row["calories_kcal"] == 600
    assert row["water_ml"] is None


def test_day_without_entries_gives_no_row(given):
    """A day without food and water gives no row, so unlogged days do not show up as 0 kcal."""
    given(summaries=[None, {"meals": {"breakfast": meal(0)}, "water_intake": 0}])
    assert yazio.parse_daily_summary(None) is None
    assert yazio.parse_daily_summary({"meals": {"breakfast": meal(0)}, "water_intake": 0}) is None


def test_water_only_day_keeps_nutrients_empty(given):
    """A day with only water keeps the nutrients empty instead of 0 kcal."""
    given(summary={"meals": {}, "water_intake": 500})
    row = yazio.parse_daily_summary({"meals": {}, "water_intake": 500})
    assert row == {"calories_kcal": None, "protein_g": None, "carbs_g": None, "fat_g": None, "water_ml": 500}


def test_normalize_adds_absolute_expiry_and_drops_unknown_fields(given):
    """Tokens are stored with an absolute expiry and only the needed fields; no access token is an error."""
    given(response={"access_token": "a", "refresh_token": "r", "expires_in": 3600, "scope": "x"})
    tokens = yazio._normalize({"access_token": "a", "refresh_token": "r", "expires_in": 3600, "scope": "x"})
    assert set(tokens) == {"access_token", "refresh_token", "expires_at"}
    assert 3500 < tokens["expires_at"] - time.time() <= 3600
    assert "expires_at" not in yazio._normalize({"access_token": "a"})
    with pytest.raises(config.SetupError):
        yazio._normalize({})


def test_expiry_uses_a_safety_margin(given):
    """A token expiring within the safety margin counts as expired; one without expiry is tried first."""
    given(expires_in_s=[30, 3600, "unknown"], margin_s=yazio._EXPIRY_MARGIN_S)
    assert yazio._expired({"expires_at": time.time() + 30})
    assert not yazio._expired({"expires_at": time.time() + 3600})
    assert not yazio._expired({"access_token": "a"})  # unknown lifetime: try the request first


def test_is_configured_checks_file_and_secret(tmp_path, monkeypatch, given):
    """YAZIO counts as set up with a token file or the secret; the file is private to its owner (600)."""
    given(token_file="none, then written", secret_YAZIO_TOKENS_JSON="unset, then {}")
    monkeypatch.setattr(config, "YAZIO_TOKEN_DIR", tmp_path)
    monkeypatch.setattr(config, "YAZIO_TOKENS_JSON", None)
    assert not yazio.is_configured()
    monkeypatch.setattr(config, "YAZIO_TOKENS_JSON", "{}")
    assert yazio.is_configured()
    monkeypatch.setattr(config, "YAZIO_TOKENS_JSON", None)
    yazio._save_tokens({"access_token": "a"})
    assert yazio.is_configured()
    assert oct((tmp_path / "yazio_tokens.json").stat().st_mode & 0o777) == "0o600"


def test_expired_token_is_refreshed_and_the_new_refresh_token_is_kept(tmp_path, monkeypatch, given):
    """An expired access token is renewed and saved; without a new refresh token the old one is kept."""
    monkeypatch.setattr(config, "YAZIO_TOKEN_DIR", tmp_path)
    fresh = {"access_token": "new", "expires_at": time.time() + 3600}
    monkeypatch.setattr(yazio, "_token_request", lambda payload: fresh)
    yazio._save_tokens({"access_token": "old", "refresh_token": "r1", "expires_at": time.time() - 10})
    given(stored={"access_token": "old", "refresh_token": "r1", "expires_at": "10 s ago"},
          server_response={"access_token": "new", "expires_at": "in 1 h"})
    api = yazio._Api()
    assert api.tokens["access_token"] == "new"
    assert api.tokens["refresh_token"] == "r1"  # not rotated by the server: keep using the old one
    assert json.loads((tmp_path / "yazio_tokens.json").read_text())["access_token"] == "new"


def test_missing_tokens_in_ci_fail_with_instructions(tmp_path, monkeypatch, given):
    """In the workflow without tokens or credentials, YAZIO stops with instructions."""
    given(environment={"CI": "true"}, tokens="none", credentials="none")
    monkeypatch.setattr(config, "YAZIO_TOKEN_DIR", tmp_path)
    monkeypatch.setattr(config, "YAZIO_TOKENS_JSON", None)
    monkeypatch.setenv("CI", "true")
    with pytest.raises(config.SetupError, match="YAZIO_TOKENS_JSON"):
        yazio._Api()


def test_ci_logs_in_with_credentials_from_secrets_and_stores_tokens(tmp_path, monkeypatch, given):
    """In the workflow, YAZIO_EMAIL and YAZIO_PASSWORD log in; tokens are stored, the password is not."""
    given(environment={"CI": "true", "YAZIO_EMAIL": "a@b.c", "YAZIO_PASSWORD": "pw"}, tokens="none")
    monkeypatch.setattr(config, "YAZIO_TOKEN_DIR", tmp_path)
    monkeypatch.setattr(config, "YAZIO_TOKENS_JSON", None)
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("YAZIO_EMAIL", "a@b.c")
    monkeypatch.setenv("YAZIO_PASSWORD", "pw")
    seen = {}

    def fake_request(payload):
        seen.update(payload)
        return {"access_token": "t", "refresh_token": "r"}

    monkeypatch.setattr(yazio, "_token_request", fake_request)
    assert yazio.is_configured()
    assert yazio._Api().tokens["access_token"] == "t"
    assert (seen["username"], seen["grant_type"]) == ("a@b.c", "password")
    assert json.loads((tmp_path / "yazio_tokens.json").read_text())["refresh_token"] == "r"  # password is not stored
    assert "pw" not in (tmp_path / "yazio_tokens.json").read_text()


def test_failed_refresh_falls_back_to_credentials_only_if_set(tmp_path, monkeypatch, given):
    """If the refresh is refused, a new login happens only when credentials are set."""
    given(refresh="refused", credentials="none, then YAZIO_EMAIL and YAZIO_PASSWORD")
    monkeypatch.setattr(config, "YAZIO_TOKEN_DIR", tmp_path)
    monkeypatch.delenv("YAZIO_EMAIL", raising=False)
    monkeypatch.delenv("YAZIO_PASSWORD", raising=False)

    def request(payload):
        if payload["grant_type"] == "refresh_token":
            raise config.SetupError("refused")
        return {"access_token": "relogin"}

    monkeypatch.setattr(yazio, "_token_request", request)
    stale = {"access_token": "x", "refresh_token": "r", "expires_at": time.time() - 10}
    with pytest.raises(config.SetupError):
        yazio._Api._renew(stale)
    monkeypatch.setenv("YAZIO_EMAIL", "a@b.c")
    monkeypatch.setenv("YAZIO_PASSWORD", "pw")
    assert yazio._Api._renew(stale)["access_token"] == "relogin"


class FakeApi:
    def __init__(self, days):
        self.days = days

    def get(self, path, **params):
        return self.days.get(params["date"])

    def close(self):
        pass


def test_sync_replaces_the_window_and_keeps_older_rows(tmp_path, monkeypatch, given):
    """A 3-day sync replaces the stored days in the window and keeps older days.

    A day deleted in YAZIO disappears, a changed day is replaced.
    """
    monkeypatch.setattr(config, "NUTRITION_CSV", tmp_path / "nutrition_daily.csv")
    monkeypatch.setattr(config, "YAZIO_REQUEST_DELAY_S", 0)
    monkeypatch.setattr(config, "today", lambda: date(2026, 10, 29))
    write_rows(config.NUTRITION_CSV, yazio.FIELDS, [
        {"date": "2026-10-01", "calories_kcal": 2000},   # before the window: kept
        {"date": "2026-10-28", "calories_kcal": 9999},   # inside, deleted in YAZIO since: dropped
        {"date": "2026-10-29", "calories_kcal": 1},      # inside, changed: replaced
    ])
    monkeypatch.setattr(yazio, "_Api", lambda: FakeApi({
        "2026-10-29": {"meals": {"lunch": meal(800, 50, 90, 20)}, "water_intake": 1500},
    }))
    given(days=3, today="2026-10-29", stored=read_rows(config.NUTRITION_CSV),
          yazio="2026-10-29: lunch 800 kcal, 1500 ml water; other days empty")
    yazio.sync(days=3)
    rows = read_rows(config.NUTRITION_CSV)
    assert [(r["date"], r["calories_kcal"]) for r in rows] == [("2026-10-01", "2000"), ("2026-10-29", "800")]
    assert rows[1]["water_ml"] == "1500"
