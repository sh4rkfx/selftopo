"""Time-lagged relationships between training, behaviour and recovery.

Builds one row per calendar day from the three CSV files and tests a fixed set of
driver -> outcome pairs, for example "training load on day D" against "HRV in the
night after D". Method, chosen to avoid the usual traps of self-tracking data:

* Detrending: every value is compared with its own trailing 28-day mean, so two
  metrics that merely drift over months (weight and HRV during a cut) do not look
  related.
* Spearman rank correlation, robust against outliers such as a single 2,000 m tour.
* Effect size as a Theil-Sen slope in real units ("-2.1 ms HRV per 100 load points").
* Benjamini-Hochberg correction across all tested pairs: with 80 tests, a few would
  look significant by chance alone.
* Pairs where Garmin computes the outcome from the driver (readiness from sleep and
  HRV, Body Battery from sleep and stress) are not tested, because they are circular.

The result is written to data/insights.json for the dashboard and for a written
interpretation. It describes association in your own data, not causation.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from . import config

log = logging.getLogger(__name__)

BASELINE_DAYS = 28  # trailing window that defines "normal" for each metric
BASELINE_MIN_DAYS = 7  # values needed in that window before a deviation is computed
MIN_PAIRS = 20  # days with both values needed before a pair is tested
FDR_Q = 0.10  # share of false discoveries accepted among "robust" findings
TENDENCY_P = 0.05  # uncorrected p below this, but not robust: reported as a tendency
MIN_FORM_WEIGHT_KG = 20  # exercises lighter than this are too noisy for e1RM changes
HARD_SET_TYPES = {"normal", "failure", "dropset"}
# YAZIO days below this are treated as not fully logged and left out, like the dashboard does.
MIN_COMPLETE_KCAL = 1200


@dataclass(frozen=True)
class Variable:
    key: str
    label: str
    unit: str
    step: float  # effects are reported per this change of the driver
    step_label: str
    detrend: bool = True


VARIABLES = {v.key: v for v in [
    Variable("training_load", "Training load, all activities (Garmin)", "points", 100, "100 points"),
    Variable("active_min", "Active time (Garmin)", "min", 60, "1 hour"),
    Variable("steps", "Steps", "steps", 1000, "1,000 steps"),
    Variable("hard_sets", "Hard sets (Hevy)", "sets", 10, "10 sets"),
    Variable("tonnage_t", "Tonnage (Hevy)", "t", 1, "1 t"),
    Variable("stress_avg", "Average stress", "points", 10, "10 points"),
    Variable("bedtime_min", "Bedtime", "min", 60, "1 hour later"),
    Variable("sleep_hours", "Sleep duration", "h", 1, "1 hour"),
    Variable("sleep_score", "Sleep score", "points", 10, "10 points"),
    Variable("hrv", "Overnight HRV", "ms", 10, "10 ms"),
    Variable("resting_hr", "Resting heart rate", "bpm", 5, "5 bpm"),
    Variable("readiness", "Training readiness", "points", 10, "10 points"),
    Variable("body_battery", "Body Battery at wake-up", "points", 10, "10 points"),
    Variable("calories_kcal", "Energy intake (YAZIO)", "kcal", 500, "500 kcal"),
    Variable("protein_g", "Protein intake (YAZIO)", "g", 50, "50 g"),
    Variable("carbs_g", "Carbohydrate intake (YAZIO)", "g", 100, "100 g"),
    Variable("fat_g", "Fat intake (YAZIO)", "g", 30, "30 g"),
    Variable("strength_form_pct", "Strength form (e1RM vs. best of prior 28 days)", "%", 1, "1 %",
             detrend=False),
]}

DAY_DRIVERS = ["training_load", "active_min", "steps", "hard_sets", "tonnage_t", "stress_avg"]
NIGHT_OUTCOMES = ["hrv", "resting_hr", "sleep_score", "sleep_hours", "readiness", "body_battery"]
# Intake of day D against the night after D only; a second night would add many tests for little.
NUTRITION_DRIVERS = ["calories_kcal", "protein_g", "carbs_g", "fat_g"]
# Garmin derives these outcomes from the listed inputs, so testing the pair is circular.
DERIVED_FROM = {
    "readiness": {"sleep_score", "sleep_hours", "hrv"},
    "body_battery": {"sleep_score", "sleep_hours", "hrv", "stress_avg"},
}
TIMING_LABELS = {
    "same_night": "same night",
    "next_night": "following night",
    "second_night": "second night after",
    "same_day": "same day",
    "next_day": "following day",
}


def candidate_pairs() -> list[tuple[str, str, int]]:
    """(driver, outcome, lag in days). Garmin's overnight values on date D describe the night before D."""
    pairs = [(d, o, lag) for d in DAY_DRIVERS for o in NIGHT_OUTCOMES for lag in (1, 2)]
    pairs += [(d, o, 0) for d in ("bedtime_min", "sleep_hours") for o in ("hrv", "resting_hr", "readiness")]
    pairs += [(d, "strength_form_pct", 0)
              for d in ("bedtime_min", "sleep_hours", "sleep_score", "hrv", "resting_hr", "readiness")]
    pairs += [(d, o, 1) for d in NUTRITION_DRIVERS for o in NIGHT_OUTCOMES]
    pairs += [(d, "strength_form_pct", 1) for d in ("calories_kcal", "carbs_g")]  # eaten the day before training
    return [p for p in pairs if p[0] not in DERIVED_FROM.get(p[1], set())]


