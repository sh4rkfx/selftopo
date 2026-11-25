"""Energy expenditure from measured values, the same rules as the dashboard.

Garmin's expenditure is resting kcal (from its profile formula) plus active kcal. A resting metabolic
rate measured by indirect calorimetry (measurements.csv, kind rmr_kcal) replaces the resting part
from the day of the measurement until the next one; it never adds to it. Garmin's own columns stay
unchanged; the corrected values are added as new columns:

    resting_garmin   calories_total − calories_active, as Garmin has it
    resting_kcal     the resting kcal after the correction
    expenditure_kcal resting_kcal + calories_active, what balances and recommendations use

settings.json: "rmrCorrectionMode" off | factor | absolute (missing = off), "rmrFactorOverride".
The formulas and their sources are in README.md, "Energy expenditure".
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

RMR_MODES = ("off", "factor", "absolute")
RMR_REF_DAYS = 14  # reference window up to and including the measurement date
RMR_REF_MIN_DAYS = 5  # fewer valid days: the factor is used, with a warning


@dataclass
class Settings:
    rmr_mode: str = "off"
    rmr_factor_override: float | None = None


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
    if energy.rmr_mode == "off":
        return found
    for p in found:
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
    return found
