"""One version per change

Every change gets a semantic version: the newest entry in CHANGELOG.md, selftopo.__version__ and
APP_VERSION in the dashboard are the same number, versions only go up, and each one says what
changed.
"""

import re
from pathlib import Path

from jsdashboard import HTML

import selftopo

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
HEADINGS = re.findall(r"^## (\d+)\.(\d+)\.(\d+) – (\d{4}-\d{2}-\d{2})$", CHANGELOG, re.M)


def test_code_dashboard_and_changelog_name_the_same_version(given):
    """selftopo.__version__ = APP_VERSION = the first version in the changelog; no Unreleased section."""
    app = re.search(r'const APP_VERSION = "([^"]+)";', HTML).group(1)
    newest = ".".join(HEADINGS[0][:3])
    given(python=selftopo.__version__, dashboard=app, changelog=newest)
    assert selftopo.__version__ == app == newest
    assert "## Unreleased" not in CHANGELOG


def test_versions_only_go_up_and_dates_never_go_back(given):
    """Read from the top, each version is lower than the one above and not newer by date."""
    versions = [tuple(int(x) for x in h[:3]) for h in HEADINGS]
    dates = [h[3] for h in HEADINGS]
    given(versions=[".".join(map(str, v)) for v in versions[:6]], count=len(versions))
    assert versions == sorted(versions, reverse=True) and len(set(versions)) == len(versions)
    assert dates == sorted(dates, reverse=True)


def test_every_version_says_what_changed(given):
    """Each version heading is followed by at least one bullet before the next version."""
    sections = re.split(r"^## \d+\.\d+\.\d+ – .*$", CHANGELOG, flags=re.M)[1:]
    empty = [".".join(HEADINGS[i][:3]) for i, s in enumerate(sections) if not re.search(r"^- ", s, re.M)]
    given(empty=empty)
    assert empty == []


def test_cli_prints_the_version(given, capsys):
    """`python -m selftopo --version` prints selftopo and the version."""
    from selftopo.__main__ import build_parser
    try:
        build_parser().parse_args(["--version"])
    except SystemExit:
        pass
    out = capsys.readouterr().out.strip()
    given(out=out)
    assert out == f"selftopo {selftopo.__version__}"
