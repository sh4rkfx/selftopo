"""Test report for the page dashboard/tests.html.

Loaded from conftest.py. For every test it records what the page shows: the docstring (what the
test checks), the inputs passed to the `given` fixture, every executed check with its expected and
actual value, the outcome and the duration. With the ini option `report_json` (set in
pyproject.toml) or `--report-json PATH` it writes them to a JSON file; `--report-json ""` turns
that off.

How the checks are captured:
- Passing asserts: pytest's assertion pass hook (`enable_assertion_pass_hook = true`) hands over
  the source of each assert. Comparisons also pass through `pytest_assertrepr_compare`, which
  receives both sides as objects, so the report has the expected and the actual value.
- The failing assert: the same compare hook, then the error message.
- `with pytest.raises(...)`: wrapped while a test runs, so the expected and the raised exception
  are recorded as a check as well.

Traffic light, also printed in the terminal summary:
- per test: green passed, red failed, yellow skipped or not executable (error in setup,
  teardown or while loading the file);
- overall: red if a test marked `critical` failed, or if failed and not executable tests make up
  RED_SHARE or more of all tests; yellow if anything else did not pass; green if all passed.

`python tests/report_plugin.py publish NEW_RESULTS BRANCH_DIR` merges a results file into a
checkout of the `test-results` branch (results.json and history.json). The Tests workflow calls it.
"""

from __future__ import annotations

import ast
import datetime as dt
import inspect
import json
import linecache
import os
import platform
import pprint
import re
import subprocess
import sys
import time
from collections import Counter
from functools import cache
from pathlib import Path

import pytest

SCHEMA = 1
RED_SHARE = 0.10  # failed plus not executable tests from this share of all tests on: red
HISTORY_RUNS = 30  # runs kept in history.json
MAX_REPR = 1500  # characters per value
MAX_CHECKS = 80  # recorded checks per test, for asserts in loops
MAX_TRACE = 8000  # characters of the failure report
ROOT = Path(__file__).resolve().parent.parent

LIGHT = {"passed": "green", "failed": "red", "skipped": "yellow", "xfailed": "yellow", "xpassed": "yellow",
         "error": "yellow", "not_run": "yellow"}
NOT_EXECUTABLE = {"error", "not_run"}
SKIPPED = {"skipped", "xfailed", "xpassed"}

_report: Report | None = None
_running: dict | None = None  # record of the test whose call phase is running
_compares: list[tuple[str, str, str]] = []  # comparisons since the last recorded check
_original_raises = pytest.raises
_ADDRESS = re.compile(r" at 0x[0-9a-f]+")


# --------------------------------------------------------------------------- values


def fmt(value) -> str:
    """Readable, bounded text for a value: pretty-printed, numpy scalars as plain numbers."""
    try:
        if type(value).__module__ == "numpy" and getattr(value, "shape", None) == ():
            value = value.item()
        text = pprint.pformat(value, width=96, compact=True, sort_dicts=False)
    except Exception as exc:  # a broken __repr__ must not break the report
        text = f"<value could not be shown: {type(exc).__name__}>"
    return _clip(_ADDRESS.sub("", text), MAX_REPR)


def _clip(text: str, limit: int, keep_end: bool = False) -> str:
    if len(text) <= limit:
        return text
    cut = len(text) - limit
    return f"… (−{cut})\n" + text[-limit:] if keep_end else text[:limit] + f" … (+{cut})"


def _exception_text(exc: BaseException | None) -> str:
    if exc is None:
        return ""
    message = str(exc).strip()
    return _clip(f"{type(exc).__name__}: {message}" if message else type(exc).__name__, MAX_REPR)


# --------------------------------------------------------------------------- source


@cache
def _module(path: str) -> tuple[str, ast.Module] | None:
    try:
        source = Path(path).read_text(encoding="utf-8")
        return source, ast.parse(source)
    except (OSError, SyntaxError, ValueError):
        return None


@cache
def _asserts(path: str) -> dict[int, ast.Assert]:
    parsed = _module(path)
    return {n.lineno: n for n in ast.walk(parsed[1]) if isinstance(n, ast.Assert)} if parsed else {}


def _segment(path: str, node: ast.AST) -> str:
    parsed = _module(path)
    text = ast.get_source_segment(parsed[0], node) if parsed else None
    return text or ""


def _is_raises(call: ast.AST) -> bool:
    if not isinstance(call, ast.Call):
        return False
    func = call.func
    return (isinstance(func, ast.Attribute) and func.attr == "raises") or (
        isinstance(func, ast.Name) and func.id == "raises")


