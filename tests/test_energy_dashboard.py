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
