"""Energy expenditure in the dashboard: settings, texts and charts

Settings → General → Energy expenditure chooses how a measured RMR is used and shows the factor with
what it rests on. The helpers run in Node; without Node these tests are skipped.
"""

# ruff: noqa: E501

import json
import re

from jsdashboard import HTML, run
from test_energy import HELPERS, MEASURED, garmin, rmr

TEXT = HELPERS + ["nf", "fmt", "fmtDate", "ddmm", "longDate", "rmrInfoText"]


def info(rows, measurements, settings):
    days = "[" + ",".join(f"{{t: isoToT('{r['date']}'), kcalBurned: {r['calories_total']}, activeGarmin: {r['calories_active']}}}" for r in rows) + "]"
    ms = "[" + ",".join(f"{{kind: 'rmr_kcal', status: '{m['status']}', t: isoToT('{m['date']}'), value: {m['value']}, id: '{m['id']}'}}" for m in measurements) + "]"
    return run(TEXT, f"(() => {{ const e = readEnergySettings({json.dumps(settings)}); return rmrInfoText(applyEnergy({days}, {ms}, e, isoToT('2026-11-25'), 1), e); }})()")


def test_settings_show_factor_and_basis(given):
    """The text names the measurement, Garmin's mean with days and period, and the factor; an own
    factor, a thin basis, the mode off and a missing measurement are said in words."""
    from datetime import date
    rows = garmin()
    shown = info(rows, [rmr(MEASURED)], {"rmrCorrectionMode": "factor"})
    own = info(rows, [rmr(MEASURED)], {"rmrCorrectionMode": "factor", "rmrFactorOverride": 1.1})
    thin = info(garmin(start=date(2026, 11, 21)), [rmr(MEASURED)], {"rmrCorrectionMode": "factor"})
    off = info(rows, [rmr(MEASURED)], {})
    none = info(rows, [], {"rmrCorrectionMode": "factor"})
    given(shown=shown, own=own, thin=thin, off=off, none=none)
    assert shown == "Messung Mo., 23.11.2026: 2.390 kcal · Garmin im Mittel 2.139 kcal an 14 Tagen (10.11.–23.11.) · Faktor 1,117."
    assert own.endswith("· Faktor 1,117 · es gilt dein Faktor 1,100.")
    assert "Nur 3 vollständige Garmin-Tage vor der Messung" in thin
    assert off.endswith("Ausgeschaltet: alle Werte bleiben wie von Garmin.")
    assert none.startswith("Noch kein Ruheumsatz unter Befunde eingetragen")


def test_settings_form_has_the_energy_fields(given):
    """A select with off / factor / absolute and an optional factor; the form writes rmrCorrectionMode
    once chosen and rmrFactorOverride only when given, both in German and English."""
    select = re.search(r'<select id="set-rmr-mode">(.*?)</select>', HTML, re.S).group(1)
    values = re.findall(r'<option value="(\w+)"', select)
    form = re.search(r"  function formFields\(out\) \{.*?\n  \}", HTML, re.S).group(0)
    en = json.loads(re.search(r'<script type="application/json" id="i18n-en">(.*?)</script>', HTML, re.S).group(1))
    given(options=values)
    assert values == ["off", "factor", "absolute"] and 'id="set-rmr-factor"' in HTML
    assert "out.rmrCorrectionMode = mode" in form and "out.rmrFactorOverride = factor; else delete out.rmrFactorOverride" in form
    for de in ("Energieverbrauch", "Gemessener Ruheumsatz", "Aus: Garmins Ruheumsatz", "Faktor auf Garmins Ruheumsatz", "Gemessener Wert statt Garmins", "Eigener Faktor (optional)"):
        assert en.get(de), de


def test_a_changed_measurement_rebuilds_the_expenditure(given):
    """Entering, editing or confirming a Befund rebuilds the model when a correction is on, so every
    balance from the measurement date on uses the new value without reloading."""
    setter = re.search(r"  function setMeasurements\(rows\) \{.*?\n  \}", HTML, re.S).group(0)
    calls = HTML.count("setMeasurements(result.rows);")
    given(calls=calls)
    assert "rebuildModel()" in setter and calls == 3
    assert "state.measurements = parseMeasurements(result.rows)" not in HTML



