"""Values from report files in files/, read by the Claude API, as proposals to confirm.

The dashboard uploads reports (PDF, JPG, PNG) to files/ in the data repository and reads PDFs with a
text layer itself. Everything else, photos and scans above all, is evaluated here: each file that no
row of measurements.csv points to and that was not evaluated before goes to the Anthropic Messages
API once. The values it finds are written as rows with status `proposed`; they count only after
they are confirmed in the dashboard. report_evaluations.json records which file was evaluated when
and with what result, so no file is sent twice.

Needs the secret ANTHROPIC_API_KEY. The report leaves the repository for this: it is sent to the
Anthropic API.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import secrets
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import requests

from . import config
from .csvstore import read_rows, write_rows

log = logging.getLogger(__name__)

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-5-5"
MAX_FILES_PER_RUN = 5
MAX_BYTES = 5 * 1024 * 1024
MEDIA_TYPES = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}

FIELDS = ["id", "date", "kind", "name", "value", "unit", "ref_low", "ref_high", "source", "note", "file", "status"]
# Same kinds, units and plausible ranges as MEASURE_KINDS in the dashboard
KINDS: dict[str, tuple[str, float | None, float | None]] = {
    "waist_cm": ("cm", 50, 160),
    "dexa_fat_pct": ("%", 3, 60),
    "dexa_ffm_kg": ("kg", 30, 120),
    "rmr_kcal": ("kcal/d", 800, 4000),
    "rer": ("", 0.65, 1.1),
    "vo2max_lab": ("ml/kg/min", 15, 90),
    "blood": ("", None, None),
}

PROMPT = """This is a medical or performance-test report of one person. Record every value of these kinds:
- rmr_kcal: resting metabolic rate MEASURED by indirect calorimetry, in kcal per day
  (not a formula such as Harris-Benedict)
