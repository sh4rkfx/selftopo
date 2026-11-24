"""Reports read by the Claude API

Files in files/ that no row of measurements.csv points to go to the Claude API once; what it finds
becomes rows with status `proposed`, values outside the plausible range or without a valid date are
dropped, and report_evaluations.json keeps every file from being sent twice. The API is faked here.
"""

# ruff: noqa: E501

import json
from datetime import date

import pytest
import requests

from selftopo import config, reports
from selftopo.csvstore import read_rows, write_rows

TODAY = date(2026, 11, 24)


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "MEASUREMENTS_CSV", tmp_path / "measurements.csv")
    (tmp_path / "files").mkdir()
    return tmp_path


def test_only_new_unreferenced_reports_are_pending(data, given):
    """A file a row points to, one already evaluated and a text file are skipped."""
    for name in ("a.pdf", "b.jpg", "c.png", "notes.txt"):
        (data / "files" / name).write_bytes(b"x")
    rows = [{"file": "files/a.pdf"}]
    pending = reports.pending_files(data, rows, {"files/b.jpg": {"result": "nothing"}})
    given(pending=pending)
    assert pending == ["files/c.png"]


def test_symlinks_are_never_sent(data, given):
    """A link named like a report, to a file elsewhere, is not a report."""
    secret = data / "settings.json"
    secret.write_text("{}", encoding="utf-8")
    (data / "files" / "link.pdf").symlink_to(secret)
    (data / "files" / "real.pdf").write_bytes(b"x")
    pending = reports.pending_files(data, [], {})
    given(pending=pending)
    assert pending == ["files/real.pdf"]


def test_a_linked_files_folder_is_not_read(data, tmp_path, given):
    """files/ pointing at a folder outside the repository gives nothing to send."""
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "private.pdf").write_bytes(b"x")
    (data / "files").rmdir()
    (data / "files").symlink_to(outside, target_is_directory=True)
    pending = reports.pending_files(data, [], {})
    given(pending=pending)
    assert pending == []


def test_tool_result_becomes_checked_proposals(given):
    """Plausible values become proposed rows; a VO2max of 4.4 (l/min read as ml/kg/min), a blood value
    without name and a second Ferritin are dropped; units come from the kind, not from the answer."""
    result = {"date": "2026-11-23", "values": [
        {"kind": "rmr_kcal", "value": 2455, "unit": "kcal"},
        {"kind": "rer", "value": 0.77},
        {"kind": "vo2max_lab", "value": 4.4, "unit": "l/min"},
        {"kind": "blood", "name": "Ferritin", "value": 86, "unit": "µg/l", "ref_low": 30, "ref_high": 400},
        {"kind": "blood", "name": "ferritin", "value": 90, "unit": "µg/l"},
        {"kind": "blood", "value": 5},
    ]}
    rows = reports.to_rows(result, "files/x.pdf", TODAY)
    given(rows=rows)
    assert [(r["kind"], r["name"], r["value"], r["unit"], r["ref_low"], r["ref_high"]) for r in rows] == [
        ("rmr_kcal", "", "2455", "kcal/d", "", ""), ("rer", "", "0.77", "", "", ""),
        ("blood", "Ferritin", "86", "µg/l", "30", "400")]
    assert {r["status"] for r in rows} == {"proposed"} and {r["file"] for r in rows} == {"files/x.pdf"}


def test_no_rows_without_a_valid_past_date(given):
    """A missing, impossible or future date gives nothing to confirm."""
    values = [{"kind": "waist_cm", "value": 90}]
    got = [reports.to_rows({"date": d, "values": values}, "f", TODAY) for d in (None, "2026-02-30", "2026-12-01")]
    given(results=got)
    assert got == [[], [], []]


def test_upload_date_in_the_file_name_when_the_report_has_none(given):
    """A scan without a legible date takes the date the dashboard put in the file name; Claude's date wins."""
    values = [{"kind": "waist_cm", "value": 90}]
    none = reports.to_rows({"date": None, "values": values}, "files/2026-11-20-scan.jpg", TODAY)
    read = reports.to_rows({"date": "2026-11-18", "values": values}, "files/2026-11-20-scan.jpg", TODAY)
    given(none=none, read=read)
    assert [r["date"] for r in none] == ["2026-11-20"] and [r["date"] for r in read] == ["2026-11-18"]


def test_evaluate_writes_proposals_and_remembers_files(data, monkeypatch, given):
    """One file with values, one without; a failing request is not remembered, so it is tried again."""
    for name in ("lab.pdf", "photo.jpg", "broken.png", "chatty.png"):
        (data / "files" / name).write_bytes(b"x")
    write_rows(data / "measurements.csv", reports.FIELDS, [{"id": "a", "date": "2026-11-01", "kind": "waist_cm", "value": "91", "status": "confirmed"}])

    def fake(path, api_key, model):
        if path.name == "broken.png":
            raise requests.ConnectionError("down")
        if path.name == "chatty.png":
            return None  # answered in text instead of calling the tool
        if path.name == "lab.pdf":
            return {"date": "2026-10-30", "values": [{"kind": "blood", "name": "HbA1c", "value": 5.4, "unit": "%"}]}
        return {"date": None, "values": []}

    monkeypatch.setattr(reports, "ask_claude", fake)
    counts = reports.evaluate(api_key="k", today=TODAY)
    rows = read_rows(data / "measurements.csv")
    ledger = json.loads((data / "report_evaluations.json").read_text(encoding="utf-8"))
    given(counts=counts, ledger=ledger)
    assert counts == {"files": 3, "values": 1, "failed": 1, "waiting": 0}
    assert [(r["kind"], r["name"], r["status"], r["file"]) for r in rows] == [
        ("blood", "HbA1c", "proposed", "files/lab.pdf"), ("waist_cm", "", "confirmed", "")]
    assert set(ledger) == {"files/lab.pdf", "files/photo.jpg", "files/chatty.png"} and ledger["files/photo.jpg"]["result"] == "nothing"
    assert ledger["files/chatty.png"]["result"] == "no_answer"
    assert reports.pending_files(data, rows, ledger) == ["files/broken.png"]


