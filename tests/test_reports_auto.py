"""Values from an uploaded report, entered by themselves

The dashboard reads PDFs with text, also when a value stands below its label as in SpiroFit's
report tiles. Unambiguous values are entered as confirmed, the rest as proposals; files under
files/ that no row names yet are read once when the dashboard opens with write access. The
helpers run in Node; without Node these tests are skipped.
"""

# ruff: noqa: E501

import json
import re

from jsdashboard import HTML, run

READ = ["DAY", "isoToT", "tToIso", "todayT", "DECIMAL", "parseNumber", "MEASURE_KINDS", "REPORT_RULES", "LAB_LINE", "LAB_SKIP",
        "OTHER_FIGURE", "valueBelow", "ESTIMATE_LINE", "reportNumbers", "decimalMark", "reportDate", "hasUnclearDate", "extractMeasures"]
ROWS = READ + ["AUTO_SOURCE", "reportRows"]

# The text layout pdf.js gives for a SpiroFit "Resting Test" (lines by baseline), names left out
SPIROFIT = """Resting Test
23.11.2026, 08:13:26
Größe 180 cm Gewicht 80.0 kg
RMR
Dieser Wert gibt an, wie viele Kalorien der Körper im völligen Ruhezustand verbraucht, was dem Grundumsatz (BMR)
ähnelt. Die Ruheenergieverbrauchsrate steht hauptsächlich im Zusammenhang mit der fettfreien Körpermasse,
2.455 kcal/d
einschließlich Muskelgewebe und innerer Organe, jedoch nicht mit Körperfett.
Ein langsamerer Stoffwechsel ist oft durch eine verringerte Ruheenergiezufuhr (RMR – Resting Metabolic Rate)
Ruheumsatz im Vergleich Lebensstilbedingte Kalorien
Minimum gemessen Maximum
2.454,8
1.350 kcal/d
berechnet
1.841,6
3.805 kcal/d
Täglicher Gesamtenergieverbrauch
RER in Ruhe Der Respiratorische Austauschquotient (RER) in Ruhe ist ein Wert, der es ermöglicht, das Verhältnis der im
Ruhezustand verwendeten Brennstoffquellen (Kohlenhydrate vs. Fette) grob zu bestimmen. Werte näher bei 0,7 deuten
0,77
darauf hin, dass Fett die Hauptenergiequelle ist, während Werte näher bei 1,0 auf eine erhöhte Nutzung von"""


def extract(text):
    return run(READ, f"extractMeasures({json.dumps(text)}, isoToT('2026-11-25'))")


def rows(found, existing=(), fallback=None, file="files/2026-11-23-test.pdf"):
    return run(ROWS, f"reportRows({json.dumps(found)}, {json.dumps(file)}, {json.dumps(list(existing))}, {json.dumps(fallback)})")


def test_value_below_its_label(given):
    """RMR 2,455 kcal/d and RER 0.77 below their headings, dated 23.11.2026; not the comparison
    figures (2,454.8, calculated 1,841.6), lifestyle 1,350, the total 3,805 or the 0.7 in the text."""
    found = extract(SPIROFIT)
    given(found=found)
    assert found == {"date": "2026-11-23", "items": [{"kind": "rmr_kcal", "value": 2455}, {"kind": "rer", "value": 0.77}]}
    # Under a heading of another figure nothing is taken
    other = extract("Ruheumsatz im Vergleich\n1.350 kcal/d\n")
    assert other["items"] == []


def test_unambiguous_rules(given):
    """Confirmed with the report's own date, the kind once and no other value that day; a blood value
    also needs a name and a unit; otherwise a proposal."""
    rmr = {"kind": "rmr_kcal", "value": 2455}
    cases = {
        "clear": rows({"date": "2026-11-23", "items": [rmr]}),
        "date from the file name": rows({"date": None, "items": [rmr]}, fallback="2026-11-23"),
        "twice": rows({"date": "2026-11-23", "items": [rmr, {**rmr, "value": 2390}]}),
        "other value that day": rows({"date": "2026-11-23", "items": [rmr]}, existing=[{"date": "2026-11-23", "kind": "rmr_kcal", "value": 2390, "name": ""}]),
        "blood without unit": rows({"date": "2026-11-23", "items": [{"kind": "blood", "name": "Ferritin", "value": 86, "unit": ""}]}),
    }
    status = {k: [r["status"] for r in v] for k, v in cases.items()}
    same = rows({"date": "2026-11-23", "items": [rmr]}, existing=[{"date": "2026-11-23", "kind": "rmr_kcal", "value": 2455, "name": ""}])
    given(status=status, already_there=same)
    assert status == {"clear": ["confirmed"], "date from the file name": ["proposed"], "twice": ["proposed", "proposed"],
                      "other value that day": ["proposed"], "blood without unit": ["proposed"]}
    assert same == []


