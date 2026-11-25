"""Energy expenditure from measured values

A resting metabolic rate measured by indirect calorimetry (Befunde → Ruheumsatz) replaces Garmin's
resting kcal (total minus active) from the day of the measurement until the next one, as a factor
on Garmin's value or as the measured value itself. Garmin's columns stay unchanged, and with the
mode off nothing changes. The dashboard (JavaScript) and the recommendations (selftopo/energy.py)
follow the same rules; the dashboard half runs in Node and is skipped without it.
"""

# ruff: noqa: E501

import json
import random
from datetime import date, timedelta

import pandas as pd
import pytest
from jsdashboard import run

from selftopo import energy, reports
from selftopo.csvstore import write_rows

HELPERS = ["DAY", "isoToT", "tToIso", "RMR_MODES", "RMR_REF_DAYS", "RMR_REF_MIN_DAYS", "readEnergySettings", "rmrReference",
           "rmrPeriods", "rmrPeriodAt", "applyEnergy"]
TODAY = date(2026, 11, 25)
MEASURED = date(2026, 11, 23)


def garmin(start=date(2026, 10, 20), end=TODAY, rest=2139, active=lambda d: 400 + (d.day % 5) * 60, skip=(), partial=None):
    """One row per day: calories_total = rest + active, calories_active = active."""
    rows, d = [], start
    while d <= end:
        if d not in skip:
            a = active(d)
            r = (partial or {}).get(d, rest)
            rows.append({"date": d.isoformat(), "calories_total": r + a, "calories_active": a})
        d += timedelta(days=1)
    return rows


def rmr(day, value=2390, status="confirmed", **more):
    return {"id": f"{day}-rmr", "date": day.isoformat(), "kind": "rmr_kcal", "value": str(value), "status": status, **more}


def dashboard(rows, measurements, settings, today=TODAY, fraction=1.0):
    """applyEnergy in the dashboard: per day [restGarmin, rest, kcalBurned, kcalGarmin], and the periods."""
    days = [{"t": f"isoToT('{r['date']}')", "kcalBurned": r["calories_total"], "activeGarmin": r["calories_active"]} for r in rows]
    days_js = "[" + ",".join(f"{{t: {d['t']}, kcalBurned: {json.dumps(d['kcalBurned'])}, activeGarmin: {json.dumps(d['activeGarmin'])}}}" for d in days) + "]"
    ms = [{"kind": m["kind"], "status": m["status"], "t": f"isoToT('{m['date']}')", "value": float(m["value"]), "id": m["id"]} for m in measurements]
    ms_js = "[" + ",".join(f"{{kind: '{m['kind']}', status: '{m['status']}', t: {m['t']}, value: {m['value']}, id: '{m['id']}'}}" for m in ms) + "]"
    expr = (f"(() => {{ const days = {days_js}; const p = applyEnergy(days, {ms_js}, readEnergySettings({json.dumps(settings)}), isoToT('{today}'), {fraction});"
            " return { days: Object.fromEntries(days.map((d) => [tToIso(d.t), [d.restGarmin, d.rest, d.kcalBurned, d.kcalGarmin]])),"
            " periods: p.map((x) => ({ from: tToIso(x.from), to: x.to == null ? null : tToIso(x.to), rmr: x.rmr, factor: x.factor, measuredFactor: x.measuredFactor,"
            " ref: x.ref && { kcal: x.ref.kcal, n: x.ref.n, from: tToIso(x.ref.from), to: tToIso(x.ref.to), warn: x.ref.warn } })) }; })()")
    return run(HELPERS, expr)


def python(tmp_path, rows, measurements, settings, today=TODAY, fraction=1.0):
    """selftopo.energy.apply on a frame of calendar days, measurements read from a real measurements.csv."""
    path = tmp_path / "measurements.csv"
    write_rows(path, reports.FIELDS, measurements)
    frame = pd.DataFrame(rows).assign(date=lambda f: pd.to_datetime(f["date"])).set_index("date")
    frame = frame.reindex(pd.date_range(frame.index.min(), pd.Timestamp(today), freq="D"))
    periods = energy.apply(frame, energy.read_measurements(path), energy.read_settings(settings), today, fraction)
    return frame, periods


# --------------------------------------------------------------------------- reference and factor


