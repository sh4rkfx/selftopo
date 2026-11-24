"""Befunde: measurements.csv

Values from labs and tests entered in the dashboard. Rows are read leniently but never guessed:
a row without a date, a number or a known kind is counted as unreadable. The card shows the
newest value per measure, a RER next to the resting metabolic rate of the same day, and rates
blood values only against the reference range on the report. The helpers run in Node; without
Node these tests are skipped.
"""

# ruff: noqa: E501

import json

from jsdashboard import run

HELPERS = ["isoToT", "tToIso", "MEASURE_KINDS", "MEASURE_GROUPS", "parseMeasurements", "refState", "measurementGroups"]


def parse(rows):
    return run(HELPERS, f"parseMeasurements({json.dumps(rows)})")


def row(date, kind, value, **more):
    return {"date": date, "kind": kind, "value": value, **more}


def test_unreadable_rows_are_counted_not_shown(given):
    """Missing or impossible date, a text as value, an unknown kind or a blood value without a name."""
    rows = [row("2026-11-23", "rmr_kcal", "2455"), row("", "waist_cm", "90"), row("2026-11-01", "waist_cm", "neunzig"),
            row("2026-11-01", "glucose", "90"), row("2026-11-01", "blood", "86"), row("2026-02-30", "waist_cm", "90")]
    given(rows=rows)
    out = parse(rows)
    assert [m["kind"] for m in out["list"]] == ["rmr_kcal"] and out["invalid"] == 5


def test_decimal_comma_and_reference_range(given):
    """"5,4" reads as 5.4; reference bounds are optional and numbers."""
    out = parse([row("2026-10-30", "blood", "5,4", name="HbA1c", unit="%", ref_low="4,0", ref_high="5,6")])["list"][0]
    given(value=out["value"], lo=out["lo"], hi=out["hi"])
    assert (out["value"], out["lo"], out["hi"], out["status"]) == (5.4, 4.0, 5.6, "confirmed")


def test_reference_states(given):
    """Below, within or above the range on the report; no range, no verdict."""
    cases = [{"value": 24, "lo": 30, "hi": 100}, {"value": 92, "lo": 30, "hi": 400}, {"value": 142, "lo": None, "hi": 116}, {"value": 5, "lo": None, "hi": None}]
    got = [run(HELPERS, f"refState({json.dumps(c)})") for c in cases]
    given(states=got)
    assert got == ["low", "in", "high", None]


def test_card_shows_newest_per_measure_with_rer_and_without_proposals(given):
    """Two waist values → the newer one, counted 2; the RER of the same day rides along; a proposal stays out."""
    rows = [row("2026-11-02", "waist_cm", "91.1"), row("2026-11-23", "waist_cm", "90.4"),
            row("2026-11-23", "rmr_kcal", "2455"), row("2026-11-23", "rer", "0.77"),
            row("2026-11-24", "vo2max_lab", "44", status="proposed"),
            row("2026-10-30", "blood", "86", name="Ferritin"), row("2026-05-02", "blood", "70", name="ferritin")]
    groups = run(HELPERS, f"measurementGroups(parseMeasurements({json.dumps(rows)}).list).map((g) => [g.group, g.items.map((i) => [i.m.kind, i.m.value, i.n, i.rer && i.rer.value])])")
    given(groups=groups)
    assert groups == [
        ["body", [["waist_cm", 90.4, 2, None]]],
        ["metabolism", [["rmr_kcal", 2455, 1, 0.77]]],
        ["blood", [["blood", 86, 2, None]]],
    ]


ENTRY = ["isoToT", "tToIso", "DAY", "nf", "fmt", "MEASURE_KINDS", "MEASURE_UNIT_TEXT", "MEASURE_FIELDS", "measureUnitText", "parseNumber", "newMeasureId", "validateMeasurement", "csvCell", "measureCsvLine", "measureCsv", "applyMeasureChange"]
TODAY = "isoToT('2026-11-24')"


def validate(fields):
    return run(ENTRY, f"validateMeasurement({json.dumps(fields)}, {TODAY})")


def test_numbers_in_german_or_english_notation(given):
    """91,5 and 91.5 are the same; 2.455 is two thousand; text is not a number."""
    got = run(ENTRY, '["91,5", "91.5", "2.455", "0,77", ""].map(parseNumber).concat([Number.isNaN(parseNumber("neun"))])')
    given(parsed=got)
    assert got == [91.5, 91.5, 2455, 0.77, None, True]


def test_rmr_with_rer_becomes_two_rows(given):
    """The RER entered with the resting metabolic rate is stored as its own row of the same day."""
    out = validate({"kind": "rmr_kcal", "date": "2026-11-23", "value": "2.455", "rer": "0,77", "source": "Kalorimetrie"})
    given(rows=out["rows"])
    assert [(r["kind"], r["value"], r["unit"], r["date"]) for r in out["rows"]] == [("rmr_kcal", "2455", "kcal/d", "2026-11-23"), ("rer", "0.77", "", "2026-11-23")]


def test_out_of_range_future_and_missing_fields_are_explained(given):
    """Waist in mm, a date tomorrow, a blood value without name and unit, a RER of 1.3."""
    waist = validate({"kind": "waist_cm", "date": "2026-11-25", "value": "905"})["errors"]
    blood = validate({"kind": "blood", "date": "2026-11-20", "value": "86", "lo": "400", "hi": "30"})["errors"]
    rer = validate({"kind": "rmr_kcal", "date": "2026-11-20", "value": "2455", "rer": "1,3"})["errors"]
    given(waist=waist, blood=blood, rer=rer)
    assert set(waist) == {"date", "value"} and "Stimmt die Einheit" in waist["value"]
    assert set(blood) == {"name", "unit", "ref"}
    assert set(rer) == {"rer"}


def test_change_replaces_by_id_and_csv_is_sorted_and_quoted(given):
    """Editing keeps one row per id, deleting drops it; the file is sorted by date and quotes commas."""
    rows = [{"id": "a", "date": "2026-11-23", "kind": "rmr_kcal", "value": "2455"}, {"id": "b", "date": "2026-10-01", "kind": "waist_cm", "value": "91"}]
    put = [{"id": "a", "date": "2026-11-23", "kind": "rmr_kcal", "value": "2400", "note": "nüchtern, 7:30"}]
    csv = run(ENTRY, f"measureCsv(applyMeasureChange({json.dumps(rows)}, {{ put: {json.dumps(put)}, remove: ['b'] }}))")
    given(csv=csv)
    assert csv == 'id,date,kind,name,value,unit,ref_low,ref_high,source,note,file,status\na,2026-11-23,rmr_kcal,,2400,,,,,"nüchtern, 7:30",,\n'