- rer: respiratory exchange ratio (RER, RQ) of that resting measurement
- vo2max_lab: VO2max or VO2peak relative to body weight in ml/kg/min (not absolute ml/min)
- dexa_fat_pct: total body fat percentage, only from a DEXA/DXA scan
- dexa_ffm_kg: lean or fat-free mass in kg, only from a DEXA/DXA scan
- waist_cm: waist circumference in cm
- blood: any blood or lab value, with its name, unit and the reference range exactly as printed
Use the date the sample was taken or the test was done. Copy numbers exactly; leave out what you cannot read with
certainty. If the file is not such a report, record no values.
Always answer by calling the tool record_values exactly once, also when there are no values."""

# Strict tool use: the input always matches the schema, so every object closes with
# additionalProperties false and lists all its fields as required (null where there is none).
# Forced tool use (tool_choice "tool" or "any") is rejected by newer models such as Claude Sonnet
# 5.5, so the call uses "auto" and the prompt asks for the tool.
TOOL = {
    "name": "record_values",
    "description": "Record the values found in the report.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "date": {"type": ["string", "null"], "description": "Date of the measurement, YYYY-MM-DD"},
            "values": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": list(KINDS)},
                        "name": {"type": ["string", "null"], "description": "Name as printed; for blood values only"},
                        "value": {"type": "number"},
                        "unit": {"type": ["string", "null"]},
                        "ref_low": {"type": ["number", "null"]},
                        "ref_high": {"type": ["number", "null"]},
                    },
                    "required": ["kind", "name", "value", "unit", "ref_low", "ref_high"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["date", "values"],
        "additionalProperties": False,
    },
}


def evaluations_path() -> Path:
    return config.DATA_DIR / "report_evaluations.json"


def pending_files(data_dir: Path, rows: list[dict[str, str]], evaluated: dict[str, Any]) -> list[str]:
    """Report files under files/ that no row points to and that were not evaluated yet, oldest name first."""
    folder = data_dir / "files"
    if not folder.is_dir():
        return []
    referenced = {r.get("file", "") for r in rows}
    found = []
    for path in sorted(folder.rglob("*")):
        rel = path.relative_to(data_dir).as_posix()
        # Never a symlink: it could point at a file that is not a report
        if path.is_symlink() or not path.resolve().is_relative_to(folder.resolve()):
            continue
        if path.is_file() and path.suffix.lower() in MEDIA_TYPES and rel not in referenced and rel not in evaluated:
            found.append(rel)
    return found


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None  # NaN


def _fmt(number: float) -> str:
    return str(int(number)) if number == int(number) else repr(round(number, 4))


def _day(text: Any, today: date) -> date | None:
    try:
        when = date.fromisoformat(str(text)[:10])
    except ValueError:
        return None
    return when if when <= today else None


def to_rows(result: dict[str, Any], file: str, today: date) -> list[dict[str, str]]:
    """Proposed rows from the tool input; values outside the plausible range are dropped.

    The date is the one Claude read; without a readable one, the date the dashboard put at the
    start of the file name on upload (files/2026-11-23-befund.jpg). Without either, nothing.
    """
    when = _day(result.get("date"), today) or _day(Path(file).name, today)
    if when is None:
        return []
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in result.get("values") or []:
        kind = item.get("kind")
        value = _number(item.get("value"))
        if kind not in KINDS or value is None:
            continue
        unit, low, high = KINDS[kind]
        name = str(item.get("name") or "").strip() if kind == "blood" else ""
        if kind == "blood" and not name:
            continue
        if low is not None and not (low <= value <= high):
            continue
        key = (kind, name.lower())
        if key in seen:
            continue
        seen.add(key)
        ref_low, ref_high = _number(item.get("ref_low")), _number(item.get("ref_high"))
        rows.append({
            "id": f"{when.isoformat()}-{kind}-{secrets.token_hex(2)}",
            "date": when.isoformat(),
            "kind": kind,
            "name": name,
            "value": _fmt(value),
            "unit": str(item.get("unit") or "").strip() if kind == "blood" else unit,
            "ref_low": "" if ref_low is None or kind != "blood" else _fmt(ref_low),
            "ref_high": "" if ref_high is None or kind != "blood" else _fmt(ref_high),
            "source": "Claude",
            "note": "",
            "file": file,
            "status": "proposed",
        })
    return rows


def ask_claude(path: Path, api_key: str, model: str) -> dict[str, Any] | None:
    """The tool input Claude returns for one report file; None when it answered without the tool."""
    media_type = MEDIA_TYPES[path.suffix.lower()]
    data = base64.standard_b64encode(path.read_bytes()).decode()
    block_type = "document" if media_type == "application/pdf" else "image"
    response = requests.post(
        API_URL,
        headers={"x-api-key": api_key, "anthropic-version": API_VERSION, "content-type": "application/json"},
        json={
            "model": model,
            "max_tokens": 2000,
            "tools": [TOOL],
            "tool_choice": {"type": "auto"},
            "messages": [{"role": "user", "content": [
                {"type": block_type, "source": {"type": "base64", "media_type": media_type, "data": data}},
                {"type": "text", "text": PROMPT},
            ]}],
        },
        timeout=120,
    )
    response.raise_for_status()
    for block in response.json().get("content") or []:
        if block.get("type") == "tool_use" and block.get("name") == TOOL["name"]:
            return block.get("input") or {}
    return None


def evaluate(api_key: str | None = None, model: str | None = None, today: date | None = None) -> dict[str, int]:
    """Evaluates up to MAX_FILES_PER_RUN pending reports; returns counts of files and proposed values."""
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise config.SetupError(
            "No ANTHROPIC_API_KEY. Without it, reports are only read in the dashboard (PDFs with text).")
    model = model or os.environ.get("SELFTOPO_CLAUDE_MODEL") or DEFAULT_MODEL
    today = today or config.today()
    rows = read_rows(config.MEASUREMENTS_CSV)
    ledger_path = evaluations_path()
    ledger: dict[str, Any] = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else {}
    pending = pending_files(config.DATA_DIR, rows, ledger)
    counts = {"files": 0, "values": 0, "failed": 0, "waiting": max(0, len(pending) - MAX_FILES_PER_RUN)}
    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    for rel in pending[:MAX_FILES_PER_RUN]:
        path = config.DATA_DIR / rel
        if path.stat().st_size > MAX_BYTES:
            ledger[rel] = {"at": now, "result": "too_large"}
            continue
        try:
            answer = ask_claude(path, api_key, model)
        except requests.RequestException as exc:
            # Not recorded, so the next run tries again
            log.warning("reports: %s failed: %s", rel, str(exc)[:200])
            counts["failed"] += 1
            continue
        if answer is None:
            # Recorded, so the file is not sent again each run; delete its entry to try once more
            ledger[rel] = {"at": now, "result": "no_answer", "model": model}
            counts["files"] += 1
            log.warning("reports: %s answered without values", rel)
            continue
        found = to_rows(answer, rel, today)
        rows.extend(found)
        ledger[rel] = {"at": now, "result": "proposed" if found else "nothing", "values": len(found), "model": model}
        counts["files"] += 1
        counts["values"] += len(found)
        log.info("reports: %s → %d values proposed", rel, len(found))
    if counts["values"]:
        write_rows(config.MEASUREMENTS_CSV, FIELDS, sorted(rows, key=lambda r: (r.get("date", ""), r.get("kind", ""))))
    if pending:
        ledger_path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return counts