def tef_info(settings, measured):
    return run(TEXT + ["tefInfoText"], f"tefInfoText(readEnergySettings({json.dumps(settings)}), {json.dumps(measured)})")


def test_macro_suggested_with_measurement(given):
    """With an RMR entered and TEF off, the settings suggest "Nach Makronährstoffen"; the texts name the
    coefficients or the flat share and the estimate for days without a complete log; the form writes
    tefMode, tefFlatPercent and only coefficients that differ from the default, in German and English."""
    suggest, plain = tef_info({}, True), tef_info({}, False)
    macro = tef_info({"tefMode": "macro", "tefCoefficients": {"protein": 0.22}}, True)
    flat = tef_info({"tefMode": "flat", "tefFlatPercent": 8}, False)
    form = re.search(r"  function formFields\(out\) \{.*?\n  \}", HTML, re.S).group(0)
    select = re.findall(r'<option value="(\w+)"', re.search(r'<select id="set-tef-mode">(.*?)</select>', HTML, re.S).group(1))
    en = json.loads(re.search(r'<script type="application/json" id="i18n-en">(.*?)</script>', HTML, re.S).group(1))
    given(suggest=suggest, macro=macro, flat=flat)
    assert suggest.startswith("Mit gemessenem Ruheumsatz empfohlen: „Nach Makronährstoffen“") and plain.startswith("Aus:")
    assert macro.startswith("Eiweiß 22 %, Kohlenhydrate 7,5 %, Fett 1,5 %, Alkohol 20 %") and "10 % des Mittels" in macro
    assert flat.startswith("8 % der geloggten Aufnahme") and "8 % des Mittels" in flat
    assert select == ["off", "flat", "macro"] and "out.tefMode = tefMode" in form and "v !== TEF_COEFFICIENTS[variant][n]" in form
    for de in ("Verdauung (thermischer Effekt)", "Pauschal, Anteil der Aufnahme", "Nach Makronährstoffen", "Anteile je Makronährstoff anpassen"):
        assert en.get(de), de


def breakdown(settings, measurement=True, rng=True):
    """energyBreakdown over 7 days with 460 active kcal and a log of 160/285/80 g each."""
    days = "[" + ",".join(f"{{t: isoToT('2026-11-{17 + i}'), kcalBurned: 2599, activeGarmin: 460, kcalIn: 2500, foodComplete: true, foodRaw: {{p: 160, c: 285, f: 80}}}}" for i in range(7)) + "]"
    ms = f"[{{kind: 'rmr_kcal', status: 'confirmed', t: isoToT('2026-11-01'), value: 2390, id: 'a', range95: {json.dumps([2110, 2670] if rng else None)}}}]" if measurement else "[]"
    return run(TEXT + ["mean", "energyBreakdown"],
               f"(() => {{ const days = {days}; const e = readEnergySettings({json.dumps(settings)}); applyEnergy(days, {ms}, e, isoToT('2026-11-25'), 1); return energyBreakdown(days, e); }})()")


def test_breakdown_text(given):
    """Measured 2,390, active 460, TEF 256 → 3,110 kcal, Garmin 2,600, range ±297; without TEF the part is left out."""
    full = breakdown({"rmrCorrectionMode": "absolute", "tefMode": "macro"})
    no_tef = breakdown({"rmrCorrectionMode": "absolute"}, rng=False)
    given(full=full, no_tef=no_tef)
    assert full == "3.110 kcal (Ruhe 2.390 · aktiv 460 · TEF 260) · Garmin: 2.600 · Spanne 2.810–3.400"
    assert no_tef == "2.850 kcal (Ruhe 2.390 · aktiv 460) · Garmin: 2.600 · Spanne 2.780–2.920"
    en = json.loads(re.search(r'<script type="application/json" id="i18n-en">(.*?)</script>', HTML, re.S).group(1))
    assert en["{0} kcal (Ruhe {1} · aktiv {2} · TEF {3}) · Garmin: {4} · Spanne {5}–{6}"] == "{0} kcal (resting {1} · active {2} · TEF {3}) · Garmin: {4} · range {5}–{6}"


