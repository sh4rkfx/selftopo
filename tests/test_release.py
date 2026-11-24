"""Releases from the changelog

tools/release.py tags every version of CHANGELOG.md on the squash commit of its pull request and
publishes it as a GitHub release; the workflow Release runs it after the tests pass on main.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release", ROOT / "tools" / "release.py")
release = importlib.util.module_from_spec(spec)
sys.modules["release"] = release  # dataclasses look the module up by name
spec.loader.exec_module(release)

CHANGELOG = """# Changelog

## 2.2.0 – 2026-11-24

[#71](https://github.com/me/app/pull/71)

### Dashboard

- New thing.

## 2.1.0 – 2026-11-10

[#69](https://github.com/me/app/pull/69)

- First thing.

## 2.0.0 – 2026-11-01

- Before per-change versions.
"""
LOG = "c3 Mention of (#69) in a later fix (#72)\nc2 New thing (#71)\nc1 First thing (#69)\nc0 Release 2.0.0 (#68)\n"


def test_versions_are_read_with_pull_request_and_notes(given):
    """Newest first; each with its pull request (none before per-change versions) and its notes."""
    got = [(v.version, v.date, v.pr, v.notes.splitlines()[-1]) for v in release.versions(CHANGELOG)]
    given(versions=got)
    assert got == [("2.2.0", "2026-11-24", 71, "- New thing."), ("2.1.0", "2026-11-10", 69, "- First thing."),
                   ("2.0.0", "2026-11-01", None, "- Before per-change versions.")]


def test_tag_goes_on_the_squash_commit_of_the_pull_request(given):
    """'(#69)' at the end of the subject; a later commit that quotes the number in its title does not count."""
    given(log=LOG)
    assert release.commit_of(69, LOG) == "c1" and release.commit_of(71, LOG) == "c2"
    assert release.commit_of(99, LOG) is None


def test_only_untagged_versions_are_published_oldest_first(given):
    """v2.1.0 exists: only 2.2.0 is new; with no tags both, oldest first; 2.0.0 and older never."""
    some = [(v.version, sha) for v, sha in release.plan(CHANGELOG, LOG, {"v2.1.0", "v2.0.0"})]
    none = [(v.version, sha) for v, sha in release.plan(CHANGELOG, LOG, set())]
    given(some=some, none=none)
    assert some == [("2.2.0", "c2")] and none == [("2.1.0", "c1"), ("2.2.0", "c2")]


def test_a_tag_without_its_release_is_completed(given):
    """A run that pushed v2.2.0 but failed to create its release: the next run creates the release."""
    todo = [(v.version, sha) for v, sha in release.plan(CHANGELOG, LOG, {"v2.1.0", "v2.2.0"}, {"v2.1.0"})]
    given(todo=todo)
    assert todo == [("2.2.0", "c2")]


def test_a_version_without_its_commit_stops(given):
    """A pull request number with no merged commit is an error, not a tag on the wrong commit."""
    given(log="c0 Something else (#5)")
    with pytest.raises(SystemExit, match="no commit for pull request #69"):
        release.plan(CHANGELOG, "c0 Something else (#5)\n", set())


def test_workflow_runs_after_green_tests_on_main_and_by_hand(given):
    """Triggered by the Tests workflow on main (only when it passed on a push) or by hand; writes tags."""
    text = (ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
    given(workflow="publish.yml")
    assert "workflows: [Tests]" in text and "branches: [main]" in text and "workflow_dispatch:" in text
    assert "ref: ${{ github.event.workflow_run.head_sha || 'main' }}" in text  # the commit that passed
    assert "github.event.workflow_run.conclusion == 'success'" in text and "contents: write" in text
    assert "python tools/release.py publish" in text
