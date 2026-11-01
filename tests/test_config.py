"""Settings

settings.json and the time zone: missing, broken and valid files, and which source wins.
"""

import json

import pytest

from selftopo import config


@pytest.mark.critical  # a broken file must not stop the daily sync
def test_load_settings_missing_and_broken(tmp_path, given):
    """A missing settings.json, broken JSON or a JSON list give empty settings, so the sync still runs.

    Broken JSON is reported as a problem in the sync log.
    """
    given(files={"settings.json": "(missing)", "broken.json": "{not json", "list.json": "[]"})
    assert config.load_settings(tmp_path / "settings.json") == {}
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    config.SETTINGS_PROBLEMS.clear()
    assert config.load_settings(broken) == {}
    assert "not valid JSON" in config.SETTINGS_PROBLEMS[0]
    listed = tmp_path / "list.json"
    listed.write_text("[]", encoding="utf-8")
    assert config.load_settings(listed) == {}


@pytest.mark.critical
def test_load_settings_reads_object(tmp_path, given):
    """A valid settings.json is read unchanged."""
    path = tmp_path / "settings.json"
    given(settings={"timezone": "Europe/Berlin", "step_goal": 9000})
    path.write_text(json.dumps({"timezone": "Europe/Berlin", "step_goal": 9000}), encoding="utf-8")
    assert config.load_settings(path) == {"timezone": "Europe/Berlin", "step_goal": 9000}


@pytest.mark.critical  # the time zone decides on which day a value is stored
def test_timezone_environment_beats_settings_and_default_is_utc(given):
    """The time zone comes from SELFTOPO_TZ, then settings.json, otherwise UTC, with its source.

    The source lets the sync warn when it falls back to UTC.
    """
    given(environment="America/New_York", settings={"timezone": "Europe/Berlin"})
    zone, source = config.resolve_timezone("America/New_York", {"timezone": "Europe/Berlin"})
    assert (str(zone), source) == ("America/New_York", "environment")
    zone, source = config.resolve_timezone(None, {"timezone": "Europe/Berlin"})
    assert (str(zone), source) == ("Europe/Berlin", "settings.json")
    zone, source = config.resolve_timezone(None, {})
    assert (str(zone), source) == ("UTC", "default")


@pytest.mark.critical
def test_unknown_timezone_falls_back_with_a_problem(given):
    """An unknown time zone falls back to UTC and is named in the problems the sync reports."""
    given(settings={"timezone": "Mars/Olympus"})
    config.SETTINGS_PROBLEMS.clear()
    zone, source = config.resolve_timezone(None, {"timezone": "Mars/Olympus"})
    assert (str(zone), source) == ("UTC", "default")
    assert "Mars/Olympus" in config.SETTINGS_PROBLEMS[0]


def test_grip_exercises_from_settings_or_defaults(given):
    """Grip exercises come from settings.json or default to Hevy's English and German names.

    Blank names are dropped; a wrong format falls back to the defaults and is reported.
    """
    given(settings={"grip_exercises": {"left": ["Grip L", " "], "right": ["Grip R"]}}, wrong_format=["x"])
    assert "Left-hand Grip Strength" in config.resolve_grip_exercises({})
    names = config.resolve_grip_exercises({"grip_exercises": {"left": ["Grip L", " "], "right": ["Grip R"]}})
    assert names == ("Grip L", "Grip R")
    config.SETTINGS_PROBLEMS.clear()
    assert config.resolve_grip_exercises({"grip_exercises": ["x"]}) == config.resolve_grip_exercises({})
    assert config.SETTINGS_PROBLEMS