def _planned_checks(func) -> list[dict]:
    """Asserts and pytest.raises blocks in the test function's source, in source order."""
    code = getattr(func, "__code__", None)
    parsed = _module(code.co_filename) if code else None
    if not parsed:
        return []
    for node in ast.walk(parsed[1]):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and code.co_firstlineno in (
                node.lineno, *(d.lineno for d in node.decorator_list[:1])):
            planned = []
            for inner in ast.walk(node):
                if isinstance(inner, ast.Assert):
                    planned.append({"line": inner.lineno, "expr": _segment(code.co_filename, inner.test)})
                elif isinstance(inner, (ast.With, ast.AsyncWith)):
                    planned += [{"line": w.context_expr.lineno, "expr": _segment(code.co_filename, w.context_expr)}
                                for w in inner.items if _is_raises(w.context_expr)]
            return sorted(planned, key=lambda c: c["line"])
    return []


def _doc(obj) -> str:
    return inspect.cleandoc(obj.__doc__) if getattr(obj, "__doc__", None) else ""


def _title(name: str) -> str:
    base = name.split("[", 1)[0].removeprefix("test_").replace("_", " ").strip()
    params = name[len(name.split("[", 1)[0]):]
    return (base[:1].upper() + base[1:] + (f" {params}" if params else "")) or name


# --------------------------------------------------------------------------- run metadata


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=5, check=True)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _repository() -> str | None:
    if os.environ.get("GITHUB_REPOSITORY"):
        return os.environ["GITHUB_REPOSITORY"]
    url = _git("remote", "get-url", "origin") or ""
    match = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", url)
    return match.group(1) if match else None


def run_info() -> dict:
    env = os.environ
    commit = env.get("GITHUB_SHA") or _git("rev-parse", "HEAD")
    repository = _repository()
    run_id = env.get("GITHUB_RUN_ID")
    server = env.get("GITHUB_SERVER_URL", "https://github.com")
    return {
        "repository": repository,
        "commit": commit,
        "subject": _git("log", "-1", "--format=%s", commit) if commit else None,
        "branch": env.get("GITHUB_REF_NAME") or _git("rev-parse", "--abbrev-ref", "HEAD"),
        "event": env.get("GITHUB_EVENT_NAME") or "local",
        "run_url": f"{server}/{repository}/actions/runs/{run_id}" if run_id and repository else None,
        "local_changes": None if env.get("CI") else bool(_git("status", "--porcelain", "--untracked-files=no")),
        "python": platform.python_version(),
        "pytest": pytest.__version__,
        "platform": platform.system(),
    }


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- summary


def summarize(tests: list[dict]) -> dict:
    """Counts and the overall traffic light with the rule that decided it."""
    outcomes = Counter(t["outcome"] for t in tests)
    total = len(tests)
    failed = outcomes["failed"]
    not_executable = sum(outcomes[o] for o in NOT_EXECUTABLE)
    skipped = sum(outcomes[o] for o in SKIPPED)
    critical_failed = sum(1 for t in tests if t["outcome"] == "failed" and t.get("critical"))
    share = (failed + not_executable) / total if total else 1.0
    if not total:
        light, reason = "red", "no_tests"
    elif critical_failed:
        light, reason = "red", "critical_failed"
    elif share >= RED_SHARE:
        light, reason = "red", "share"
    elif failed:
        light, reason = "yellow", "failed"
    elif not_executable:
        light, reason = "yellow", "not_executable"
    elif skipped:
        light, reason = "yellow", "skipped"
    else:
        light, reason = "green", "all_passed"
    return {
        "total": total, "passed": outcomes["passed"], "failed": failed, "critical_failed": critical_failed,
        "not_executable": not_executable, "skipped": skipped, "share_bad": round(share, 4),
        "light": light, "reason": reason, "red_share": RED_SHARE,
        "duration_s": round(sum(t.get("duration_s") or 0 for t in tests), 4),
    }


# --------------------------------------------------------------------------- recording