def test_unambiguous_saved_confirmed_others_proposed(given):
    """From the SpiroFit text: RMR and RER entered as confirmed rows with the file, the kind's unit and the source."""
    out = rows(extract(SPIROFIT))
    given(rows=out)
    assert [(r["kind"], r["value"], r["unit"], r["status"], r["file"], r["source"]) for r in out] == [
        ("rmr_kcal", "2455", "kcal/d", "confirmed", "files/2026-11-23-test.pdf", "automatisch gelesen"),
        ("rer", "0.77", "", "confirmed", "files/2026-11-23-test.pdf", "automatisch gelesen")]
    assert len({r["id"] for r in out}) == 2


def test_unread_files_are_read_once(given):
    """PDFs under files/ that no row names, at most 3; a file version read without values is not read
    again in this browser; photos and files over 5 MB are left to the Claude reader."""
    listing = [{"type": "file", "name": f"2026-11-2{i}-r.pdf", "path": f"files/2026-11-2{i}-r.pdf", "sha": f"s{i}", "size": 1000} for i in range(5)]
    listing += [{"type": "file", "name": "scan.jpg", "path": "files/scan.jpg", "sha": "j", "size": 10}, {"type": "file", "name": "big.pdf", "path": "files/big.pdf", "sha": "b", "size": 6 * 1024 * 1024}]
    existing = [{"file": "files/2026-11-20-r.pdf"}]
    tried = {"files/2026-11-21-r.pdf": "s1", "files/2026-11-22-r.pdf": "old"}
    out = run(["REPORT_MAX_BYTES", "AUTO_READ_MAX", "unreadReports"], f"unreadReports({json.dumps(listing)}, {json.dumps(existing)}, {json.dumps(tried)}).map((f) => f.path)")
    load = re.search(r"          fillSettings\(\);\n          autoReadReports\(\);", HTML)
    given(read=out)
    assert out == ["files/2026-11-22-r.pdf", "files/2026-11-23-r.pdf", "files/2026-11-24-r.pdf"]
    assert load is not None


def test_auto_entries_are_marked(given):
    """The Befunde card says what was entered from which file; the table names the source in German and English."""
    text = run(["valuesText", "autoReadText"], "autoReadText([{ file: 'files/2026-11-23-test.pdf', confirmed: 2, proposed: 0 }, { file: 'files/lab.pdf', confirmed: 1, proposed: 2 }])")
    en = json.loads(re.search(r'<script type="application/json" id="i18n-en">(.*?)</script>', HTML, re.S).group(1))
    given(text=text)
    assert text == "Aus 2026-11-23-test.pdf automatisch eingetragen: 2 Werte. Aus lab.pdf automatisch eingetragen: 1 Wert; 2 Werte warten unten auf dich."
    assert 'm.source === AUTO_SOURCE ? T("automatisch gelesen")' in HTML and en["automatisch gelesen"] == "read automatically"
    assert 'id="befunde-auto" hidden' in HTML


def test_auto_read_is_retried_and_never_overlaps(given):
    """A failed download is not remembered; two calls during one pass share it; a proposal of that day does not make a value ambiguous."""
    body = re.search(r"  async function readUnreadReports\(cred\) \{.*?\n  \}", HTML, re.S).group(0)
    guard = re.search(r"  function autoReadReports\(cred = loadCredentials\(\)\) \{.*?\n  \}", HTML, re.S).group(0)
    proposal = rows({"date": "2026-11-23", "items": [{"kind": "rmr_kcal", "value": 2455}]},
                    existing=[{"date": "2026-11-23", "kind": "rmr_kcal", "value": 2390, "name": "", "status": "proposed"}])
    given(status=[r["status"] for r in proposal])
    assert "if (found) tried[f.path] = f.sha;" in body and "autoReading ||=" in guard
    assert "const key = `${AUTO_READ_KEY}:${cred.repo}`;" in body  # remembered per data repository
    assert [r["status"] for r in proposal] == ["confirmed"]