def test_reference_uses_complete_plausible_days(tmp_path, given):
    """14 days up to and including 23.11. (10.–23.11.): 12.11. has no data and 15.11. only 900 kcal
    (below half the median), so 12 days of 2,139 kcal; a measurement on the running day leaves it out."""
    rows = garmin(skip={date(2026, 11, 12)}, partial={date(2026, 11, 15): 900, TODAY: 1200})
    js = dashboard(rows, [rmr(MEASURED), rmr(TODAY, 2400)], {})
    _, py = python(tmp_path, rows, [rmr(MEASURED), rmr(TODAY, 2400)], {})
    given(window="2026-11-10 to 2026-11-23", reference=js["periods"][0]["ref"], running_day=js["periods"][1]["ref"])
    assert js["periods"][0]["ref"] == {"kcal": 2139, "n": 12, "from": "2026-11-10", "to": "2026-11-23", "warn": False}
    assert py[0]["ref"] == {"kcal": 2139, "n": 12, "from": date(2026, 11, 10), "to": date(2026, 11, 23), "warn": False}
    # 12.–24.11.: 13 days without 12.11. and 15.11.; the running day 25.11. (1,200) is not counted
    assert js["periods"][1]["ref"]["n"] == py[1]["ref"]["n"] == 11 and js["periods"][1]["ref"]["to"] == "2026-11-24"


def test_few_reference_days_warn(tmp_path, given):
    """Garmin data from 21.11. only: 3 days before the measurement, the factor is used with a warning."""
    rows = garmin(start=date(2026, 11, 21))
    js = dashboard(rows, [rmr(MEASURED)], {"rmrCorrectionMode": "factor"})
    _, py = python(tmp_path, rows, [rmr(MEASURED)], {"rmrCorrectionMode": "factor"})
    given(reference=js["periods"][0]["ref"], factor=js["periods"][0]["factor"])
    assert js["periods"][0]["ref"]["n"] == py[0]["ref"]["n"] == 3
    assert js["periods"][0]["ref"]["warn"] is True and py[0]["ref"]["warn"] is True
    assert js["periods"][0]["factor"] == py[0]["factor"] == 1.117


def test_factor_and_override(tmp_path, given):
    """2,390 / 2,139 = 1.117 (3 decimals); rmrFactorOverride 1.1 takes precedence, the measured factor stays visible."""
    rows = garmin()
    measured = dashboard(rows, [rmr(MEASURED)], {"rmrCorrectionMode": "factor"})["periods"][0]
    override = dashboard(rows, [rmr(MEASURED)], {"rmrCorrectionMode": "factor", "rmrFactorOverride": 1.1})
    frame, py = python(tmp_path, rows, [rmr(MEASURED)], {"rmrCorrectionMode": "factor", "rmrFactorOverride": 1.1})
    given(measured=measured["factor"], override=override["periods"][0]["factor"], day="2026-11-24")
    assert measured["factor"] == 1.117
    assert override["periods"][0]["factor"] == py[0]["factor"] == 1.1 and override["periods"][0]["measuredFactor"] == py[0]["measured_factor"] == 1.117
    assert override["days"]["2026-11-24"][1] == pytest.approx(2139 * 1.1)
    assert frame.loc["2026-11-24", "resting_kcal"] == pytest.approx(2139 * 1.1)


@pytest.mark.parametrize(("settings", "problems"), [({"rmrCorrectionMode": "on"}, 1), ({"rmrFactorOverride": 3}, 1), ({"rmrFactorOverride": "x"}, 1), ({}, 0)])
def test_invalid_energy_settings_mean_off(given, settings, problems):
    """An unknown mode or a factor outside 0.5–2 is reported and treated as missing."""
    js = run(HELPERS, f"(() => {{ const p = []; const s = readEnergySettings({json.dumps(settings)}, p); return [s, p.length]; }})()")
    py_problems = []
    py = energy.read_settings(settings, py_problems)
    given(settings=settings, dashboard=js[0])
    assert js[0] == {"rmrMode": "off", "rmrFactorOverride": None} and js[1] == problems
    assert py.rmr_mode == "off" and py.rmr_factor_override is None and len(py_problems) == problems


# --------------------------------------------------------------------------- modes and periods


def test_modes_factor_absolute_and_today_prorated(tmp_path, given):
    """Factor: resting = 2,139 × 1.117; absolute: resting = 2,390; on the running day at 12:00 the
    absolute value is half, 1,195, while Garmin's own value for today is already partial."""
    rows = garmin(partial={TODAY: 1100})
    out = {}
    for mode in ("factor", "absolute"):
        js = dashboard(rows, [rmr(MEASURED)], {"rmrCorrectionMode": mode}, fraction=0.5)
        frame, _ = python(tmp_path, rows, [rmr(MEASURED)], {"rmrCorrectionMode": mode}, fraction=0.5)
        out[mode] = {"24.11.": js["days"]["2026-11-24"][1], "today": js["days"]["2026-11-25"][1]}
        assert frame.loc["2026-11-24", "resting_kcal"] == pytest.approx(js["days"]["2026-11-24"][1])
        assert frame.loc["2026-11-25", "resting_kcal"] == pytest.approx(js["days"]["2026-11-25"][1])
    given(resting=out)
    assert out["factor"]["24.11."] == pytest.approx(2139 * 1.117) and out["factor"]["today"] == pytest.approx(1100 * 1.117)
    assert out["absolute"] == {"24.11.": 2390, "today": 1195}