class Report:
    def __init__(self, config: pytest.Config):
        option = config.getoption("report_json")
        self.path = Path(option if option is not None else config.getini("report_json") or "")
        self.enabled = str(self.path) not in ("", ".")
        if self.enabled and not self.path.is_absolute():
            self.path = config.rootpath / self.path
        self.tests: dict[str, dict] = {}
        self.groups: dict[str, dict] = {}
        self.started = time.time()
        self.started_iso = _now()

    def add_item(self, item: pytest.Item) -> None:
        file, line, _ = item.location
        func = getattr(item, "obj", None)
        module = getattr(item, "module", None)
        if file not in self.groups:
            doc = _doc(module) if module else ""
            title, _, rest = doc.partition("\n")
            self.groups[file] = {"title": title.strip().rstrip("."), "description": rest.strip()}
        params = getattr(getattr(item, "callspec", None), "params", {}) or {}
        self.tests[item.nodeid] = {
            "id": item.nodeid, "name": item.name, "title": _title(item.name), "file": file,
            "line": (line or 0) + 1, "critical": item.get_closest_marker("critical") is not None,
            "doc": _doc(func), "inputs": [{"name": k, "value": fmt(v)} for k, v in params.items()],
            "checks": [], "planned": _planned_checks(func), "outcome": "not_run", "phase": None,
            "message": None, "trace": None, "durations": {}, "duration_s": 0.0,
        }

    def add_collect_error(self, report: pytest.CollectReport) -> None:
        file = report.nodeid or "?"
        text = report.longreprtext or ""
        lines = text.strip().splitlines()
        self.groups.setdefault(file, {"title": file, "description": ""})
        self.tests[file] = {
            "id": file, "name": file, "title": "File could not be loaded", "file": file, "line": 1,
            "critical": False, "doc": "", "inputs": [], "checks": [], "planned": [], "outcome": "error",
            "phase": "collect", "reason_code": "collect_error",
            "message": _clip(lines[-1].removeprefix("E").strip() if lines else "", 600),
            "trace": _clip(text, MAX_TRACE, keep_end=True), "durations": {}, "duration_s": 0.0,
        }

    def as_dict(self) -> dict:
        tests = list(self.tests.values())
        return {
            "schema": SCHEMA, "run": {**run_info(), "started": self.started_iso, "finished": _now(),
                                      "wall_s": round(time.time() - self.started, 3)},
            "summary": summarize(tests), "groups": self.groups, "tests": tests,
        }


def _add_check(record: dict | None, check: dict) -> None:
    if record is not None and len(record["checks"]) < MAX_CHECKS:
        record["checks"].append(check)


def _compare_check(op: str, left: str, right: str, line: int, expr: str, ok: bool) -> dict:
    return {"line": line, "expr": expr, "ok": ok, "op": op, "left": left, "right": right}


def _checks_from_assert(path: str, lineno: int, orig: str, expl: str, compares: list, ok: bool) -> list[dict]:
    node = _asserts(path).get(lineno)
    test = node.test if node else None
    orig = _segment(path, test) if test is not None else orig  # without trailing comments
    first, _, rest = (expl or "").partition("\n")
    where = [line.strip(" +") for line in rest.splitlines() if line.lstrip(" +").startswith("where ")]
    detail = _clip(_ADDRESS.sub("", "\n".join(where)), 600) or None
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And) and compares and all(
            isinstance(v, ast.Compare) for v in test.values[:len(compares)]):
        return [_compare_check(op, left, right, lineno, _segment(path, value), ok or i < len(compares) - 1)
                for i, ((op, left, right), value) in enumerate(zip(compares, test.values, strict=False))]
    if compares and (isinstance(test, ast.Compare) or (test is None and len(compares) == 1)):
        op, left, right = compares[-1]
        return [{**_compare_check(op, left, right, lineno, orig, ok), "detail": detail}]
    negated = isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not)
    value = first.strip()
    value = value[4:] if negated and value.startswith("not ") else value
    return [{"line": lineno, "expr": orig, "ok": ok, "op": "falsy" if negated else "truthy",
             "left": _clip(_ADDRESS.sub("", value), MAX_REPR) if value else None, "right": None, "detail": detail}]


class _RecordedRaises:
    """pytest.raises(...) as a context manager that records itself as a check."""

    def __init__(self, ctx, expected, match, record: dict | None, line: int, expr: str):
        self._ctx, self._record, self._line, self._expr = ctx, record, line, expr
        names = expected if isinstance(expected, tuple) else (expected,)
        self._expected = " | ".join(getattr(e, "__name__", str(e)) for e in names) + (
            f", match {match!r}" if match is not None else "")

    def __enter__(self):
        return self._ctx.__enter__()

    def __exit__(self, exc_type, exc, tb):
        check = {"line": self._line, "expr": self._expr, "op": "raises", "right": self._expected,
                 "left": _exception_text(exc) if exc_type else None}
        try:
            suppressed = self._ctx.__exit__(exc_type, exc, tb)
        except BaseException as err:
            _add_check(self._record, {**check, "ok": False, "detail": _clip(str(err), 600)})
            raise
        _add_check(self._record, {**check, "ok": bool(suppressed)})
        return suppressed


