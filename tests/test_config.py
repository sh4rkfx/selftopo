import json

from selftopo import config


def test_load_settings_missing_and_broken(tmp_path):
    assert config.load_settings(tmp_path / "settings.json") == {}
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    config.SETTINGS_PROBLEMS.clear()
    assert config.load_settings(broken) == {}
    assert "not valid JSON" in config.SETTINGS_PROBLEMS[0]
    listed = tmp_path / "list.json"
    listed.write_text("[]", encoding="utf-8")
    assert config.load_settings(listed) == {}


def test_load_settings_reads_object(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"timezone": "Europe/Berlin", "step_goal": 9000}), encoding="utf-8")
    assert config.load_settings(path) == {"timezone": "Europe/Berlin", "step_goal": 9000}


def test_timezone_environment_beats_settings_and_default_is_utc():
    zone, source = config.resolve_timezone("America/New_York", {"timezone": "Europe/Berlin"})
    assert (str(zone), source) == ("America/New_York", "environment")
    zone, source = config.resolve_timezone(None, {"timezone": "Europe/Berlin"})
    assert (str(zone), source) == ("Europe/Berlin", "settings.json")
    zone, source = config.resolve_timezone(None, {})
    assert (str(zone), source) == ("UTC", "default")


def test_unknown_timezone_falls_back_with_a_problem():
    config.SETTINGS_PROBLEMS.clear()
    zone, source = config.resolve_timezone(None, {"timezone": "Mars/Olympus"})
    assert (str(zone), source) == ("UTC", "default")
    assert "Mars/Olympus" in config.SETTINGS_PROBLEMS[0]


def test_grip_exercises_from_settings_or_defaults():
    assert "Left-hand Grip Strength" in config.resolve_grip_exercises({})
    names = config.resolve_grip_exercises({"grip_exercises": {"left": ["Grip L", " "], "right": ["Grip R"]}})
    assert names == ("Grip L", "Grip R")
    config.SETTINGS_PROBLEMS.clear()
    assert config.resolve_grip_exercises({"grip_exercises": ["x"]}) == config.resolve_grip_exercises({})
    assert config.SETTINGS_PROBLEMS
