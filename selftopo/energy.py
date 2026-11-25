"""Energy expenditure from measured values, the same rules as the dashboard.

Garmin's expenditure is resting kcal (from its profile formula) plus active kcal. A resting metabolic
rate measured by indirect calorimetry (measurements.csv, kind rmr_kcal) replaces the resting part
from the day of the measurement until the next one; it never adds to it. Garmin's own columns stay
unchanged; the corrected values are added as new columns:

    resting_garmin   calories_total − calories_active, as Garmin has it
    resting_kcal     the resting kcal after the correction
    tef_kcal         thermic effect of food (tef_low, tef_high, tef_estimated), empty when off
    expenditure_kcal resting_kcal + calories_active + tef_kcal, what balances and recommendations use

settings.json: "rmrCorrectionMode" off | factor | absolute, "rmrFactorOverride", "tefMode" off |
flat | macro, "tefFlatPercent", "tefCoefficients", "tefCoefficientsLow", "tefCoefficientsHigh"
(every key optional; missing means off).
The formulas and their sources are in README.md, "Energy expenditure".
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

RMR_MODES = ("off", "factor", "absolute")
RMR_REF_DAYS = 14  # reference window up to and including the measurement date
RMR_REF_MIN_DAYS = 5  # fewer valid days: the factor is used, with a warning
# Thermic effect of food: share of each macronutrient's energy (Westerterp 2004); kcal per g 4/4/9/7
TEF_MODES = ("off", "flat", "macro")
TEF_KCAL_PER_G = {"protein": 4, "carbs": 4, "fat": 9, "alcohol": 7}
TEF_COEFFICIENTS = {
    "mid": {"protein": 0.25, "carbs": 0.075, "fat": 0.015, "alcohol": 0.2},
    "low": {"protein": 0.2, "carbs": 0.05, "fat": 0.0, "alcohol": 0.1},
    "high": {"protein": 0.3, "carbs": 0.1, "fat": 0.03, "alcohol": 0.3},
}
TEF_FLAT_PERCENT = 10.0
TEF_FALLBACK_DAYS = 14  # a day without a complete log: flat % of the mean intake of these days
MIN_COMPLETE_KCAL = 1200  # same as analyze.MIN_COMPLETE_KCAL and the dashboard


@dataclass
class Settings:
    rmr_mode: str = "off"
    rmr_factor_override: float | None = None
    tef_mode: str = "off"
    tef_flat_percent: float = TEF_FLAT_PERCENT
    tef: dict[str, dict[str, float]] = field(default_factory=lambda: {k: dict(v) for k, v in TEF_COEFFICIENTS.items()})


def read_settings(settings: dict[str, Any], problems: list[str] | None = None) -> Settings:
    """The energy keys of settings.json; a missing or invalid key means off."""
    problems = problems if problems is not None else []
    out = Settings()
    mode = settings.get("rmrCorrectionMode")
    if mode is not None:
        if mode in RMR_MODES:
            out.rmr_mode = mode
        else:
            problems.append(f'"rmrCorrectionMode" must be off, factor or absolute, not {mode!r}')
    factor = settings.get("rmrFactorOverride")
    if factor is not None and factor != "":
        try:
            value = float(factor)
        except (TypeError, ValueError):
            value = float("nan")
        if np.isfinite(value) and 0.5 <= value <= 2:
            out.rmr_factor_override = value
        else:
            problems.append(f'"rmrFactorOverride" must be a number between 0.5 and 2, not {factor!r}')
    mode = settings.get("tefMode")
    if mode is not None:
        if mode in TEF_MODES:
            out.tef_mode = mode
        else:
            problems.append(f'"tefMode" must be off, flat or macro, not {mode!r}')
    flat = settings.get("tefFlatPercent")
    if flat is not None and flat != "":
        value = _number(flat) if not isinstance(flat, bool) else None
        if value is not None and 0 <= value <= 25:
            out.tef_flat_percent = value
        else:
            problems.append(f'"tefFlatPercent" must be a number between 0 and 25, not {flat!r}')
    for variant, key in (("mid", "tefCoefficients"), ("low", "tefCoefficientsLow"), ("high", "tefCoefficientsHigh")):
        given = settings.get(key)
        if given is not None and not isinstance(given, dict):
            problems.append(f'"{key}" must be an object like {{"protein": 0.25}}')
            continue
        for name, raw in (given or {}).items():
            value = _number(raw) if not isinstance(raw, bool) else None
            if name in out.tef[variant] and value is not None and 0 <= value <= 0.5:
                out.tef[variant][name] = value
            else:
                problems.append(f'"{key}.{name}" must be a share between 0 and 0.5, not {raw!r}')
    return out


def _number(text: Any) -> float | None:
    try:
        value = float(str(text).strip().replace(",", "."))
    except ValueError:
        return None
    return value if np.isfinite(value) else None


def read_measurements(path: Path) -> list[dict[str, Any]]:
    """Confirmed RMR measurements: {"date", "rmr", "range95", "range99"}, oldest first, one per day."""
    if not path.exists():
        return []
    by_day: dict[date, dict[str, Any]] = {}
    try:
        with path.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                if (row.get("kind") or "").strip() != "rmr_kcal" or row.get("status") == "proposed":
                    continue
                value = _number(row.get("value"))
                try:
                    day = date.fromisoformat((row.get("date") or "")[:10])
                except ValueError:
                    continue
                if value is None:
                    continue
                by_day[day] = {"date": day, "rmr": value,
                               "range95": _range(row.get("range95_low"), row.get("range95_high"), value),
                               "range99": _range(row.get("range99_low"), row.get("range99_high"), value)}
    except (OSError, csv.Error) as exc:
        log.warning("energy: %s unreadable (%s)", path, exc)
        return []
    return [by_day[d] for d in sorted(by_day)]


def _range(low: Any, high: Any, value: float) -> tuple[float, float] | None:
    lo, hi = _number(low), _number(high)
    return (lo, hi) if lo is not None and hi is not None and lo <= value <= hi else None


def reference(resting: pd.Series, day: date, today: date) -> dict[str, Any] | None:
    """Garmin's mean resting kcal on the 14 days up to and including `day`: without today, without
    missing days and without days below half the window's median (a sync in the middle of a day)."""
    start, end = pd.Timestamp(day - timedelta(days=RMR_REF_DAYS - 1)), pd.Timestamp(day)
    window = resting.loc[start:end]
    window = window[(window.index < pd.Timestamp(today)) & (window > 0)].dropna()
    if window.empty:
        return None
    valid = window[window >= window.median() / 2]
    return {"kcal": float(valid.mean()), "n": len(valid), "from": valid.index[0].date(), "to": valid.index[-1].date(),
            "warn": len(valid) < RMR_REF_MIN_DAYS}