def _recording_raises(expected_exception, *args, **kwargs):
    if args or kwargs.keys() - {"match"}:
        return _original_raises(expected_exception, *args, **kwargs)
    frame = sys._getframe(1)
    line, path = frame.f_lineno, frame.f_code.co_filename
    planned = next((p["expr"] for p in (_running or {}).get("planned", []) if p["line"] == line), None)
    if planned is None:
        planned = linecache.getline(path, line).strip().removeprefix("with ").rstrip(":")
    ctx = _original_raises(expected_exception, **kwargs)
    return _RecordedRaises(ctx, expected_exception, kwargs.get("match"), _running, line, planned)


# --------------------------------------------------------------------------- pytest hooks


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addini("report_json", "write the report for dashboard/tests.html to this file", default="")
    parser.addoption("--report-json", default=None, metavar="PATH",
                     help="write the report for dashboard/tests.html to PATH ('' for none)")


def pytest_configure(config: pytest.Config) -> None:
    global _report
    config.addinivalue_line(
        "markers", "critical: a failure can store wrong values, lose stored data, or break or expose a login")
    if not hasattr(config, "workerinput"):  # not inside a pytest-xdist worker
        _report = Report(config)


def pytest_collection_finish(session: pytest.Session) -> None:
    if _report:
        for item in session.items:
            _report.add_item(item)


def pytest_collectreport(report: pytest.CollectReport) -> None:
    if _report and report.failed:
        _report.add_collect_error(report)


@pytest.fixture
def given(request: pytest.FixtureRequest):
    """Record the inputs of a test for the report: given(payload=payload, days=30)."""
    record = _report.tests.get(request.node.nodeid) if _report else None

    def record_inputs(**inputs) -> None:
        if record is not None:
            record["inputs"] += [{"name": name, "value": fmt(value)} for name, value in inputs.items()]

    return record_inputs


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item: pytest.Item):
    global _running
    _running = _report.tests.get(item.nodeid) if _report else None
    _compares.clear()
    pytest.raises = _recording_raises
    try:
        return (yield)
    finally:
        pytest.raises = _original_raises
        _running = None


def pytest_assertrepr_compare(config: pytest.Config, op: str, left, right) -> None:
    if _running is not None:
        _compares.append((op, fmt(left), fmt(right)))


def pytest_assertion_pass(item: pytest.Item, lineno: int, orig: str, expl: str) -> None:
    record = _report.tests.get(item.nodeid) if _report else None
    if record is not None:
        for check in _checks_from_assert(str(item.path), lineno, orig, expl, list(_compares), True):
            _add_check(record, check)
    _compares.clear()


def _failure_location(item: pytest.Item, excinfo: pytest.ExceptionInfo) -> int | None:
    for entry in reversed(excinfo.traceback):
        if Path(str(entry.path)) == Path(item.path):
            return entry.lineno + 1
    return None


def _record_failure(record: dict, item: pytest.Item, call: pytest.CallInfo) -> None:
    excinfo = call.excinfo
    line = _failure_location(item, excinfo)
    path = str(item.path)
    if excinfo.errisinstance(AssertionError) and line in _asserts(path):
        node = _asserts(path)[line]
        expl = ""
        for text_line in str(excinfo.value).splitlines():
            if text_line.startswith("assert "):
                expl = text_line[len("assert "):]
                break
        checks = _checks_from_assert(path, line, _segment(path, node.test), expl, list(_compares), False)
        message = str(excinfo.value).split("\nassert ", 1)[0] if "\nassert " in str(excinfo.value) else None
        for check in checks[:-1]:
            check["ok"] = True
        if message:
            checks[-1]["detail"] = _clip(message, 600)
        for check in checks:
            _add_check(record, check)
    elif not record["checks"] or record["checks"][-1]["ok"]:
        expr = linecache.getline(path, line).strip().removeprefix("assert ") if line else ""
        _add_check(record, {"line": line, "expr": expr, "ok": False, "op": "error",
                            "left": _exception_text(excinfo.value), "right": None})
    _compares.clear()


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    report = yield
    record = _report.tests.get(item.nodeid) if _report else None
    if record is None:
        return report
    record["durations"][report.when] = round(report.duration, 6)
    record["duration_s"] = round(sum(record["durations"].values()), 6)
    xfail = getattr(report, "wasxfail", None)
    if report.when == "call" and report.failed and call.excinfo is not None:
        _record_failure(record, item, call)
    if report.skipped:
        reason = report.longrepr[2] if isinstance(report.longrepr, tuple) else str(report.longrepr or "")
        record.update(outcome="xfailed" if xfail is not None else "skipped", phase=report.when,
                      message=_clip(xfail or reason.removeprefix("Skipped: "), 600))
    elif report.failed and not (report.when == "teardown" and record["outcome"] in ("failed", "error")):
        crash = getattr(report.longrepr, "reprcrash", None)
        outcome = "failed" if report.when == "call" else "error"
        record.update(outcome=outcome, phase=report.when,
                      message=_clip(crash.message if crash else str(report.longrepr).splitlines()[-1], 600),
                      trace=_clip(report.longreprtext, MAX_TRACE, keep_end=True))
        if outcome == "error":
            record["reason_code"] = f"{report.when}_error"
    elif report.when == "call" and report.passed:
        record.update(outcome="xpassed" if xfail is not None else "passed", phase="call",
                      message=_clip(xfail, 600) if xfail else None)
    return report


