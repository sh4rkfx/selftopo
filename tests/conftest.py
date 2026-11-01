from zoneinfo import ZoneInfo

import pytest

from selftopo import config


@pytest.fixture(autouse=True)
def vienna_time(monkeypatch):
    """The fixtures are written for Europe/Vienna, independent of settings.json and SELFTOPO_TZ."""
    monkeypatch.setattr(config, "TIMEZONE", ZoneInfo("Europe/Vienna"))
