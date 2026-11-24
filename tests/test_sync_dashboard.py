"""When the data was fetched, as the dashboard shows it

The header names the time of the last sync from sync_status.json, not only when the page loaded.
It turns yellow after 30 hours, names sources that failed, and offers the run on GitHub. The
helpers run in Node; without Node these tests are skipped.
"""

# ruff: noqa: E501

import json

import pytest
from jsdashboard import run

HELPERS = ["DAY", "SYNC_LATE_AFTER_H", "SYNC_SOURCE_LABELS", "syncInfo"]
NOW = "Date.parse('2026-11-24T09:00:00Z')"


def info(status):
    return run(HELPERS, f"syncInfo({json.dumps(status)}, {NOW})")


@pytest.mark.parametrize(("finished", "late"), [("2026-11-24T06:41:00Z", False), ("2026-11-23T04:00:00Z", False), ("2026-11-23T02:59:00Z", True)])
def test_late_after_30_hours(given, finished, late):
    """A sync older than 30 hours is late (yellow chip and a note); GitHub often starts scheduled runs hours late."""
    got = info({"finished_at": finished, "trigger": "schedule", "sources": {}})
    given(finished=finished, info=got)
    assert got["late"] is late


def test_failed_sources_are_named_and_the_run_is_linked(given):
    """Failed sources come with their names; only a github.com run link is offered; a manual start is marked."""
    got = info({"finished_at": "2026-11-24T06:41:00Z", "trigger": "workflow_dispatch", "run_url": "https://github.com/me/data/actions/runs/1",
                "sources": {"garmin": {"result": "ok"}, "hevy": {"result": "failed"}, "yazio": {"result": "failed"}}})
    evil = info({"finished_at": "2026-11-24T06:41:00Z", "run_url": "https://example.com/x", "sources": {}})
    given(info=got, foreign_link=evil["runUrl"])
    assert got["failed"] == ["Hevy", "YAZIO"] and got["manual"] is True
    assert got["runUrl"] == "https://github.com/me/data/actions/runs/1" and evil["runUrl"] is None


def test_no_status_file_no_sync_time(given):
    """Without a readable sync_status.json the header keeps the page's load time."""
    given(status=None)
    assert info(None) is None and info({"finished_at": "garbage"}) is None
