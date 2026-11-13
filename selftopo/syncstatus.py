"""When the data was last fetched, so the dashboard can tell fresh data from a late or failed sync.

`sync` writes data/sync_status.json after every run. The dashboard shows the time of the last run
instead of only the time the page loaded, and warns when it is old or a source failed. Scheduled
GitHub Actions runs often start hours late, so the file is the only reliable answer to "is this
the newest data?".
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

from . import config

log = logging.getLogger(__name__)

SCHEMA = 1


def now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def _trigger() -> str:
    """schedule, workflow_dispatch or another GitHub event; local outside GitHub Actions."""
    return os.environ.get("GITHUB_EVENT_NAME") or "local"


def _run_url() -> str | None:
    server, repo, run = (os.environ.get(k) for k in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"))
    return f"{server}/{repo}/actions/runs/{run}" if server and repo and run else None


def _read() -> dict[str, Any]:
    try:
        data = json.loads(config.SYNC_STATUS_JSON.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def build(previous: dict[str, Any], started: datetime, finished: datetime, results: dict[str, str]) -> dict[str, Any]:
    """The new file content. Sources of this run get their result; the others keep the last one,
    so a run of a single source does not erase what the full runs reported."""
    sources = {name: entry for name, entry in (previous.get("sources") or {}).items() if isinstance(entry, dict)}
    for name, result in results.items():
        entry = dict(sources.get(name) or {})
        entry["result"] = result
        entry["at"] = _iso(finished)
        if result == "ok":
            entry["last_ok"] = _iso(finished)
        sources[name] = entry
    return {
        "schema": SCHEMA,
        "started_at": _iso(started),
        "finished_at": _iso(finished),
        "trigger": _trigger(),
        "run_url": _run_url(),
        "sources": dict(sorted(sources.items())),
    }


def write(started: datetime, results: dict[str, str]) -> None:
    """Never fails the sync: the data matters more than the note about it."""
    try:
        content = build(_read(), started, now(), results)
        config.SYNC_STATUS_JSON.parent.mkdir(parents=True, exist_ok=True)
        config.SYNC_STATUS_JSON.write_text(json.dumps(content, indent=2) + "\n", encoding="utf-8")
    except OSError:
        log.exception("could not write %s", config.SYNC_STATUS_JSON)