def pytest_sessionfinish(session: pytest.Session) -> None:
    if _report and _report.enabled:
        _report.path.parent.mkdir(parents=True, exist_ok=True)
        _report.path.write_text(json.dumps(_report.as_dict(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def pytest_terminal_summary(terminalreporter) -> None:
    if not _report or not _report.tests:
        return
    summary = summarize(list(_report.tests.values()))
    markup = {"green": {"green": True}, "yellow": {"yellow": True}, "red": {"red": True, "bold": True}}
    where = f" -> {os.path.relpath(_report.path)}" if _report.enabled else ""
    terminalreporter.write_line(
        f"Test report: {summary['light'].upper()} ({summary['reason']}), "
        f"{summary['passed']} of {summary['total']} passed{where}", **markup[summary["light"]])


# --------------------------------------------------------------------------- publishing (CI)


def _load(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _not_run(test: dict, reason_code: str, message: str) -> dict:
    keep = {k: test.get(k) for k in ("id", "name", "title", "file", "line", "critical", "doc", "planned")}
    return {**keep, "inputs": [], "checks": [], "outcome": "not_run", "phase": None, "reason_code": reason_code,
            "message": message, "trace": None, "durations": {}, "duration_s": 0.0}


def publish(new_path: Path, into: Path) -> dict:
    """Merge a run into the branch folder: results.json is the run, history.json the last runs.

    Tests of a file that could not be loaded, or of a run without results, are taken from the
    previous run and marked as not run, so they stay visible (yellow) instead of disappearing.
    """
    previous = _load(into / "results.json")
    history = _load(into / "history.json") or {"schema": SCHEMA, "runs": []}
    new = _load(new_path)
    if new is None:
        new = {"schema": SCHEMA, "run": {**run_info(), "finished": _now()}, "groups": {}, "tests": [],
               "problem": "no_results"}
    tests = new["tests"]
    if previous:
        known = {t["id"] for t in tests}
        broken = {t["file"] for t in tests if t.get("phase") == "collect"}
        carried = []
        for test in previous.get("tests", []):
            if test["id"] in known or test.get("phase") == "collect":
                continue
            if new.get("problem") == "no_results":
                carried.append(_not_run(test, "no_results", "The test job produced no results."))
            elif test["file"] in broken:
                carried.append(_not_run(test, "collect_error", "The file of this test could not be loaded."))
        if carried:
            files = {t["file"] for t in carried}
            tests[:] = [t for t in tests if not (t.get("phase") == "collect" and t["file"] in files)] + carried
            for file in files:
                new["groups"].setdefault(file, previous.get("groups", {}).get(file, {"title": file}))
    new["summary"] = summarize(tests)
    run = new["run"]
    history["runs"].append({
        "commit": run.get("commit"), "subject": run.get("subject"), "finished": run.get("finished"),
        "run_url": run.get("run_url"), "summary": new["summary"],
        "tests": {t["id"]: [t["outcome"], t.get("duration_s") or 0] for t in tests},
    })
    history["runs"] = history["runs"][-HISTORY_RUNS:]
    into.mkdir(parents=True, exist_ok=True)
    (into / "results.json").write_text(json.dumps(new, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (into / "history.json").write_text(json.dumps(history, ensure_ascii=False, separators=(",", ":")) + "\n",
                                       encoding="utf-8")
    return new["summary"]


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] != "publish":
        sys.exit("usage: python tests/report_plugin.py publish NEW_RESULTS BRANCH_DIR")
    result = publish(Path(sys.argv[2]), Path(sys.argv[3]))
    print(f"published: {result['light']} ({result['reason']}), {result['passed']} of {result['total']} passed")