def test_validity_periods_and_only_confirmed(tmp_path, given):
    """2,300 from 10.11., 2,450 from 20.11.; the proposal of 15.11. does not count; before 10.11. Garmin's 2,139."""
    rows = garmin()
    ms = [rmr(date(2026, 11, 10), 2300), rmr(date(2026, 11, 15), 3000, status="proposed"), rmr(date(2026, 11, 20), 2450)]
    js = dashboard(rows, ms, {"rmrCorrectionMode": "absolute"})
    frame, py = python(tmp_path, rows, ms, {"rmrCorrectionMode": "absolute"})
    rest = {d: js["days"][d][1] for d in ("2026-11-09", "2026-11-10", "2026-11-15", "2026-11-19", "2026-11-20", "2026-11-24")}
    given(periods=[(p["from"], p["to"], p["rmr"]) for p in js["periods"]], resting=rest)
    assert [(p["from"], p["to"]) for p in js["periods"]] == [("2026-11-10", "2026-11-19"), ("2026-11-20", None)]
    assert [(p["from"], p["to"]) for p in py] == [(date(2026, 11, 10), date(2026, 11, 19)), (date(2026, 11, 20), None)]
    assert rest == {"2026-11-09": 2139, "2026-11-10": 2300, "2026-11-15": 2300, "2026-11-19": 2300, "2026-11-20": 2450, "2026-11-24": 2450}
    assert frame["resting_kcal"].loc["2026-11-09":"2026-11-24"].tolist() == [js["days"][d][1] for d in sorted(js["days"]) if "2026-11-09" <= d <= "2026-11-24"]


def test_measured_rmr_replaces_garmin_resting(tmp_path, given):
    """Expenditure = measured resting + active, never Garmin's total + RMR; Garmin's columns are unchanged."""
    rows = garmin()
    js = dashboard(rows, [rmr(MEASURED)], {"rmrCorrectionMode": "absolute"})
    frame, _ = python(tmp_path, rows, [rmr(MEASURED)], {"rmrCorrectionMode": "absolute"})
    raw = next(r for r in rows if r["date"] == "2026-11-24")
    rest_garmin, rest, burned, garmin_total = js["days"]["2026-11-24"]
    given(garmin_total=raw["calories_total"], active=raw["calories_active"], expenditure=burned)
    assert burned == 2390 + raw["calories_active"] and burned != raw["calories_total"] + 2390
    assert garmin_total == raw["calories_total"] and rest_garmin == 2139
    assert frame.loc["2026-11-24", "expenditure_kcal"] == burned
    assert frame.loc["2026-11-24", "calories_total"] == raw["calories_total"] and frame.loc["2026-11-24", "resting_garmin"] == 2139


def test_all_off_output_unchanged(tmp_path, given):
    """Without the key, with "off", or before the first measurement: expenditure is Garmin's total."""
    rows = garmin()
    for settings in ({}, {"rmrCorrectionMode": "off", "rmrFactorOverride": 1.2}):
        js = dashboard(rows, [rmr(MEASURED)], settings)
        frame, _ = python(tmp_path, rows, [rmr(MEASURED)], settings)
        assert all(v[2] == v[3] for v in js["days"].values())
        assert (frame["expenditure_kcal"] == frame["calories_total"]).all()
    before = dashboard(rows, [rmr(MEASURED)], {"rmrCorrectionMode": "factor"})["days"]["2026-11-22"]
    given(settings=["{}", "off"], day_before_measurement=before)
    assert before[2] == before[3]


def test_python_and_dashboard_agree(tmp_path, given):
    """60 random days with gaps and partial days, two measurements, every mode: the same resting kcal and expenditure per day."""
    rnd = random.Random(7)
    rows = []
    for i in range(60):
        d = date(2026, 9, 27) + timedelta(days=i)
        if rnd.random() < 0.1:
            continue
        rest = rnd.choice([2139, 2144, 900]) if rnd.random() < 0.15 else 2139
        act = rnd.randint(20, 1100)
        rows.append({"date": d.isoformat(), "calories_total": rest + act, "calories_active": act})
    ms = [rmr(date(2026, 10, 20), 2350), rmr(date(2026, 11, 15), 2410)]
    compared = 0
    for settings in ({"rmrCorrectionMode": "factor"}, {"rmrCorrectionMode": "absolute"}, {"rmrCorrectionMode": "factor", "rmrFactorOverride": 1.05}, {}):
        js = dashboard(rows, ms, settings, fraction=0.3)
        frame, _ = python(tmp_path, rows, ms, settings, fraction=0.3)
        for iso, (_, rest, burned, _) in js["days"].items():
            assert frame.loc[iso, "resting_kcal"] == pytest.approx(rest) and frame.loc[iso, "expenditure_kcal"] == pytest.approx(burned)
            compared += 1
    given(days=len(rows), compared=compared)