def test_chart_marks_correction_start(given):
    """Both expenditure charts get a line on the day of each measurement in use, the calories chart the
    range as a band; with the mode off there is no line."""
    def marks(mode, factor):
        return run(["correctionMarks"], f"correctionMarks({{ energy: {{ rmrMode: '{mode}' }}, rmr: [{{ from: 1, factor: {json.dumps(factor)} }}] }})")
    on, off, no_factor, absolute = marks("factor", 1.117), marks("off", 1.117), marks("factor", None), marks("absolute", None)
    chart = re.search(r"  function timeChart\(host, o\) \{.*?\n  \}", HTML, re.S).group(0)
    given(on=on, off=off)
    assert on == [{"t": 1, "label": "Ruheumsatz gemessen"}] and off == [] and no_factor == [] and len(absolute) == 1
    assert "o.marks" in chart and "marks: startMarks," in HTML and "marks: correctionMarks(M)," in HTML
    assert "band: corrected ? days.map((d) => ({ t: d.t, lo: d.burnLow7, hi: d.burnHigh7 })) : null" in HTML


def test_breakdown_leaves_out_unfinished_days(given):
    """The breakdown averages the 7 days before today from the newest measurement in use on, without a
    day Garmin synced before it ended (resting kcal below 90 % of its 28-day median)."""
    rows = [{"t": f"isoToT('2026-11-{d:02d}')", "rest": 1275 if d == 24 else 2139} for d in range(1, 26)]
    days = "[" + ",".join(f"{{t: {r['t']}, restGarmin: {r['rest']}, kcalBurned: 1}}" for r in rows) + "]"
    expr = (f"(() => {{ const days = {days}; const p = [{{ from: isoToT('2026-11-21'), factor: 1.1 }}];"
            " return [breakdownDays(days, p, { rmrMode: 'factor' }, isoToT('2026-11-25')), breakdownDays(days, p, { rmrMode: 'off' }, isoToT('2026-11-25'))]"
            ".map((l) => l.map((d) => tToIso(d.t))); })()")
    with_rmr, without = run(["DAY", "isoToT", "tToIso", "breakdownDays"], expr)
    given(with_rmr=with_rmr, without=without)
    assert with_rmr == ["2026-11-21", "2026-11-22", "2026-11-23"]
    assert without == ["2026-11-18", "2026-11-19", "2026-11-20", "2026-11-21", "2026-11-22", "2026-11-23"]
    # A newer measurement without a factor is still the one in force: the breakdown starts at its date
    newer = run(["DAY", "isoToT", "tToIso", "breakdownDays"], expr.replace("const p = [{ from: isoToT('2026-11-21'), factor: 1.1 }];",
                "const p = [{ from: isoToT('2026-11-10'), factor: 1.1 }, { from: isoToT('2026-11-22'), factor: null }];"))[0]
    assert newer == ["2026-11-22", "2026-11-23"]


def test_correction_is_named_only_where_it_applies(given):
    """A factor-mode RMR without Garmin data before it has no factor: nothing is corrected, so nothing is called corrected."""
    def corrected(mode, factor, tef="off"):
        return run(["energyCorrected"], f"energyCorrected({{ rmrMode: '{mode}', tefMode: '{tef}', activeKcalFactor: 1 }}, [{{ factor: {json.dumps(factor)} }}])")
    cases = {"factor without factor": corrected("factor", None), "factor": corrected("factor", 1.117), "absolute": corrected("absolute", None),
             "off": corrected("off", 1.117), "tef only": corrected("off", None, "macro")}
    given(cases=cases)
    assert cases == {"factor without factor": False, "factor": True, "absolute": True, "off": False, "tef only": True}
