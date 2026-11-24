"""Tags and GitHub releases for every version in CHANGELOG.md.

Run by the workflow *Release* after the tests pass on main, and by hand for versions that have no
release yet. Each version section names its pull request ([#69](…)); its tag goes on the squash
commit of that pull request (subject ending in "(#69)"). The newest version is published as the
latest release and the major tag (v2) moves to it, so data repositories pick it up.

    python tools/release.py plan       # what would be tagged
    python tools/release.py publish    # tag, push, create releases (needs gh and GH_TOKEN)
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEADING = re.compile(r"^## (\d+)\.(\d+)\.(\d+) – (\d{4}-\d{2}-\d{2})$", re.M)
PR_LINK = re.compile(r"^\[#(\d+)\]\(https://github\.com/[\w.-]+/[\w.-]+/pull/\1\)$", re.M)


@dataclass
class Version:
    version: str
    date: str
    pr: int | None
    notes: str

    @property
    def tag(self) -> str:
        return f"v{self.version}"

    @property
    def key(self) -> tuple[int, ...]:
        return tuple(int(x) for x in self.version.split("."))


def versions(changelog: str) -> list[Version]:
    """Every version of the changelog, newest first, with its pull request and its notes."""
    marks = list(HEADING.finditer(changelog))
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(changelog)
        notes = changelog[m.end():end].strip()
        pr = PR_LINK.search(notes)
        out.append(Version(".".join(m.groups()[:3]), m.group(4), int(pr.group(1)) if pr else None, notes))
    return out


def commit_of(pr: int, log: str) -> str | None:
    """The squash commit of a pull request in `git log --format='%H %s'` output."""
    hits = re.findall(rf"^(\w+) .*\(#{pr}\)$", log, re.M)
    return hits[-1] if hits else None  # the oldest, if a later commit quotes the number


def plan(changelog: str, log: str, tags: set[str], since: tuple[int, ...] = (2, 1, 0)) -> list[tuple[Version, str]]:
    """(version, commit) for each version from `since` on that has no tag yet, oldest first."""
    todo = []
    for v in reversed(versions(changelog)):
        if v.key < since or v.tag in tags:
            continue
        sha = commit_of(v.pr, log) if v.pr else None
        if not sha:
            raise SystemExit(f"{v.version}: no commit for pull request #{v.pr}")
        todo.append((v, sha))
    return todo


def run(*cmd: str, input: str | None = None) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True, input=input, cwd=ROOT).stdout


def main(argv: list[str]) -> int:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    log = run("git", "log", "--format=%H %s")
    tags = set(run("git", "tag", "--list").split())
    todo = plan(changelog, log, tags)
    newest = versions(changelog)[0]
    for v, sha in todo:
        print(f"{v.tag} → {sha[:7]} (#{v.pr})")
    if argv[:1] != ["publish"]:
        return 0
    for v, sha in todo:
        run("git", "tag", "-a", v.tag, sha, "-m", v.version)
        run("git", "push", "origin", f"refs/tags/{v.tag}")
        latest = "true" if v.version == newest.version else "false"
        run("gh", "release", "create", v.tag, "--verify-tag", "--title", v.version, f"--latest={latest}",
            "--notes-file", "-", input=v.notes + "\n")
    # The major tag follows the newest release, so data repositories that check out v2 get it
    if newest.tag in set(run("git", "tag", "--list").split()):
        major = f"v{newest.version.split('.')[0]}"
        run("git", "tag", "-f", major, f"{newest.tag}^{{}}")
        run("git", "push", "-f", "origin", f"refs/tags/{major}")
        print(f"{major} → {newest.tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