def timing(outcome: str, lag: int) -> str:
    if outcome == "strength_form_pct":
        return "next_day" if lag else "same_day"
    return {0: "same_night", 1: "next_night", 2: "second_night"}[lag]


# --------------------------------------------------------------------------- daily table


def _read(path) -> pd.DataFrame:
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def _column(frame: pd.DataFrame, name: str) -> pd.Series:
    if name in frame:
        return pd.to_numeric(frame[name], errors="coerce")
    return pd.Series(np.nan, index=frame.index, dtype=float)


def _minutes_from_midnight(index: pd.DatetimeIndex, stamps: pd.Series) -> pd.Series:
    """Bedtime as minutes relative to midnight of the wake-up date (23:30 the evening before = -30)."""
    start = pd.to_datetime(stamps, format="%Y-%m-%d %H:%M", errors="coerce")
    minutes = (start - pd.Series(index, index=index)).dt.total_seconds() / 60
    return minutes.where(minutes.between(-360, 360))


def _strength_form(hard: pd.DataFrame) -> pd.Series:
    """Per day: mean change of each exercise's best e1RM against its best of the prior 28 days, in %."""
    sets = hard[hard["reps"].between(1, 10) & (hard["weight_kg"] > 0)].copy()
    if sets.empty:
        return pd.Series(dtype=float)
    sets["e1rm"] = sets["weight_kg"] * (1 + sets["reps"] / 30)  # Epley
    typical = sets.groupby("exercise")["weight_kg"].median()
    sets = sets[sets["exercise"].map(typical) >= MIN_FORM_WEIGHT_KG]
    changes = []
    for _, group in sets.groupby("exercise"):
        best = group.groupby("date")["e1rm"].max().sort_index()
        prior = best.rolling(f"{BASELINE_DAYS}D", closed="left").max()
        changes.append(((best / prior - 1) * 100).dropna())
    if not changes:
        return pd.Series(dtype=float)
    return pd.concat(changes).groupby(level=0).mean()


def load_daily() -> pd.DataFrame:
    """One row per calendar day with every variable in VARIABLES that the data provides."""
    garmin = _read(config.GARMIN_CSV)
    activities = _read(config.ACTIVITIES_CSV)
    sets = _read(config.HEVY_CSV)
    food = _read(config.NUTRITION_CSV)

    dates = [pd.to_datetime(f["date"]) for f in (garmin, activities, sets) if "date" in f and len(f)]
    if not dates:
        return pd.DataFrame()
    all_dates = pd.concat(dates)
    index = pd.date_range(all_dates.min(), all_dates.max(), freq="D")
    daily = pd.DataFrame(index=index)

    if len(garmin):
        g = garmin.assign(date=pd.to_datetime(garmin["date"])).drop_duplicates("date", keep="last")
        g = g.set_index("date").reindex(index)
        daily["hrv"] = _column(g, "hrv_last_night_ms")
        daily["resting_hr"] = _column(g, "resting_hr")
        daily["sleep_score"] = _column(g, "sleep_score")
        daily["sleep_hours"] = _column(g, "sleep_hours")
        daily["readiness"] = _column(g, "readiness_score")
        daily["body_battery"] = _column(g, "body_battery_wake").fillna(_column(g, "body_battery_high"))
        daily["stress_avg"] = _column(g, "stress_avg")
        daily["steps"] = _column(g, "steps")
        if "sleep_start_local" in g:
            daily["bedtime_min"] = _minutes_from_midnight(index, g["sleep_start_local"])

    # Days without an activity or a workout count as zero load once the source has data.
    if len(activities):
        a = activities.assign(date=pd.to_datetime(activities["date"]))
        a["training_load"] = _column(a, "training_load")
        a["active_min"] = _column(a, "duration_min")
        per_day = a.groupby("date")[["training_load", "active_min"]].sum()
        covered = index >= a["date"].min()
        for name in per_day:
            daily[name] = per_day[name].reindex(index).fillna(0).where(covered)

    if len(sets):
        s = sets.assign(date=pd.to_datetime(sets["date"]))
        grip = {name.casefold() for name in config.GRIP_EXERCISES}
        s = s[~s["exercise"].fillna("").astype(str).str.strip().str.casefold().isin(grip)]
        s["set_type"] = s["set_type"].fillna("normal").astype(str).str.lower()
        s["weight_kg"] = _column(s, "weight_kg").fillna(0)
        s["reps"] = _column(s, "reps")
        hard = s[s["set_type"].isin(HARD_SET_TYPES)].copy()
        hard["volume_t"] = hard["weight_kg"] * hard["reps"].fillna(0) / 1000
        per_day = hard.groupby("date").agg(hard_sets=("set_type", "size"), tonnage_t=("volume_t", "sum"))
        covered = index >= s["date"].min()
        for name in per_day:
            daily[name] = per_day[name].reindex(index).fillna(0).where(covered)
        daily["strength_form_pct"] = _strength_form(hard).reindex(index)

    # Unlogged days stay empty (not 0): a missing YAZIO day says nothing about intake.
    if len(food):
        f = food.assign(date=pd.to_datetime(food["date"])).drop_duplicates("date", keep="last")
        f = f.set_index("date").reindex(index)
        complete = _column(f, "calories_kcal") >= MIN_COMPLETE_KCAL
        for name in NUTRITION_DRIVERS:
            daily[name] = _column(f, name).where(complete)

    return daily


