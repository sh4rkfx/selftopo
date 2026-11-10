"""Run single functions of the dashboard script in Node, for tests of its pure helpers.

The dashboard is one HTML file without a build step, so the tests cut the declarations they need
out of the script (`function name(...) {...}` or `const name = ...;`), put them after a few stubs
and call them in Node. Only for helpers that touch neither the DOM nor the data files.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

HTML = (Path(__file__).resolve().parent.parent / "dashboard" / "index.html").read_text(encoding="utf-8")
SCRIPT = HTML[HTML.rindex("<script>"):]

# The German defaults the helpers rely on, without the browser: dates in UTC, German locale
STUBS = """
const LANG = "de", LOCALE = "de-DE", DATE_LOCALE = "de-AT";
const T = (text, vars) => (vars ? text.replace(/\\{(\\w+)\\}/g, (m, k) => (k in vars ? String(vars[k]) : m)) : text);
"""


def declaration(name: str) -> str:
    """The source of the top-level declaration `name` in the dashboard script."""
    match = re.search(rf"\n  (?:function {re.escape(name)}\(|const {re.escape(name)} = )", SCRIPT)
    assert match, f"{name} not found in dashboard/index.html"
    start = match.start() + 1
    depth, i, quote = 0, start, None
    is_function = SCRIPT.startswith("function", start + 2)
    while i < len(SCRIPT):
        c = SCRIPT[i]
        if quote:
            if c == "\\":
                i += 1
            elif c == quote:
                quote = None
        elif c in "\"'`":
            quote = c
        elif SCRIPT.startswith("//", i):
            i = SCRIPT.index("\n", i) - 1
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if is_function and depth == 0 and c == "}":
                return SCRIPT[start:i + 1]
        elif c == ";" and depth == 0 and not is_function:
            return SCRIPT[start:i + 1]
        i += 1
    raise AssertionError(f"end of {name} not found")


def run(names: list[str], expression: str):
    """Evaluate `expression` after the declarations `names`; returns its JSON value."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not installed")
    source = STUBS + "\n".join(declaration(n) for n in names) + f"\nprocess.stdout.write(JSON.stringify({expression}));"
    out = subprocess.run([node, "-e", source], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout)
