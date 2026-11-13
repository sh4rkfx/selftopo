"""Sync status

data/sync_status.json: when the last sync ran, how it was started and how each source did, so the
dashboard can tell fresh data from a late or failed run.
"""

import argparse
import json
from datetime import UTC, datetime

from selftopo import __main__ as cli
from selftopo import config, syncstatus

STARTED = datetime(2026, 11, 13, 6, 31, 5, tzinfo=UTC)
FINISHED = datetime(2026, 11, 13, 6, 32, 40, tzinfo=UTC)
YESTERDAY = "2026-11-12T15:33:00Z"
GARMIN_OK = {"garmin": {"result": "ok", "at": YESTERDAY, "last_ok": YESTERDAY}}


def test_status_names_trigger_run_and_result_of_each_source(monkeypatch, given):
    """A scheduled run on GitHub records start, end, trigger, a link to the run and each source's result."""
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "me/data")
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    results = {"garmin": "ok", "hevy": "failed", "yazio": "skipped"}
    given(results=results, started=STARTED.isoformat(), finished=FINISHED.isoformat())
    status = syncstatus.build({}, STARTED, FINISHED, results)
    assert status["started_at"] == "2026-11-13T06:31:05Z"
    assert status["finished_at"] == "2026-11-13T06:32:40Z"
    assert status["trigger"] == "schedule"
    assert status["run_url"] == "https://github.com/me/data/actions/runs/42"
    end = "2026-11-13T06:32:40Z"
    assert status["sources"]["garmin"] == {"result": "ok", "at": end, "last_ok": end}
    assert status["sources"]["hevy"] == {"result": "failed", "at": "2026-11-13T06:32:40Z"}


def test_failed_source_keeps_its_last_success(monkeypatch, given):
    """A source that fails keeps the time of its last good run, so the dashboard can say how old its data is."""
    for name in ("GITHUB_EVENT_NAME", "GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"):
        monkeypatch.delenv(name, raising=False)  # as outside GitHub Actions
    previous = {"sources": GARMIN_OK}
    given(previous=previous, results={"garmin": "failed"})
    status = syncstatus.build(previous, STARTED, FINISHED, {"garmin": "failed"})
    assert status["sources"]["garmin"]["result"] == "failed"
    assert status["sources"]["garmin"]["last_ok"] == YESTERDAY
    assert status["trigger"] == "local"
    assert status["run_url"] is None


def test_single_source_run_keeps_the_other_sources(given):
    """`sync --source hevy` updates Hevy only; what the last full run said about Garmin stays."""
    previous = {"sources": GARMIN_OK}
    given(previous=previous, results={"hevy": "ok"})
    status = syncstatus.build(previous, STARTED, FINISHED, {"hevy": "ok"})
    assert sorted(status["sources"]) == ["garmin", "hevy"]
    assert status["sources"]["garmin"]["at"] == YESTERDAY


def test_sync_writes_the_file_even_when_a_source_fails(tmp_path, monkeypatch, given):
    """cmd_sync writes sync_status.json after the run, also when a source raised, and still returns 1."""
    path = tmp_path / "sync_status.json"
    monkeypatch.setattr(config, "SYNC_STATUS_JSON", path)

    def broken(days, refresh=False):
        raise RuntimeError("Garmin is down")

    monkeypatch.setattr(cli, "SOURCES", {"garmin": broken, "hevy": lambda days, refresh=False: None})
    given(sources={"garmin": "raises RuntimeError", "hevy": "returns"})
    code = cli.cmd_sync(argparse.Namespace(source="all", days=3, refresh=False))
    written = json.loads(path.read_text(encoding="utf-8"))
    assert code == 1
    assert written["sources"]["garmin"]["result"] == "failed"
    assert written["sources"]["hevy"]["result"] == "ok"


def test_unreadable_previous_file_is_replaced(tmp_path, monkeypatch, given):
    """A broken sync_status.json does not stop the sync; it is written anew."""
    path = tmp_path / "sync_status.json"
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(config, "SYNC_STATUS_JSON", path)
    given(file="{not json", results={"garmin": "ok"})
    syncstatus.write(STARTED, {"garmin": "ok"})
    assert json.loads(path.read_text(encoding="utf-8"))["sources"]["garmin"]["result"] == "ok"