# --------------------------------------------------------------------------- analysis


def deviation(series: pd.Series, detrend: bool = True) -> pd.Series:
    """Difference to the trailing mean of the days before (the day itself is not part of its baseline)."""
    if not detrend:
        return series
    baseline = series.rolling(BASELINE_DAYS, min_periods=BASELINE_MIN_DAYS).mean().shift(1)
    return series - baseline


def _status(p: float, q: float) -> str:
    if q < FDR_Q:
        return "robust"
    return "tendency" if p < TENDENCY_P else "none"


def analyze_frame(daily: pd.DataFrame, days: int | None = None) -> dict[str, Any]:
    """Test all candidate pairs on the last `days` days (deviations use the full history)."""
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if daily.empty:
        return {"generated_at": generated, "period": None, "tested": 0, "robust": 0, "findings": [],
                "note": "No data yet. Run python -m selftopo sync first."}

    end = daily.index.max()
    start = max(daily.index.min(), end - pd.Timedelta(days=days - 1)) if days else daily.index.min()
    in_window = daily.index >= start
    present = [key for key in VARIABLES if key in daily]
    dev = {key: deviation(daily[key], VARIABLES[key].detrend) for key in present}

    findings, skipped = [], 0
    for driver, outcome, lag in candidate_pairs():
        if driver not in dev or outcome not in dev:
            continue
        pair = pd.DataFrame({"x": dev[driver], "y": dev[outcome].shift(-lag)})[in_window].dropna()
        if len(pair) < MIN_PAIRS or pair["x"].nunique() < 3 or pair["y"].nunique() < 3:
            skipped += 1
            continue
        rho, p = stats.spearmanr(pair["x"], pair["y"])
        slope = stats.theilslopes(pair["y"], pair["x"]).slope
        d, o = VARIABLES[driver], VARIABLES[outcome]
        findings.append({
            "driver": driver, "driver_label": d.label,
            "outcome": outcome, "outcome_label": o.label,
            "lag_days": lag, "timing": timing(outcome, lag),
            "n": int(len(pair)), "rho": float(rho), "p": float(p),
            "effect": float(slope * d.step), "effect_unit": o.unit, "effect_per": d.step_label,
        })

    if findings:
        qs = stats.false_discovery_control([f["p"] for f in findings], method="bh")
        for f, q in zip(findings, qs, strict=True):
            f["q"] = float(q)
            f["status"] = _status(f["p"], f["q"])
    order = {"robust": 0, "tendency": 1, "none": 2}
    findings.sort(key=lambda f: (order[f["status"]], f["q"], -abs(f["rho"])))

    return _clean({
        "generated_at": generated,
        "period": {"start": start.date().isoformat(), "end": end.date().isoformat(),
                   "days": int((end - start).days + 1)},
        "method": {
            "correlation": "Spearman rank correlation of deviations from each metric's trailing "
                           f"{BASELINE_DAYS}-day mean",
            "effect": "Theil-Sen slope, outcome change per step of the driver",
            "multiple_testing": f"Benjamini-Hochberg; robust means q < {FDR_Q}, tendency means p < {TENDENCY_P}",
            "min_days_per_pair": MIN_PAIRS,
        },
        "coverage": {key: int(daily.loc[in_window, key].notna().sum()) for key in present},
        "tested": len(findings),
        "skipped_too_few_days": skipped,
        "robust": sum(f["status"] == "robust" for f in findings),
        "findings": findings,
    })


def _clean(value: Any) -> Any:
    """Round floats and replace NaN/inf with None, so the file is valid JSON for browsers."""
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, float):
        return round(value, 4) if math.isfinite(value) else None
    return value


def describe(finding: dict[str, Any]) -> str:
    unit = finding["effect_unit"]
    return (f"{finding['driver_label']} -> {finding['outcome_label']} ({TIMING_LABELS[finding['timing']]}): "
            f"{finding['effect']:+.1f} {unit} per {finding['effect_per']}, "
            f"rho {finding['rho']:+.2f}, n {finding['n']}, q {finding['q']:.3f}")


def run(days: int | None = 180) -> dict[str, Any]:
    result = analyze_frame(load_daily(), days)
    config.INSIGHTS_JSON.parent.mkdir(parents=True, exist_ok=True)
    tmp = config.INSIGHTS_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(config.INSIGHTS_JSON)
    log.info("Analysis: %d pairs tested, %d robust -> %s", result["tested"], result["robust"], config.INSIGHTS_JSON)
    return result
