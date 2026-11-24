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

HELPERS = ["isoToT", "MEASURE_KINDS", "MEASURE_GROUPS", "parseMeasurements", "refState", "measurementGroups"]


def parse(rows):
    return run(HELPERS, f"parseMeasurements({json.dumps(rows)})")


def row(date, kind, value, **more):
    return {"date": date, "kind": kind, "value": value, **more}


def test_unreadable_rows_are_counted_not_shown(given):
    """Missing date, a text as value, an unknown kind or a blood value without a name."""
    rows = [row("2026-11-23", "rmr_kcal", "2455"), row("", "waist_cm", "90"), row("2026-11-01", "waist_cm", "neunzig"),
            row("2026-11-01", "glucose", "90"), row("2026-11-01", "blood", "86")]
    given(rows=rows)
    out = parse(rows)
    assert [m["kind"] for m in out["list"]] == ["rmr_kcal"] and out["invalid"] == 4


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
