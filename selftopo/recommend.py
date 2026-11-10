"""Recommendations toward your own goals, written to data/recommendations.json.

Reads the CSV files, insights.json and the goals in settings.json, evaluates a fixed set of rules
and writes what the dashboard shows in its area "Empfehlungen" and in the Today card. Each rule
has a trigger, an action, its evidence, a measurement and a safety filter; without a trigger in
the data a rule stays silent. The rules, thresholds and sources are listed in RULES and in
docs/recommendations.md. Rules that only rest on a relationship in your own data are offered as
an experiment, never as a fact.

Texts are German templates with {0}, {1}, ... placeholders; the dashboard translates them with
its dictionary and formats the values. A value is a number {"n": x, "d": decimals}, a date
{"date": "YYYY-MM-DD"}, a clock time {"clock": "HH:MM"}, a Hevy muscle group {"muscle": "chest"}, a
text to translate {"t": "..."}, a list {"list": [...]} or a plain string.

selftopo is not a medical device. The rules are suggestions for healthy adults; values that
could be medically relevant only lead to the advice to have them checked.
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

from . import analyze, config

log = logging.getLogger(__name__)

SCHEMA = 1
MAX_LEVERS = 3  # cards shown in the area; the rest is one level deeper
HIDE_DAYS = 14  # "later" hides a recommendation this long
EXPERIMENT_DAYS = 14
EXPERIMENT_MIN_DAYS = 10  # per phase; fewer gives no result, only "too little data"
KCAL_PER_KG = 7700  # energy in one kg of body weight change, the usual approximation
MAX_LOSS_PCT_PER_WEEK = 1.0  # safety: never suggest a faster pace
MIN_BMI = 20.0  # safety: no weight-loss advice below this BMI or towards a goal below it

# --------------------------------------------------------------------------- goals

# One goal per area. Each goal names its metric and a target; "by" is optional (a date).
GOAL_METRICS = {
    "koerper": {"weight": "kg"},
    "erholung": {"resting_hr": "bpm", "hrv": "range"},
    "schlaf": {"sleep_hours": "h", "bedtime": "clock"},
    "kraft": {"weekly_sets": "sets"},
    "fitness": {"vo2max": "ml/kg/min"},
    "aktivitaeten": {"steps": "steps", "active_minutes": "min/week"},
}
# Direction in which a metric gets better
BETTER = {"weight": -1, "resting_hr": -1, "hrv": 1, "sleep_hours": 1, "bedtime": -1, "weekly_sets": 1,
          "vo2max": 1, "steps": 1, "active_minutes": 1, "sleep_score": 1}


@dataclass
class Goal:
    area: str
    metric: str
    target: float | str | None
    by: date | None = None


def parse_goals(settings: dict[str, Any], problems: list[str] | None = None) -> dict[str, Goal]:
    """Goals from settings.json: {"goals": {"koerper": {"metric": "weight", "target": 75, "by": "2027-03-31"}}}.

    Invalid entries are reported in `problems` and left out, so one typo never blocks the rest.
    """
    problems = problems if problems is not None else config.SETTINGS_PROBLEMS
    raw = settings.get("goals") or {}
    if not isinstance(raw, dict):
        problems.append('"goals" in settings.json must be an object, one goal per area')
        return {}
    goals = {}
    for area, entry in raw.items():
        metrics = GOAL_METRICS.get(area)
        if metrics is None:
            problems.append(f'goals: unknown area "{area}" (known: {", ".join(GOAL_METRICS)})')
            continue
        if not isinstance(entry, dict) or entry.get("metric") not in metrics:
            problems.append(f'goals.{area}: "metric" must be one of {", ".join(metrics)}')
            continue
        metric, target = entry["metric"], entry.get("target")
        if metric == "hrv":
            target = "range"
        elif metric == "bedtime":
            if not (isinstance(target, str) and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", target)):
                problems.append(f'goals.{area}: "target" must be a time like "23:00"')
                continue
        elif not isinstance(target, (int, float)) or isinstance(target, bool) or target <= 0:
            problems.append(f'goals.{area}: "target" must be a positive number')
            continue
        by = None
        if entry.get("by") not in (None, ""):
            try:
                by = date.fromisoformat(str(entry["by"]))
            except ValueError:
                problems.append(f'goals.{area}: "by" must be a date like "2027-03-31"')
        goals[area] = Goal(area, metric, target, by)
    return goals


# --------------------------------------------------------------------------- sources and rules

SOURCES = {
    "manresa2021": ("Manresa-Rocamora 2021", "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8507742/"),
    "dueking2021": ("Düking 2021", "https://pubmed.ncbi.nlm.nih.gov/34489178/"),
    "stutz2019": ("Stutz 2019", "https://pubmed.ncbi.nlm.nih.gov/30374942/"),
    "garthe2011": ("Garthe 2011", "https://lida.sport-iat.de/ta/Record/4020442?lng=en"),
    "morton2018": ("Morton 2018", "https://pubmed.ncbi.nlm.nih.gov/28698222/"),
    "reimers2018": ("Reimers 2018", "https://www.mdpi.com/2077-0383/7/12/503/htm"),
    "pietila2018": ("Pietilä 2018", "https://pubmed.ncbi.nlm.nih.gov/29549064/"),
    "watson2015": ("Watson 2015", "https://pmc.ncbi.nlm.nih.gov/articles/PMC4434546/"),
    "windred2024": ("Windred 2024", "https://www.broadinstitute.org/publications/broad1346196"),
    "drake2013": ("Drake 2013", "https://pmc.ncbi.nlm.nih.gov/articles/PMC3805807/"),
    "paluch2022": ("Paluch 2022", "https://ora.ox.ac.uk/objects/uuid:c77d223f-33ce-4d5c-9124-a00e5a43fcc1"),
    "esc2024": ("ESC 2024", "https://escardio.org/Congresses-Events/ESC-Congress/Congress-news/"
                            "2024-esc-clinical-practice-guidelines-for-the-management-of-elevated-blood-press"),
    "schoenfeld2017": ("Schoenfeld 2017", "https://doi.org/10.1080/02640414.2016.1210197"),
    "schoenfeld2019": ("Schoenfeld 2019", "https://doi.org/10.1080/02640414.2018.1555906"),
    "milanovic2015": ("Milanović 2015", "https://doi.org/10.1007/s40279-015-0365-0"),
    "bull2020": ("Bull 2020", "https://doi.org/10.1136/bjsports-2020-102955"),
    "cornelissen2013": ("Cornelissen 2013", "https://pubmed.ncbi.nlm.nih.gov/23525435/"),
    "he2013": ("He 2013", "https://doi.org/10.1136/bmj.f1325"),
    "neter2003": ("Neter 2003", "https://doi.org/10.1161/01.HYP.0000094221.86888.AE"),
    "zheng2015": ("Zheng 2015", "https://pubmed.ncbi.nlm.nih.gov/25521523/"),
    "madigan2015": ("Madigan 2015", "https://pubmed.ncbi.nlm.nih.gov/26293454/"),
}


@dataclass(frozen=True)
class Rule:
    id: str
    number: int  # as in the concept's rule catalogue
    kind: str  # "today", "safety", "lever" or "experiment"
    evidence: str  # "B", "C", "guideline" or "data" (data quality)
    areas: tuple[str, ...]  # goal areas that switch the rule on; empty: always on
    sources: tuple[str, ...] = ()
    effort: int = 2  # 1 small, 2 medium, 3 large; orders levers of the same evidence


RULES = {r.id: r for r in [
    Rule("today", 1, "today", "B", (), ("manresa2021", "dueking2021")),
    Rule("late-training", 2, "lever", "B", ("schlaf",), ("stutz2019",), 1),
    Rule("weight-pace", 3, "lever", "B", ("koerper",), ("garthe2011",), 2),
    Rule("protein", 4, "lever", "B", ("koerper", "kraft"), ("morton2018",), 1),
    Rule("food-logging", 5, "lever", "data", ("koerper",), (), 1),
    Rule("endurance", 6, "lever", "B", ("erholung",), ("reimers2018",), 3),
    Rule("alcohol", 7, "experiment", "B", ("erholung", "schlaf"), ("pietila2018",), 2),
    Rule("sleep-duration", 8, "lever", "B", ("schlaf", "erholung"), ("watson2015",), 2),
    Rule("sleep-regularity", 9, "lever", "B", ("schlaf",), ("windred2024",), 2),
    Rule("bedtime-hrv", 10, "experiment", "C", ("erholung", "schlaf"), (), 2),
    Rule("caffeine", 11, "lever", "B", ("schlaf",), ("drake2013",), 1),
    Rule("steps", 12, "lever", "B", ("aktivitaeten", "koerper"), ("paluch2022",), 1),
    Rule("own-data", 13, "experiment", "C", ("erholung", "schlaf"), (), 2),
    Rule("blood-pressure-high", 14, "safety", "guideline", (), ("esc2024",)),
    Rule("training-volume", 15, "lever", "B", ("kraft",), ("schoenfeld2017", "schoenfeld2019"), 2),
    Rule("intervals", 16, "lever", "B", ("fitness",), ("milanovic2015",), 2),
    Rule("activity-minutes", 17, "lever", "guideline", ("aktivitaeten", "erholung", "fitness"), ("bull2020",), 2),
    # Rule 18 (load spikes) is left out on purpose: the acute:chronic ratio is disputed.
    Rule("blood-pressure-elevated", 19, "lever", "B", (), ("cornelissen2013", "he2013", "neter2003"), 3),
    Rule("late-meal", 20, "experiment", "C", ("schlaf",), (), 2),
    Rule("weighing", 21, "lever", "data", ("koerper",), ("zheng2015", "madigan2015"), 1),
]}
EVIDENCE_ORDER = {"guideline": 0, "B": 1, "data": 2, "C": 3}


def n(value: float, decimals: int = 0) -> dict[str, Any]:
    return {"n": round(float(value), decimals), "d": decimals}


def text(template: str, *values: Any) -> dict[str, Any]:
    return {"text": template, "vars": list(values)}


@dataclass
class Card:
    rule: str
    title: dict[str, Any]
    why: dict[str, Any]
    measure: dict[str, Any]
    current: dict[str, Any] | None = None  # value of the measurement now
    experiment: dict[str, Any] | None = None  # {"days": 14, "metrics": [...], "action": text}
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        rule = RULES[self.rule]
        return {
            "rule": rule.id, "number": rule.number, "kind": rule.kind, "evidence": rule.evidence,
            "areas": list(rule.areas), "sources": list(rule.sources),
            "title": self.title, "why": self.why, "measure": self.measure, "current": self.current,
            "experiment": self.experiment, **self.extra,
        }


# --------------------------------------------------------------------------- data


def _read(path) -> pd.DataFrame:
    try:
        return pd.read_csv(path) if path.exists() else pd.DataFrame()
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        log.warning("recommend: %s unreadable (%s)", path, exc)
        return pd.DataFrame()


def _num(frame: pd.DataFrame, name: str) -> pd.Series:
    if name in frame:
        return pd.to_numeric(frame[name], errors="coerce")
    return pd.Series(np.nan, index=frame.index, dtype=float)


@dataclass
class Data:
    today: date
    days: pd.DataFrame  # one row per calendar day up to today
    activities: pd.DataFrame
    sets: pd.DataFrame  # hard sets with "date" and "muscle"
    bp: pd.DataFrame
    fitness: pd.DataFrame
    lifestyle: pd.DataFrame
    insights: dict[str, Any]
    has_nutrition: bool

    def last(self, column: str, days: int, end: date | None = None) -> pd.Series:
        """Values of `column` in the `days` days up to `end` (default today), without gaps."""
        end = pd.Timestamp(end or self.today)
        window = self.days.loc[end - pd.Timedelta(days=days - 1):end]
        return window[column].dropna() if column in window else pd.Series(dtype=float)

    def mean(self, column: str, days: int, end: date | None = None, minimum: int = 3) -> float | None:
        values = self.last(column, days, end)
        return float(values.mean()) if len(values) >= minimum else None


def load(today: date | None = None) -> Data:
    """Everything the rules read, from the files in DATA_DIR."""
    today = today or config.today()
    daily = analyze.load_daily()
    garmin = _read(config.GARMIN_CSV)
    if len(garmin):
        g = garmin.assign(date=pd.to_datetime(garmin["date"])).drop_duplicates("date", keep="last").set_index("date")
        start = g.index.min() if daily.empty else min(g.index.min(), daily.index.min())
    else:
        g = pd.DataFrame()
        start = daily.index.min() if not daily.empty else pd.Timestamp(today)
    index = pd.date_range(start, pd.Timestamp(today), freq="D")
    days = daily.reindex(index) if not daily.empty else pd.DataFrame(index=index)
    if len(g):
        g = g.reindex(index)
        for col in ("weight_kg", "bmi", "hrv_baseline_low_ms", "hrv_baseline_high_ms", "calories_total",
                    "calories_active"):
            days[col] = _num(g, col)
        for col in ("readiness_level", "sleep_start_local", "sleep_end_local"):
            days[col] = g[col] if col in g else None
    food = _read(config.NUTRITION_CSV)
    if len(food):
        f = food.assign(date=pd.to_datetime(food["date"])).drop_duplicates("date", keep="last").set_index("date")
        f = f.reindex(index)
        days["intake_kcal"] = _num(f, "calories_kcal")  # every logged day, also incomplete ones
    for col in ("hrv", "resting_hr", "sleep_hours", "steps", "weight_kg", "protein_g", "calories_kcal"):
        if col not in days:
            days[col] = np.nan

    activities = _read(config.ACTIVITIES_CSV)
    if len(activities):
        activities = activities.assign(
            date=pd.to_datetime(activities["date"]),
            start=pd.to_datetime(activities.get("start_time_local"), errors="coerce"),
            duration_min=_num(activities, "duration_min"),
            aerobic_te=_num(activities, "aerobic_te"),
            anaerobic_te=_num(activities, "anaerobic_te"),
            type=activities.get("type", pd.Series(dtype=str)).fillna("").astype(str),
        )

    sets = _read(config.HEVY_CSV)
    if len(sets):
        exercises = _read(config.HEVY_EXERCISES_CSV)
        muscles = (dict(zip(exercises["exercise_template_id"].astype(str), exercises["primary_muscle_group"],
                            strict=False)) if {"exercise_template_id", "primary_muscle_group"} <= set(exercises)
                   else {})
        grip = {name.casefold() for name in config.GRIP_EXERCISES}
        s = sets[~sets["exercise"].fillna("").astype(str).str.strip().str.casefold().isin(grip)]
        s = s[s["set_type"].fillna("normal").astype(str).str.lower().isin(analyze.HARD_SET_TYPES)]
        sets = pd.DataFrame({
            "date": pd.to_datetime(s["date"]),
            "muscle": s.get("exercise_template_id", pd.Series(index=s.index, dtype=str)).astype(str).map(muscles),
        })

    bp = _read(config.BLOOD_PRESSURE_CSV)
    if len(bp):
        bp = bp.assign(date=pd.to_datetime(bp["date"]), systolic=_num(bp, "systolic"), diastolic=_num(bp, "diastolic"))
    fitness = _read(config.FITNESS_CSV)
    if len(fitness):
        fitness = fitness.assign(date=pd.to_datetime(fitness["date"]), vo2max=_num(fitness, "vo2max"))
    lifestyle = _read(config.LIFESTYLE_CSV)
    if len(lifestyle):
        lifestyle = lifestyle[lifestyle["name"].fillna("").astype(str).str.strip() != ""]
        lifestyle = lifestyle.assign(date=pd.to_datetime(lifestyle["date"]), value=_num(lifestyle, "value"))
    try:
        insights = json.loads(config.INSIGHTS_JSON.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        insights = {}
    return Data(today, days, activities, sets, bp, fitness, lifestyle, insights, len(food) > 0)


# --------------------------------------------------------------------------- helpers


def slope_per_week(series: pd.Series) -> float | None:
    """Least-squares trend of a daily series in units per week; None with fewer than 7 values."""
    values = series.dropna()
    if len(values) < 7:
        return None
    x = (values.index - values.index[0]).days.to_numpy(dtype=float)
    if np.ptp(x) < 6:
        return None
    return float(np.polyfit(x, values.to_numpy(dtype=float), 1)[0] * 7)


def _clock_minutes(stamp: Any) -> float | None:
    """Minutes after 18:00 of a "YYYY-MM-DD HH:MM" stamp, so bedtimes around midnight compare."""
    try:
        t = datetime.strptime(str(stamp)[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    return ((t.hour - 18) % 24) * 60 + t.minute


def _minutes_to_clock(minutes: float) -> str:
    total = int(round(minutes)) + 18 * 60
    return f"{(total // 60) % 24:02d}:{total % 60:02d}"


def behaviour(data: Data, *words: str) -> pd.DataFrame:
    """Lifestyle Logging rows whose behaviour name contains one of `words` (any language)."""
    if data.lifestyle.empty:
        return data.lifestyle
    pattern = "|".join(re.escape(w) for w in words)
    return data.lifestyle[data.lifestyle["name"].astype(str).str.contains(pattern, case=False, regex=True)]


def _night_after(data: Data, days: pd.Series, column: str) -> pd.Series:
    """Overnight values of the night after each day (stored on the next date)."""
    shifted = data.days[column].shift(-1) if column in data.days else pd.Series(dtype=float)
    return shifted.reindex(pd.to_datetime(days)).dropna()


ENDURANCE = re.compile(r"run|cycl|bik|ride|swim|hik|row|elliptic|ski|stair|walk", re.I)


# --------------------------------------------------------------------------- rules


def rule_today(data: Data) -> Card | None:
    """Rule 1: low readiness, or HRV below range with resting HR 5 bpm above the 60-day mean."""
    today = pd.Timestamp(data.today)
    if today not in data.days.index:
        return None
    row = data.days.loc[today]
    level = str(row.get("readiness_level") or "").upper()
    hrv7, rhr7 = data.mean("hrv", 7), data.mean("resting_hr", 7)
    low = data.mean("hrv_baseline_low_ms", 7, minimum=1)
    rhr60 = data.mean("resting_hr", 60, minimum=20)
    hrv_low = hrv7 is not None and low is not None and hrv7 < low
    rhr_gap = rhr7 - rhr60 if rhr7 is not None and rhr60 is not None else None
    readiness_low = level in ("LOW", "POOR")
    if not (readiness_low or (hrv_low and rhr_gap is not None and rhr_gap >= 5)):
        return None
    # Possible infection: resting HR clearly up on each of the last 3 days and HRV clearly low
    recent = data.last("resting_hr", 3)
    sick = (rhr60 is not None and len(recent) == 3 and bool((recent >= rhr60 + 5).all())
            and hrv7 is not None and low is not None and hrv7 < low * 0.92)
    reasons = []
    if readiness_low and pd.notna(row.get("readiness")):
        reasons.append(text("Readiness {0}", n(row["readiness"])))
    if hrv_low:
        reasons.append(text("HRV {0} ms unter deinem Bereich ab {1}", n(hrv7), n(low)))
    if rhr_gap is not None and rhr_gap >= 2.5:
        reasons.append(text("Ruhepuls {0} bpm über deinem 60-Tage-Mittel", n(rhr_gap, 1)))
    if sick:
        title = text("Heute Pause")
        why = text("Ruhepuls seit 3 Tagen erhöht und HRV deutlich tief: das passt auch zu einem Infekt. "
                   "Fühlst du dich krank, trainiere nicht.")
    else:
        title = text("Heute locker statt schwer")
        why = text("Kein schweres Kraft- oder Intervalltraining; locker, Technik oder Pause.")
    return Card("today", title, why, text("Readiness und HRV der nächsten 2 Tage"),
                extra={"reasons": reasons, "pause": sick})


def rule_blood_pressure(data: Data) -> list[Card]:
    """Rules 14 and 19: mean of the readings in the last 30 days (at least 3)."""
    if data.bp.empty:
        return []
    recent = data.bp[data.bp["date"] >= pd.Timestamp(data.today - timedelta(days=29))].dropna(
        subset=["systolic", "diastolic"])
    if len(recent) < 3:
        return []
    sys_, dia = float(recent["systolic"].mean()), float(recent["diastolic"].mean())
    current = text("{0}/{1} mmHg", n(sys_), n(dia))
    if sys_ >= 140 or dia >= 90:
        return [Card("blood-pressure-high", text("Blutdruck ärztlich abklären lassen"),
                     text("Dein Mittel der letzten 30 Tage liegt bei {0}/{1} mmHg, ab 140/90 gilt das als "
                          "Bluthochdruck. selftopo schlägt dafür keine Selbstversuche vor.", n(sys_), n(dia)),
                     text("Blutdruck-Mittel, 30 Tage"), current, extra={"readings": len(recent)})]
    if sys_ >= 120 or dia >= 70:
        return [Card("blood-pressure-elevated",
                     text("Ausdauer 2–3× pro Woche, weniger Salz"),
                     text("Dein Mittel der letzten 30 Tage liegt bei {0}/{1} mmHg, ab 120/70 gilt das als erhöht. "
                          "Ausdauertraining senkte den Blutdruck im Mittel um 3,5/2,5 mmHg, weniger Salz um "
                          "etwa 4/2 mmHg, jedes kg Abnahme um etwa 1 mmHg.", n(sys_), n(dia)),
                     text("Blutdruck-Mittel, 8 Wochen"), current, extra={"readings": len(recent)})]
    return []


def goal_progress(data: Data, goal: Goal) -> dict[str, Any]:
    """Distance, pace and forecast of one goal."""
    out: dict[str, Any] = {"area": goal.area, "metric": goal.metric, "target": goal.target,
                           "by": goal.by.isoformat() if goal.by else None, "current": None, "pace_per_week": None,
                           "needed_per_week": None, "eta": None, "status": "no-data"}
    if goal.metric == "hrv":
        hrv7, low = data.mean("hrv", 7), data.mean("hrv_baseline_low_ms", 7, minimum=1)
        high = data.mean("hrv_baseline_high_ms", 7, minimum=1)
        if hrv7 is not None and low is not None:
            out.update(current=round(hrv7, 1), range=[low, high],
                       status="reached" if hrv7 >= low else "off-track")
        return out
    if goal.metric == "bedtime":
        target = _clock_minutes(f"2000-01-01 {goal.target}")
        starts = data.days["sleep_start_local"].iloc[-7:] if "sleep_start_local" in data.days else pd.Series()
        minutes = [m for m in (_clock_minutes(s) for s in starts.dropna()) if m is not None]
        if len(minutes) >= 3:
            on_time = sum(m <= target for m in minutes)
            out.update(current=_minutes_to_clock(float(np.median(minutes))), nights=len(minutes), on_time=on_time,
                       status="reached" if on_time >= 5 else "off-track")
        return out
    if goal.metric == "weekly_sets":
        weekly = sets_per_muscle(data)
        if weekly:
            below = {m: v for m, v in weekly.items() if v < goal.target}
            out.update(current=round(min(weekly.values()), 1), below=sorted(below),
                       status="reached" if not below else "off-track")
        return out

    series, window = {
        "weight": (data.days["weight_kg"], 28), "resting_hr": (data.days["resting_hr"], 56),
        "sleep_hours": (data.days["sleep_hours"], 28), "steps": (data.days["steps"], 28),
        "vo2max": (_vo2max_series(data), 84), "active_minutes": (_weekly_active(data), 56),
    }[goal.metric]
    end = pd.Timestamp(data.today)
    recent = series.loc[end - pd.Timedelta(days=window - 1):end].dropna()
    if goal.metric == "vo2max":
        current = float(recent.iloc[-1]) if len(recent) else None
    elif goal.metric == "active_minutes":
        current = float(recent.iloc[-1]) if len(recent) else None
    else:
        last7 = series.loc[end - pd.Timedelta(days=6):end].dropna()
        current = float(last7.mean()) if len(last7) >= 3 else None
    if current is None:
        return out
    direction = BETTER[goal.metric]
    if goal.metric == "weight":
        direction = -1 if goal.target < current else 1
    pace = slope_per_week(recent)
    remaining = float(goal.target) - current
    reached = remaining * direction <= 0
    out.update(current=round(current, 2), remaining=round(remaining, 2), status="reached" if reached else "off-track")
    if pace is not None:
        out["pace_per_week"] = round(pace, 3)
    if reached:
        return out
    if goal.by and goal.by > data.today:
        out["needed_per_week"] = round(remaining / ((goal.by - data.today).days / 7), 3)
    if pace is not None and pace * remaining > 0 and abs(pace) > 1e-9:
        weeks = remaining / pace
        if weeks <= 520:
            out["eta"] = (data.today + timedelta(days=round(weeks * 7))).isoformat()
    if goal.by:
        on_track = out["eta"] is not None and date.fromisoformat(out["eta"]) <= goal.by
        out["status"] = "on-track" if on_track else "off-track"
    elif out["eta"]:
        out["status"] = "on-track"
    return out


def _vo2max_series(data: Data) -> pd.Series:
    if data.fitness.empty:
        return pd.Series(dtype=float)
    return data.fitness.set_index("date")["vo2max"].dropna().sort_index()


def _weekly_active(data: Data) -> pd.Series:
    """Activity minutes of the 7 days up to each day."""
    if "active_min" not in data.days:
        return pd.Series(dtype=float)
    return data.days["active_min"].rolling(7, min_periods=7).sum()


def sets_per_muscle(data: Data) -> dict[str, float]:
    """Hard sets per week and primary muscle group, mean of the last 4 weeks."""
    if data.sets.empty:
        return {}
    start = pd.Timestamp(data.today - timedelta(days=27))
    recent = data.sets[(data.sets["date"] >= start) & data.sets["muscle"].notna()]
    if data.sets["date"].min() > start or recent.empty:
        return {}  # less than 4 weeks of Hevy data
    return {str(m): round(c / 4, 1) for m, c in recent.groupby("muscle").size().items()}


def rule_weight_pace(data: Data, goal: Goal, progress: dict[str, Any]) -> Card | None:
    """Rule 3: losing slower than the goal date needs. Safety: BMI, 1 %/week, resting metabolic rate."""
    if goal.metric != "weight" or progress["status"] in ("reached", "no-data") or not goal.by:
        return None
    current, pace, needed = progress["current"], progress["pace_per_week"], progress["needed_per_week"]
    if pace is None or needed is None or needed >= 0:  # only for losing weight
        return None
    # Safety fails closed: without a BMI the lower limit cannot be checked, so there is no card
    bmi = data.mean("bmi", 14, minimum=1)
    if bmi is None:
        return None
    height2 = current / bmi
    if bmi < MIN_BMI or float(goal.target) / height2 < MIN_BMI:
        return None
    max_rate = -current * MAX_LOSS_PCT_PER_WEEK / 100
    capped = needed < max_rate
    rate = max(needed, max_rate)
    gap = rate - pace  # kg/week still missing (negative)
    if gap > -0.05:
        return None
    kcal = -gap * KCAL_PER_KG / 7
    measure = text("Abnahmetempo über 28 Tage, Muskelmasse")
    current_text = text("{0} kg/Woche", n(pace, 2))
    # Safety: the intake this leads to stays above Garmin's resting energy (total minus active
    # calories). Intake is the mean of completely logged days; without YAZIO it is estimated from
    # Garmin's expenditure and the observed pace. Without either, there is no card.
    bmr = (data.days["calories_total"] - data.days["calories_active"]).iloc[-28:].dropna()
    if len(bmr) < 7:
        return None
    intake = data.mean("calories_kcal", 14)
    if intake is None:
        expenditure = data.mean("calories_total", 28, minimum=7)
        if expenditure is None:
            return None
        intake = expenditure + pace * KCAL_PER_KG / 7
    if intake - kcal < float(bmr.median()):
        kcal = max(0.0, intake - float(bmr.median()))
        if kcal < 50:
            return None
    title = text("Rund {0} kcal pro Tag weniger", n(round(kcal / 10) * 10))
    if capped:
        why = text("Dein Gewicht ändert sich um {0} kg pro Woche. Dein Zieldatum bräuchte mehr als 1 % pro Woche; "
                   "selftopo rechnet mit höchstens {1} kg pro Woche, das schützt Muskelmasse und Kraft.",
                   n(pace, 2), n(-max_rate, 2))
    else:
        why = text("Dein Gewicht ändert sich um {0} kg pro Woche. Für {1} kg bis {2} bräuchtest du {3} kg pro Woche.",
                   n(pace, 2), n(float(goal.target), 1), {"date": goal.by.isoformat()}, n(needed, 2))
    return Card("weight-pace", title, why, measure, current_text, extra={"kcal_per_day": round(kcal)})


def rule_protein(data: Data) -> Card | None:
    """Rule 4: protein below 1.6 g/kg in the 7-day mean (complete logging days only)."""
    protein, weight = data.mean("protein_g", 7), data.mean("weight_kg", 14, minimum=1)
    if protein is None or weight is None:
        return None
    per_kg = protein / weight
    if per_kg >= 1.6:
        return None
    return Card("protein", text("Eiweiß auf 1,6 g/kg anheben, z. B. eine eiweißreiche Mahlzeit mehr"),
                text("Du isst im Mittel {0} g/kg. Über etwa 1,6 g/kg brachte mehr Eiweiß im Mittel keinen weiteren "
                     "Zuwachs an fettfreier Masse.", n(per_kg, 1)),
                text("Eiweiß g/kg, Muskelmasse"), text("{0} g/kg", n(per_kg, 1)))


def rule_food_logging(data: Data) -> Card | None:
    """Rule 5: fewer than 5 of the last 7 days logged completely."""
    if not data.has_nutrition:
        return None
    end = pd.Timestamp(data.today - timedelta(days=1))  # today is not complete yet
    window = data.days.loc[end - pd.Timedelta(days=6):end, "intake_kcal"] if "intake_kcal" in data.days else None
    if window is None:
        return None
    complete = int((window >= analyze.MIN_COMPLETE_KCAL).sum())
    if complete >= 5:
        return None
    return Card("food-logging", text("Diese Woche jeden Tag vollständig loggen"),
                text("Nur {0} von 7 Tagen sind vollständig geloggt; ohne sie ist die Energiebilanz unsicher und "
                     "die Empfehlung zum Abnehmtempo bleibt aus.", n(complete)),
                text("vollständig geloggte Tage"), text("{0} von 7", n(complete)))


def rule_weighing(data: Data) -> Card | None:
    """Rule 21: fewer than 4 weigh-ins in the last 7 days."""
    count = len(data.last("weight_kg", 7))
    if count >= 4:
        return None
    return Card("weighing", text("Morgens nach dem Aufstehen wiegen, möglichst täglich"),
                text("Nur {0} Wiegungen in 7 Tagen. Das 7-Tage-Mittel braucht mehr Werte, sonst ist das Tempo zum "
                     "Ziel ungenau.", n(count)),
                text("Wiegungen pro Woche"), text("{0} von 7", n(count)))


def rule_endurance(data: Data) -> Card | None:
    """Rule 6: fewer than 2 endurance sessions (20 min or more) per week over 4 weeks."""
    if data.activities.empty:
        return None
    start = pd.Timestamp(data.today - timedelta(days=27))
    if data.activities["date"].min() > start:
        return None
    a = data.activities[(data.activities["date"] >= start) & (data.activities["duration_min"] >= 20)]
    per_week = len(a[a["type"].str.contains(ENDURANCE)]) / 4
    if per_week >= 2:
        return None
    return Card("endurance", text("2–3 lockere Ausdauereinheiten pro Woche"),
                text("In den letzten 4 Wochen waren es {0} pro Woche. Ausdauertraining senkte den Ruhepuls "
                     "in Studien, Krafttraining nicht in beiden Geschlechtern.", n(per_week, 1)),
                text("Ruhepuls, 8–12 Wochen"), text("{0} pro Woche", n(per_week, 1)))


def rule_activity_minutes(data: Data) -> Card | None:
    """Rule 17: fewer than 150 activity minutes per week over 4 weeks."""
    if data.activities.empty:
        return None
    start = pd.Timestamp(data.today - timedelta(days=27))
    if data.activities["date"].min() > start:
        return None
    minutes = float(data.activities.loc[data.activities["date"] >= start, "duration_min"].sum()) / 4
    if minutes >= 150:
        return None
    return Card("activity-minutes", text("Auf 150–300 Minuten Bewegung pro Woche kommen"),
                text("Deine Aktivitäten der Uhr ergeben {0} min pro Woche. Die WHO empfiehlt Erwachsenen "
                     "150–300 min mäßige oder 75–150 min intensive Bewegung pro Woche; zügiges Gehen zählt.",
                     n(minutes)),
                text("Aktive Minuten pro Woche"), text("{0} min/Woche", n(minutes)))


def rule_steps(data: Data) -> Card | None:
    """Rule 12: steps below 8,000 in the 28-day mean."""
    steps = data.mean("steps", 28, minimum=14)
    if steps is None or steps >= 8000:
        return None
    goal = min(8000, int(math.ceil((steps + 1) / 1000) * 1000))
    return Card("steps", text("Schrittziel auf {0} anheben", n(goal)),
                text("Im Mittel gehst du {0} Schritte. Unter 60 Jahren flachte der Nutzen in Studien erst bei "
                     "8.000–10.000 Schritten ab; in 1.000er-Stufen ist das gut machbar.", n(steps)),
                text("Schritte, Ziel-Tage"), text("{0} pro Tag", n(steps)))


def rule_sleep_duration(data: Data, target: float | None) -> Card | None:
    """Rule 8: sleep below 7 h (or the goal) in the 7-day mean."""
    hours = data.mean("sleep_hours", 7)
    limit = max(7.0, float(target)) if target else 7.0
    if hours is None or round(hours, 1) >= limit:  # compared as shown, so the card never says "7.0 h" is too little
        return None
    return Card("sleep-duration", text("Bettzeit 30 min früher, an Arbeitstagen zuerst"),
                text("Du schläfst im Mittel {0} h. Erwachsene sollen regelmäßig 7 h oder mehr schlafen.",
                     n(hours, 1)),
                text("Schlafdauer"), text("{0} h", n(hours, 1)))


def rule_sleep_regularity(data: Data) -> Card | None:
    """Rule 9: sleep midpoint on weekend nights more than 1 h later than on weekday nights (28 days)."""
    if "sleep_start_local" not in data.days:
        return None
    window = data.days.iloc[-28:]
    weekend, weekday = [], []
    for day, row in window.iterrows():
        start, end = _clock_minutes(row.get("sleep_start_local")), _clock_minutes(row.get("sleep_end_local"))
        if start is None or end is None:
            continue
        end = end if end > start else end + 24 * 60
        (weekend if day.weekday() >= 5 else weekday).append((start + end) / 2)
    if len(weekend) < 2 or len(weekday) < 5:
        return None
    shift = float(np.median(weekend) - np.median(weekday))
    if shift <= 60:
        return None
    return Card("sleep-regularity", text("Gleiche Aufstehzeit ± 30 min, auch am Wochenende"),
                text("Am Wochenende liegt deine Schlafmitte {0} h später als unter der Woche. Regelmäßigkeit "
                     "sagte in einer großen Beobachtungsstudie die Sterblichkeit stärker voraus als die Dauer.",
                     n(shift / 60, 1)),
                text("Wochenend-Verschiebung der Schlafmitte"), text("{0} h", n(shift / 60, 1)))


def rule_late_training(data: Data) -> Card | None:
    """Rule 2: intense activities ending less than 1 h before falling asleep, 2 or more in 14 days."""
    if data.activities.empty or "sleep_start_local" not in data.days:
        return None
    start = pd.Timestamp(data.today - timedelta(days=13))
    a = data.activities[(data.activities["date"] >= start) & data.activities["start"].notna()]
    intense = a[(a["aerobic_te"] >= 4.0) | (a["anaerobic_te"] >= 2.0)]
    late = 0
    for _, act in intense.iterrows():
        if pd.isna(act["duration_min"]):
            continue
        end = act["start"] + pd.Timedelta(minutes=float(act["duration_min"]))
        night = act["date"] + pd.Timedelta(days=1)
        sleep = data.days["sleep_start_local"].get(night)
        sleep_at = pd.to_datetime(sleep, errors="coerce") if isinstance(sleep, str) else pd.NaT
        if pd.notna(sleep_at) and pd.Timedelta(0) <= sleep_at - end < pd.Timedelta(hours=1):
            late += 1
    if late < 2:
        return None
    return Card("late-training", text("Intensive Einheiten früher legen; lockeres Training abends ist in Ordnung"),
                text("{0}-mal endete in 14 Tagen eine intensive Einheit weniger als 1 h vor dem Einschlafen. "
                     "Abendtraining stört den Schlaf im Mittel nicht, intensives kurz vor dem Schlafen kann es.",
                     n(late)),
                text("Einschlafzeit, Sleep Score nach Trainingsabenden"), text("{0} in 14 Tagen", n(late)))


def rule_training_volume(data: Data, target: float) -> Card | None:
    """Rule 15: a muscle group gets fewer than 10 (or the goal's) hard sets per week."""
    weekly = sets_per_muscle(data)
    below = {m: v for m, v in weekly.items() if v < target}
    if not below:
        return None
    names = sorted(below, key=lambda m: below[m])[:3]
    return Card("training-volume", text("Sätze schrittweise auf {0} pro Woche anheben, etwa +2 pro Woche", n(target)),
                text("Unter {0} harten Sätzen pro Woche: {1}. Mehr Wochensätze brachten mehr Muskelzuwachs; bei "
                     "gleichem Volumen ist die Zahl der Einheiten egal.", n(target),
                     {"list": [{"muscle": m} for m in names]}),
                text("Sätze je Muskelgruppe, Muskelmasse, 8–12 Wochen"),
                text("{0} Sätze/Woche", n(min(below.values()), 1)), extra={"muscles": names})


def rule_intervals(data: Data) -> Card | None:
    """Rule 16: VO2max not up in 8 weeks and no interval session in 4 weeks."""
    vo2 = _vo2max_series(data)
    end = pd.Timestamp(data.today)
    if len(vo2) < 2 or vo2.index.min() > end - pd.Timedelta(days=56):
        return None
    before = vo2.loc[:end - pd.Timedelta(days=56)]
    if before.empty or vo2.iloc[-1] > before.iloc[-1]:
        return None
    if not data.activities.empty:
        recent = data.activities[data.activities["date"] >= end - pd.Timedelta(days=27)]
        if (recent["anaerobic_te"] >= 2.0).any():
            return None
    return Card("intervals", text("Eine Intervalleinheit pro Woche, z. B. 4 × 4 min hart"),
                text("Deine VO2max steht seit 8 Wochen bei {0}, und in 4 Wochen war keine Intervalleinheit dabei. "
                     "Intervall- und Dauertraining steigern VO2max beide, Intervalle etwas mehr. "
                     "An Tagen mit niedriger Readiness hat die Heute-Karte Vorrang.", n(float(vo2.iloc[-1]))),
                text("VO2max, 8–12 Wochen"), text("VO2max {0}", n(float(vo2.iloc[-1]))))


def _behaviour_experiment(data: Data, rule: str, words: tuple[str, ...], outcome: str, min_days: int,
                          title: dict, why: str, measure: dict, metrics: list[str]) -> Card | None:
    """Rules 7 and 20: behaviour logged on enough days, and the outcome worse in the nights after."""
    rows = behaviour(data, *words)
    if rows.empty:
        return None
    recent = rows[rows["date"] >= pd.Timestamp(data.today - timedelta(days=27))]
    yes_days = pd.Series(recent.loc[recent["value"] > 0, "date"].unique())
    no_days = pd.Series(recent.loc[recent["value"] == 0, "date"].unique())
    if len(yes_days) < min_days or len(no_days) < min_days:
        return None
    with_, without = _night_after(data, yes_days, outcome), _night_after(data, no_days, outcome)
    if len(with_) < min_days or len(without) < min_days:
        return None
    diff = float(with_.mean() - without.mean())
    if diff * BETTER.get(outcome, 1) >= 0:
        return None
    return Card(rule, title, text(why, n(abs(diff), 1), n(len(with_))), measure,
                experiment={"days": EXPERIMENT_DAYS, "metrics": metrics, "behaviour": list(words)})


def rule_alcohol(data: Data) -> Card | None:
    return _behaviour_experiment(
        data, "alcohol", ("alcohol", "alkohol"), "hrv", 3,
        text("Experiment: 14 Tage ohne Alkohol"),
        "Nach Tagen mit Alkohol war deine HRV im Mittel {0} ms niedriger als ohne ({1} Nächte). Studien zeigen, "
        "dass Alkohol die nächtliche Erholung schon in kleiner Menge senkt.",
        text("HRV, Ruhepuls, Sleep Score vorher/nachher"), ["hrv", "resting_hr", "sleep_score"])


def rule_late_meal(data: Data) -> Card | None:
    return _behaviour_experiment(
        data, "late-meal", ("late meal", "spätes essen", "spaetes essen", "late eating"), "sleep_score", 3,
        text("Experiment: 14 Tage die letzte große Mahlzeit spätestens 3 h vor dem Schlafen"),
        "Nach Tagen mit spätem Essen war dein Sleep Score im Mittel {0} Punkte niedriger ({1} Nächte). "
        "Das ist ein Zusammenhang in deinen Daten, keine Ursache; das Experiment prüft es.",
        text("Sleep Score, Einschlafzeit, HRV"), ["sleep_score", "bedtime", "hrv"])


def rule_caffeine(data: Data) -> Card | None:
    """Rule 11: late caffeine logged on 2 or more of the last 14 days."""
    rows = behaviour(data, "caffeine", "koffein", "coffein")
    if rows.empty:
        return None
    recent = rows[(rows["date"] >= pd.Timestamp(data.today - timedelta(days=13))) & (rows["value"] > 0)]
    days = recent["date"].nunique()
    if days < 2:
        return None
    return Card("caffeine", text("Kein Koffein in den 6 Stunden vor dem Schlafen"),
                text("Spätes Koffein an {0} von 14 Tagen. 400 mg Koffein 6 h vor dem Schlafen verkürzten den "
                     "Schlaf in einer kleinen Studie um mehr als 1 h.", n(days)),
                text("Einschlafzeit, Schlafdauer"), text("{0} von 14 Tagen", n(days)))


# Behaviours from insights.json an experiment can change, and the outcomes, with their German names
OWN_DATA_DRIVERS = {"training_load": "Trainingslast", "active_min": "aktive Zeit", "steps": "Schritte",
                    "hard_sets": "harte Sätze", "tonnage_t": "Tonnage", "calories_kcal": "Kalorien",
                    "protein_g": "Eiweiß", "carbs_g": "Kohlenhydrate", "fat_g": "Fett"}
# The step of each behaviour in insights.json ("effect_per"), in German
EFFECT_PER = {"100 points": "100 Punkte", "1 hour": "Stunde", "1,000 steps": "1.000 Schritte", "10 sets": "10 Sätze",
              "1 t": "Tonne", "500 kcal": "500 kcal", "50 g": "50 g", "100 g": "100 g", "30 g": "30 g"}
OUTCOME_NAMES = {"hrv": "HRV", "resting_hr": "Ruhepuls", "sleep_score": "Sleep Score", "sleep_hours": "Schlafdauer"}
GOAL_OUTCOMES = {"erholung": {"hrv", "resting_hr"}, "schlaf": {"sleep_score", "sleep_hours"}}


def rule_own_data(data: Data, goals: dict[str, Goal]) -> list[Card]:
    """Rules 10 and 13: robust relationships in insights.json between a behaviour and a goal metric."""
    outcomes = set().union(*(GOAL_OUTCOMES.get(a, set()) for a in goals)) if goals else set()
    cards, used = [], set()
    for f in data.insights.get("findings", []):
        if f.get("status") != "robust" or f.get("outcome") not in outcomes:
            continue
        driver, outcome, effect = f.get("driver"), f["outcome"], f.get("effect")
        if effect is None:
            continue
        better = BETTER.get(outcome, 1)
        if driver == "bedtime_min" and "bedtime-hrv" not in used:
            if effect * better >= 0:  # later bedtime goes with a better outcome: nothing to suggest
                continue
            used.add("bedtime-hrv")
            target = goals["schlaf"].target if "schlaf" in goals and goals["schlaf"].metric == "bedtime" else "23:00"
            cards.append(Card("bedtime-hrv", text("Experiment: 14 Tage vor {0} einschlafen", {"clock": target}),
                              text("Spätes Einschlafen ging in deinen Daten mit {0} {1} pro Stunde einher ({2} Tage).",
                                   n(effect, 1), f.get("effect_unit", ""), n(f.get("n", 0))),
                              text("HRV, Sleep Score"),
                              experiment={"days": EXPERIMENT_DAYS, "metrics": [outcome, "sleep_score"],
                                          "finding": {k: f.get(k) for k in ("driver", "outcome", "effect", "n", "q")}}))
        elif driver in OWN_DATA_DRIVERS and "own-data" not in used:
            used.add("own-data")
            name, outcome_name = OWN_DATA_DRIVERS[driver], OUTCOME_NAMES.get(outcome, outcome)
            per = EFFECT_PER.get(f.get("effect_per"), f.get("effect_per", ""))
            title = (text("Experiment: 14 Tage weniger {0}", {"t": name}) if effect * better < 0
                     else text("Experiment: 14 Tage mehr {0}", {"t": name}))
            cards.append(Card("own-data", title,
                              text("In deinen Daten ging mehr {0} mit {1} {2} {3} einher, pro {4} ({5} Tage). Ein "
                                   "Zusammenhang, keine Ursache; das Experiment prüft es.", {"t": name}, n(effect, 1),
                                   f.get("effect_unit", ""), {"t": outcome_name}, {"t": per},
                                   n(f.get("n", 0))),
                              text("{0}, 14 Tage", {"t": outcome_name}),
                              experiment={"days": EXPERIMENT_DAYS, "metrics": [outcome],
                                          "finding": {k: f.get(k) for k in ("driver", "outcome", "effect", "n", "q")}}))
    return cards


# --------------------------------------------------------------------------- experiments

EXPERIMENT_METRICS = {"hrv": "hrv", "resting_hr": "resting_hr", "sleep_score": "sleep_score",
                      "sleep_hours": "sleep_hours", "steps": "steps", "weight": "weight_kg"}


def evaluate_experiment(data: Data, entry: dict[str, Any]) -> dict[str, Any] | None:
    """Compare the experiment days with as many days before: median and interquartile range per metric."""
    try:
        start = date.fromisoformat(str(entry["start"]))
    except (KeyError, ValueError):
        return None
    days = int(entry.get("days") or EXPERIMENT_DAYS)
    rule = RULES.get(str(entry.get("rule")))
    end = start + timedelta(days=days - 1)
    elapsed = max(0, min(days, (data.today - start).days + 1))
    out = {"rule": rule.id if rule else entry.get("rule"), "start": start.isoformat(), "days": days,
           "elapsed": elapsed, "status": "running" if data.today <= end else "done", "metrics": [],
           "title": entry.get("title") if isinstance(entry.get("title"), dict) else None}
    metrics = entry.get("metrics") or ["hrv", "resting_hr", "sleep_score"]
    for metric in metrics:
        column = EXPERIMENT_METRICS.get(metric)
        if column is None or column not in data.days:
            continue
        series = data.days[column]
        during = series.loc[pd.Timestamp(start):pd.Timestamp(min(end, data.today))].dropna()
        before = series.loc[pd.Timestamp(start - timedelta(days=days)):pd.Timestamp(start - timedelta(days=1))].dropna()
        result = {"metric": metric, "before_n": len(before), "during_n": len(during)}
        if len(before) >= EXPERIMENT_MIN_DAYS and len(during) >= EXPERIMENT_MIN_DAYS:
            result.update(before=round(float(before.median()), 1), during=round(float(during.median()), 1),
                          before_iqr=[round(float(before.quantile(q)), 1) for q in (0.25, 0.75)],
                          during_iqr=[round(float(during.quantile(q)), 1) for q in (0.25, 0.75)])
        out["metrics"].append(result)
    return out


# --------------------------------------------------------------------------- assembly


def _hidden(settings: dict[str, Any], today: date) -> set[str]:
    """Rules hidden with "later" (until a date) or "does not fit" (for good)."""
    hidden = set()
    for rule, entry in (settings.get("recommendations_hidden") or {}).items():
        if not isinstance(entry, dict):
            continue
        until = entry.get("until")
        try:
            if entry.get("dismissed") or (until and date.fromisoformat(str(until)) >= today):
                hidden.add(rule)
        except ValueError:
            continue
    return hidden


def build(data: Data, settings: dict[str, Any]) -> dict[str, Any]:
    goals = parse_goals(settings, [])
    progress = {area: goal_progress(data, goal) for area, goal in goals.items()}
    active_areas = set(goals)
    experiments = [e for e in settings.get("experiments") or [] if isinstance(e, dict)]
    running = {str(e.get("rule")) for e in experiments}
    done = {str(e.get("rule")) for e in experiments
            if (ev := evaluate_experiment(data, e)) is not None and ev["status"] == "done"}
    hidden = _hidden(settings, data.today) | done

    def wanted(rule: str) -> bool:
        r = RULES[rule]
        return (not r.areas or bool(active_areas & set(r.areas))) and rule not in hidden

    cards: list[Card] = []
    safety = rule_blood_pressure(data)
    if goals:
        if "koerper" in goals:
            if (c := rule_weight_pace(data, goals["koerper"], progress["koerper"])):
                cards.append(c)
        candidates = [
            rule_protein, rule_food_logging, rule_weighing, rule_endurance, rule_activity_minutes, rule_steps,
            rule_sleep_regularity, rule_late_training, rule_intervals, rule_alcohol, rule_late_meal, rule_caffeine,
        ]
        for fn in candidates:
            if (c := fn(data)):
                cards.append(c)
        sleep = goals.get("schlaf")
        sleep_target = sleep.target if sleep and sleep.metric == "sleep_hours" else None
        if (c := rule_sleep_duration(data, sleep_target)):
            cards.append(c)
        sets_target = float(goals["kraft"].target) if "kraft" in goals else 10.0
        if (c := rule_training_volume(data, max(10.0, sets_target))):
            cards.append(c)
        cards += rule_own_data(data, goals)
    cards = [c for c in cards if wanted(c.rule) and c.rule not in running]
    cards.sort(key=lambda c: (EVIDENCE_ORDER[RULES[c.rule].evidence], RULES[c.rule].effort, RULES[c.rule].number))

    # Safety first: with blood pressure from 140/90, no experiments at all
    high_bp = any(c.rule == "blood-pressure-high" for c in safety)
    if high_bp:
        cards = [c for c in cards if RULES[c.rule].kind != "experiment"]
    safety_cards = [c for c in safety if c.rule == "blood-pressure-high"]
    cards = [c for c in safety if c.rule == "blood-pressure-elevated" and wanted(c.rule)] + cards

    today = rule_today(data)
    notes = []
    weight = progress.get("koerper", {})
    if "kraft" in goals and weight.get("needed_per_week") is not None and weight.get("current"):
        if -weight["needed_per_week"] / weight["current"] * 100 >= 0.7:
            notes.append(text("Deutlich abnehmen und gleichzeitig viel Kraft aufbauen widerspricht sich: "
                              "im Defizit wächst Kraft langsamer. Überlege, welches Ziel jetzt vorgeht."))
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "as_of": data.today.isoformat(),
        "today": today.to_json() if today and "today" not in hidden else None,
        "safety": [c.to_json() for c in safety_cards],
        "goals": list(progress.values()),
        "cards": [c.to_json() for c in cards[:MAX_LEVERS]],
        "more": [c.to_json() for c in cards[MAX_LEVERS:]],
        "experiments": [ev for e in experiments if (ev := evaluate_experiment(data, e)) is not None],
        "notes": notes,
        "sources": {k: {"label": label, "url": url} for k, (label, url) in SOURCES.items()},
    }


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, (float, np.floating)):
        value = float(value)
        return round(value, 4) if math.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    return value


def run(today: date | None = None) -> dict[str, Any]:
    problems: list[str] = []
    parse_goals(config.SETTINGS, problems)
    for problem in problems:
        log.warning("settings: %s", problem)
    result = _clean(build(load(today), config.SETTINGS))
    path = config.DATA_DIR / "recommendations.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    log.info("Recommendations: %d cards, today card %s -> %s", len(result["cards"]) + len(result["more"]),
             "yes" if result["today"] else "no", path)
    return result