def periods(measurements: list[dict[str, Any]], resting: pd.Series, today: date,
            override: float | None = None) -> list[dict[str, Any]]:
    """One period per measurement, from its date until the day before the next one."""
    out = []
    for i, m in enumerate(measurements):
        ref = reference(resting, m["date"], today)
        measured = round(m["rmr"] / ref["kcal"], 3) if ref else None
        nxt = measurements[i + 1]["date"] - timedelta(days=1) if i + 1 < len(measurements) else None
        out.append({**m, "from": m["date"], "to": nxt, "ref": ref, "measured_factor": measured,
                    "factor": override if override is not None else measured})
    return out


def apply(days: pd.DataFrame, measurements: list[dict[str, Any]], energy: Settings, today: date,
          day_fraction: float = 1.0) -> list[dict[str, Any]]:
    """Adds resting_garmin, resting_kcal and expenditure_kcal to `days` (one row per calendar day,
    with calories_total and calories_active). Returns the periods."""
    nan = pd.Series(np.nan, index=days.index)
    total = pd.to_numeric(days["calories_total"], errors="coerce").astype(float) if "calories_total" in days else nan
    active = pd.to_numeric(days["calories_active"], errors="coerce").astype(float) if "calories_active" in days else nan
    garmin = total - active
    days["resting_garmin"] = garmin
    days["resting_kcal"] = garmin
    days["expenditure_kcal"] = total
    found = periods(measurements, garmin, today, energy.rmr_factor_override)
    for p in found if energy.rmr_mode != "off" else []:
        start = pd.Timestamp(p["from"])
        end = pd.Timestamp(p["to"]) if p["to"] else days.index.max()
        rows = days.index[(days.index >= start) & (days.index <= end) & garmin.notna()]
        if energy.rmr_mode == "factor":
            if p["factor"] is None:
                continue
            resting = garmin[rows] * p["factor"]
        else:
            resting = pd.Series(p["rmr"], index=rows, dtype=float)
            if pd.Timestamp(today) in resting.index:
                resting[pd.Timestamp(today)] = p["rmr"] * day_fraction
        days.loc[rows, "resting_kcal"] = resting
        days.loc[rows, "expenditure_kcal"] = resting + active[rows]
    _add_tef(days, energy, today)
    return found


def _col(days: pd.DataFrame, name: str) -> pd.Series:
    if name not in days:
        return pd.Series(np.nan, index=days.index)
    return pd.to_numeric(days[name], errors="coerce").astype(float)


def _add_tef(days: pd.DataFrame, energy: Settings, today: date) -> None:
    """Thermic effect of food, added once to expenditure_kcal where Garmin has the day. A complete
    log (intake_kcal ≥ 1,200) counts as logged, the running day what is logged so far; any other
    day gets the flat share of the mean intake of the complete days among the 14 before it."""
    for name in ("tef_kcal", "tef_low", "tef_high"):
        days[name] = np.nan
    days["tef_estimated"] = False
    if energy.tef_mode == "off":
        return
    kcal = _col(days, "intake_kcal")
    grams = {k: _col(days, f"intake_{k}_g") for k in TEF_KCAL_PER_G}
    grams["alcohol"] = grams["alcohol"].fillna(0)
    complete = (kcal >= MIN_COMPLETE_KCAL) & (days.index < pd.Timestamp(today))
    today_ts = pd.Timestamp(today)
    pct = energy.tef_flat_percent / 100
    for ts in days.index[days["expenditure_kcal"].notna()]:
        logged = bool(complete.get(ts)) or (ts == today_ts and pd.notna(kcal.get(ts)))
        if logged:
            if energy.tef_mode == "macro" and all(pd.notna(grams[k].get(ts)) for k in ("protein", "carbs", "fat")):
                e = {k: grams[k][ts] * TEF_KCAL_PER_G[k] for k in TEF_KCAL_PER_G}
                mid, low, high = (sum(e[k] * energy.tef[v][k] for k in e) for v in ("mid", "low", "high"))
            else:
                mid, low, high = kcal[ts] * pct, kcal[ts] * pct / 2, kcal[ts] * pct * 1.5
            estimated = False
        else:
            window = kcal[complete & (days.index < ts) & (days.index >= ts - pd.Timedelta(days=TEF_FALLBACK_DAYS))]
            if window.empty:
                continue
            base = float(window.mean())
            mid, low, high = base * pct, base * pct / 2, base * pct * 1.5
            estimated = True
        days.loc[ts, ["tef_kcal", "tef_low", "tef_high"]] = [mid, low, high]
        days.loc[ts, "tef_estimated"] = estimated
    days["expenditure_kcal"] = days["expenditure_kcal"] + days["tef_kcal"].fillna(0)