@pytest.mark.parametrize(("status", "remembered"), [(400, True), (413, True), (429, False), (529, False), (401, False), (404, False)])
def test_a_refused_file_is_remembered_a_busy_api_or_wrong_setup_is_not(data, monkeypatch, given, status, remembered):
    """400/413 refuse this file and are recorded; 429 and 5xx are retried; a wrong key or model (401, 404) stops the run unrecorded."""
    for name in ("a.png", "b.png"):
        (data / "files" / name).write_bytes(b"x")
    response = requests.Response()
    response.status_code = status
    calls = []

    def fake(path, api_key, model):
        calls.append(path.name)
        raise requests.HTTPError(f"{status}", response=response)

    monkeypatch.setattr(reports, "ask_claude", fake)
    reports.evaluate(api_key="k", model="m1", today=TODAY)
    path = data / "report_evaluations.json"
    ledger = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    given(status=status, ledger=ledger, calls=calls)
    assert (ledger.get("files/a.png", {}).get("result") == f"error_{status}") is remembered
    assert calls == (["a.png"] if status in (401, 404) else ["a.png", "b.png"])


def test_a_refused_file_is_tried_again_with_another_model(data, given):
    """The refusal may have come from the model: a new model gets the file once more, the same one does not."""
    (data / "files" / "a.png").write_bytes(b"x")
    ledger = {"files/a.png": {"result": "error_400", "model": "m1"}}
    same, other = reports.pending_files(data, [], ledger, "m1"), reports.pending_files(data, [], ledger, "m2")
    given(same=same, other=other)
    assert same == [] and other == ["files/a.png"]


def test_ids_are_unique_among_existing_rows(data, monkeypatch, given):
    """A colliding id gets a new suffix, so editing one value never touches another."""
    (data / "files" / "lab.png").write_bytes(b"x")
    write_rows(data / "measurements.csv", reports.FIELDS, [{"id": "2026-10-30-blood-aaaaaaaaaaaa", "date": "2026-10-30", "kind": "blood", "name": "X", "value": "1", "status": "confirmed"}])
    tokens = iter(["aaaaaaaaaaaa", "aaaaaaaaaaaa", "bbbbbbbbbbbb"])
    monkeypatch.setattr(reports.secrets, "token_hex", lambda n: next(tokens))
    monkeypatch.setattr(reports, "ask_claude", lambda *a: {"date": "2026-10-30", "values": [{"kind": "blood", "name": "Ferritin", "value": 86, "unit": "µg/l"}]})
    reports.evaluate(api_key="k", today=TODAY)
    ids = [r["id"] for r in read_rows(data / "measurements.csv")]
    given(ids=ids)
    assert len(ids) == len(set(ids)) == 2


def test_without_api_key_it_explains(data, monkeypatch, given):
    """No secret: a setup error with what still works."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    given(env="no ANTHROPIC_API_KEY")
    with pytest.raises(config.SetupError, match="only read in the dashboard"):
        reports.evaluate()


def test_request_sends_pdf_as_document_with_a_strict_tool(data, monkeypatch, given):
    """PDF as a document block; tool_choice auto with a strict tool, since newer models reject forced tool use."""
    (data / "files" / "r.pdf").write_bytes(b"%PDF")
    sent = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"content": [{"type": "tool_use", "name": "record_values", "input": {"date": "2026-11-23", "values": []}}]}

    def post(url, headers, json, timeout):
        sent.update(url=url, headers=headers, body=json)
        return Response()

    monkeypatch.setattr(reports.requests, "post", post)
    out = reports.ask_claude(data / "files" / "r.pdf", "key", "model-x")
    body = sent["body"]
    given(block=body["messages"][0]["content"][0]["type"], tool_choice=body["tool_choice"])
    assert out == {"date": "2026-11-23", "values": []}
    assert body["messages"][0]["content"][0]["type"] == "document" and body["tool_choice"] == {"type": "auto"} and body["tools"][0]["strict"] is True
    assert sent["headers"]["x-api-key"] == "key" and body["model"] == "model-x"


def test_values_already_entered_are_not_proposed_again(data, monkeypatch, given):
    """The dashboard saved Ferritin 86 from the same PDF: only the new HbA1c becomes a proposal."""
    (data / "files" / "lab.pdf").write_bytes(b"x")
    write_rows(data / "measurements.csv", reports.FIELDS, [{"id": "a", "date": "2026-10-30", "kind": "blood", "name": "Ferritin", "value": "86", "status": "confirmed"}])
    monkeypatch.setattr(reports, "ask_claude", lambda *a: {"date": "2026-10-30", "values": [
        {"kind": "blood", "name": "ferritin", "value": 86.0, "unit": "µg/l"}, {"kind": "blood", "name": "HbA1c", "value": 5.4, "unit": "%"}]})
    reports.evaluate(api_key="k", today=TODAY)
    proposed = [r["name"] for r in read_rows(data / "measurements.csv") if r["status"] == "proposed"]
    given(proposed=proposed)
    assert proposed == ["HbA1c"]
