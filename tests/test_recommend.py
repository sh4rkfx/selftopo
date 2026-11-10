"""Recommendations

Goals from settings.json, the rules of the recommendation catalogue with their safety limits,
goal forecasts and experiments. Each test writes a small, made-up data set and checks which cards
come out.
"""

# ruff: noqa: E501

import json
from datetime import date, timedelta

import pytest

from selftopo import config, recommend
from selftopo.csvstore import write_rows

TODAY = date(2026, 11, 10)
DAYS = 120


def _paths(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    for name, file in [("GARMIN_CSV", "garmin_daily.csv"), ("ACTIVITIES_CSV", "garmin_activities.csv"),
                       ("HEVY_CSV", "hevy_sets.csv"), ("HEVY_EXERCISES_CSV", "hevy_exercises.csv"),
                       ("NUTRITION_CSV", "nutrition_daily.csv"), ("BLOOD_PRESSURE_CSV", "garmin_blood_pressure.csv"),
                       ("FITNESS_CSV", "garmin_fitness.csv"), ("LIFESTYLE_CSV", "garmin_lifestyle.csv"),
                       ("INSIGHTS_JSON", "insights.json")]:
        monkeypatch.setattr(config, name, tmp_path / file)


def day(i):
    """Day i of the data set; the last day (DAYS - 1) is TODAY."""
    return TODAY - timedelta(days=DAYS - 1 - i)


def garmin_rows(**overrides):
    """A calm, healthy baseline: weight 80 kg, HRV 60 in a 50–70 range, resting HR 50, 7.5 h sleep from 23:00."""
    rows = []
    for i in range(DAYS):
        d = day(i)
        row = {"date": d.isoformat(), "weight_kg": 80.0, "bmi": 24.7, "hrv_last_night_ms": 60,
               "hrv_baseline_low_ms": 50, "hrv_baseline_high_ms": 70, "resting_hr": 50, "sleep_score": 80,
               "sleep_hours": 7.5, "sleep_start_local": f"{(d - timedelta(days=1)).isoformat()} 23:00",
               "sleep_end_local": f"{d.isoformat()} 06:30", "steps": 9500, "calories_total": 2600,
               "calories_active": 800, "readiness_score": 70, "readiness_level": "MODERATE"}
        for key, value in overrides.items():
            row[key] = value(i, d) if callable(value) else value
        rows.append(row)
    return rows


def write(tmp_path, monkeypatch, garmin=None, activities=None, sets=None, food=None, bp=None, lifestyle=None,
          insights=None, fitness=None):
    from selftopo import activities as a
    from selftopo import bloodpressure, hevy, yazio
    from selftopo import fitness as fi
    from selftopo import garmin as g
    from selftopo import lifestyle as ls
    _paths(tmp_path, monkeypatch)
    write_rows(config.GARMIN_CSV, g.FIELDS, garmin if garmin is not None else garmin_rows())
    write_rows(config.ACTIVITIES_CSV, a.FIELDS, activities if activities is not None else endurance_rows(3))
    if sets is not None:
        write_rows(config.HEVY_CSV, hevy.FIELDS, sets)
        write_rows(config.HEVY_EXERCISES_CSV, hevy.EXERCISE_FIELDS, [
            {"exercise_template_id": "SQ", "title": "Squat", "primary_muscle_group": "quadriceps"},
            {"exercise_template_id": "BP", "title": "Bench Press", "primary_muscle_group": "chest"}])
    if food is not None:
        write_rows(config.NUTRITION_CSV, yazio.FIELDS, food)
    if bp is not None:
        write_rows(config.BLOOD_PRESSURE_CSV, bloodpressure.FIELDS, bp)
    if lifestyle is not None:
        write_rows(config.LIFESTYLE_CSV, ls.FIELDS, lifestyle)
    if fitness is not None:
        write_rows(config.FITNESS_CSV, fi.FIELDS, fitness)
    if insights is not None:
        config.INSIGHTS_JSON.write_text(json.dumps(insights), encoding="utf-8")
    return recommend.load(TODAY)


def endurance_rows(per_week, kind="running", te=(3.0, 0.5), minutes=45):
    rows = []
    for i in range(DAYS):
        d = day(i)
        if per_week and d.weekday() in (0, 2, 4)[:per_week]:
            rows.append({"date": d.isoformat(), "start_time_local": f"{d.isoformat()} 07:00:00", "activity_id": i,
                         "type": kind, "duration_min": minutes, "aerobic_te": te[0], "anaerobic_te": te[1]})
    return rows


def rules(result):
    return [c["rule"] for c in result["cards"] + result["more"]]


def build(data, **settings):
    return recommend.build(data, settings)


# --------------------------------------------------------------------------- goals


def test_goals_are_read_per_area_and_bad_entries_reported(given):
    """One goal per area; unknown areas, wrong metrics, missing targets and bad dates are reported, the rest is kept."""
    settings = {"goals": {
        "koerper": {"metric": "weight", "target": 75, "by": "2027-03-31"},
        "schlaf": {"metric": "bedtime", "target": "23:00"},
        "erholung": {"metric": "hrv"},
        "kraft": {"metric": "e1rm", "target": 100},
        "fitness": {"metric": "vo2max", "target": -3},
        "garten": {"metric": "weight", "target": 1},
        "aktivitaeten": {"metric": "steps", "target": 10000, "by": "bald"},
    }}
    given(settings=settings)
    problems = []
    goals = recommend.parse_goals(settings, problems)
    assert sorted(goals) == ["aktivitaeten", "erholung", "koerper", "schlaf"]
    assert goals["koerper"].by == date(2027, 3, 31) and goals["erholung"].target == "range"
    assert goals["aktivitaeten"].by is None
    assert len(problems) == 4


def test_without_goals_only_today_and_safety_appear(tmp_path, monkeypatch, given):
    """Recommendations need a goal; without one, the levers stay empty even when a rule would fire."""
    data = write(tmp_path, monkeypatch, garmin=garmin_rows(sleep_hours=6.0, steps=4000))
    given(goals=None, sleep_hours=6.0, steps=4000)
    result = build(data)
    assert result["cards"] == [] and result["more"] == [] and result["goals"] == []


def test_weight_goal_shows_pace_forecast_and_the_missing_deficit(tmp_path, monkeypatch, given):
    """Losing 0.11 kg a week while 75 kg in 12 weeks needs about 0.27 kg: rule 3 asks for roughly 170 kcal less a day.

    The goal shows the distance, the pace and when the current pace would reach it.
    """
    by = TODAY + timedelta(weeks=12)
    data = write(tmp_path, monkeypatch, garmin=garmin_rows(weight_kg=lambda i, d: round(80.0 - 0.11 * i / 7, 2)))
    given(start_kg=80.0, pace_kg_per_week=-0.11, goal="75 kg", by=by.isoformat())
    result = build(data, goals={"koerper": {"metric": "weight", "target": 75, "by": by.isoformat()}})
    goal = result["goals"][0]
    assert goal["pace_per_week"] == pytest.approx(-0.11, abs=0.005)
    assert goal["needed_per_week"] == pytest.approx(-(78.18 - 75) / 12, abs=0.01)
    assert goal["status"] == "off-track" and date.fromisoformat(goal["eta"]) > by
    card = next(c for c in result["cards"] if c["rule"] == "weight-pace")
    assert card["kcal_per_day"] == pytest.approx((0.265 - 0.11) * 7700 / 7, abs=15)
    assert card["title"]["vars"] == [{"n": 170, "d": 0}]


def test_weight_rule_never_suggests_more_than_one_percent_a_week(tmp_path, monkeypatch, given):
    """A goal date that needs more than 1 % of body weight a week is capped at 1 %, and the card says so.

    Without YAZIO, intake is estimated from Garmin's expenditure (2,600 kcal at a stable weight); the
    880 kcal for 1 % would end below the resting energy of 1,800 kcal, so the card asks for 800.
    """
    by = TODAY + timedelta(weeks=4)
    data = write(tmp_path, monkeypatch)
    given(weight=80, goal="70 kg in 4 weeks")
    card = next(c for c in build(data, goals={"koerper": {"metric": "weight", "target": 70, "by": by.isoformat()}})["cards"]
                if c["rule"] == "weight-pace")
    assert card["kcal_per_day"] == 800
    assert "höchstens" in card["why"]["text"]


def test_no_weight_loss_advice_towards_a_bmi_below_20(tmp_path, monkeypatch, given):
    """Safety: a goal that would end below BMI 20 gets no weight-loss card."""
    by = TODAY + timedelta(weeks=30)
    data = write(tmp_path, monkeypatch)
    given(weight=80, bmi=24.7, goal="62 kg (BMI about 19)")
    result = build(data, goals={"koerper": {"metric": "weight", "target": 62, "by": by.isoformat()}})
    assert "weight-pace" not in rules(result)


def test_no_weight_loss_advice_without_bmi_or_energy_data(tmp_path, monkeypatch, given):
    """Safety fails closed: without a BMI, or without Garmin's resting energy, the limits cannot be checked, so no card."""
    by = TODAY + timedelta(weeks=8)
    goals = {"koerper": {"metric": "weight", "target": 75, "by": by.isoformat()}}
    given(cases="no BMI; no calories_total/calories_active")
    data = write(tmp_path, monkeypatch, garmin=garmin_rows(bmi=None))
    assert "weight-pace" not in rules(build(data, goals=goals))
    data = write(tmp_path, monkeypatch, garmin=garmin_rows(calories_total=None, calories_active=None))
    assert "weight-pace" not in rules(build(data, goals=goals))


def test_calorie_advice_never_goes_below_resting_metabolism(tmp_path, monkeypatch, given):
    """Safety: the suggested intake never falls below Garmin's resting energy (total minus active)."""
    by = TODAY + timedelta(weeks=4)
    food = [{"date": day(i).isoformat(), "calories_kcal": 1900, "protein_g": 140} for i in range(DAYS)]
    data = write(tmp_path, monkeypatch, food=food)
    given(intake_kcal=1900, resting_kcal=1800)
    card = next(c for c in build(data, goals={"koerper": {"metric": "weight", "target": 70, "by": by.isoformat()}})["cards"]
                if c["rule"] == "weight-pace")
    assert card["kcal_per_day"] == 100


# --------------------------------------------------------------------------- today


def test_today_card_on_low_readiness(tmp_path, monkeypatch, given):
    """Rule 1: readiness LOW today gives the Today card "locker statt schwer", also without goals."""
    data = write(tmp_path, monkeypatch, garmin=garmin_rows(
        readiness_level=lambda i, d: "LOW" if d == TODAY else "MODERATE", readiness_score=lambda i, d: 31 if d == TODAY else 70))
    given(readiness_today="LOW 31")
    today = build(data)["today"]
    assert today["title"]["text"] == "Heute locker statt schwer"
    assert today["reasons"][0] == {"text": "Readiness {0}", "vars": [{"n": 31, "d": 0}]}
    assert today["pause"] is False


def test_today_card_says_pause_when_it_looks_like_an_infection(tmp_path, monkeypatch, given):
    """Safety: resting HR up 5 bpm or more on 3 days and HRV well below range means "Pause", never "train easy"."""
    sick = lambda i, d: d >= TODAY - timedelta(days=6)  # noqa: E731
    data = write(tmp_path, monkeypatch, garmin=garmin_rows(
        resting_hr=lambda i, d: 58 if sick(i, d) else 50, hrv_last_night_ms=lambda i, d: 40 if sick(i, d) else 60))
    given(resting_hr="58 vs 50", hrv="40 vs range 50–70")
    today = build(data)["today"]
    assert today["title"]["text"] == "Heute Pause" and today["pause"] is True


def test_no_today_card_on_a_normal_day(tmp_path, monkeypatch, given):
    """Normal readiness, HRV in range, usual resting HR: no Today card."""
    data = write(tmp_path, monkeypatch)
    given(readiness="MODERATE", hrv="in range")
    assert build(data)["today"] is None


# --------------------------------------------------------------------------- blood pressure


def bp_rows(sys_, dia, count=6):
    return [{"date": (TODAY - timedelta(days=2 * k)).isoformat(), "time_local": "07:00", "systolic": sys_,
             "diastolic": dia} for k in range(count)]


def test_high_blood_pressure_only_advises_a_check_and_stops_experiments(tmp_path, monkeypatch, given):
    """Rule 14: from 140/90 on average, a safety card asks for a medical check and no experiment is offered."""
    insights = {"findings": [{"driver": "bedtime_min", "outcome": "hrv", "status": "robust", "effect": -2.0,
                              "effect_unit": "ms", "n": 90}]}
    data = write(tmp_path, monkeypatch, bp=bp_rows(146, 92), insights=insights)
    given(mean_bp="146/92", goal="erholung: hrv", robust_finding="bedtime -> HRV")
    result = build(data, goals={"erholung": {"metric": "hrv"}})
    assert [c["rule"] for c in result["safety"]] == ["blood-pressure-high"]
    assert not [c for c in result["cards"] + result["more"] if c["kind"] == "experiment"]


def test_elevated_blood_pressure_suggests_endurance_and_less_salt(tmp_path, monkeypatch, given):
    """Rule 19: 120–139/70–89 on average gives a lever card first in the list."""
    data = write(tmp_path, monkeypatch, bp=bp_rows(128, 82))
    given(mean_bp="128/82")
    result = build(data, goals={"erholung": {"metric": "resting_hr", "target": 46}})
    assert result["safety"] == [] and result["cards"][0]["rule"] == "blood-pressure-elevated"


def test_too_few_blood_pressure_readings_say_nothing(tmp_path, monkeypatch, given):
    """Fewer than 3 readings in 30 days are not enough for a mean."""
    data = write(tmp_path, monkeypatch, bp=bp_rows(150, 95, count=2))
    given(readings=2)
    assert build(data, goals={"erholung": {"metric": "hrv"}})["safety"] == []


# --------------------------------------------------------------------------- levers


def test_short_sleep_and_irregular_weekends(tmp_path, monkeypatch, given):
    """Rules 8 and 9: 6.5 h on average and a weekend sleep midpoint 2 h later than on weekdays."""
    def start(i, d):
        night = d - timedelta(days=1)
        return f"{(d if d.weekday() >= 5 else night).isoformat()} {'01:00' if d.weekday() >= 5 else '23:30'}"

    def end(i, d):
        return f"{d.isoformat()} {'09:00' if d.weekday() >= 5 else '06:00'}"

    data = write(tmp_path, monkeypatch, garmin=garmin_rows(sleep_hours=6.5, sleep_start_local=start, sleep_end_local=end))
    given(sleep_hours=6.5, weekdays="23:30–06:00", weekends="01:00–09:00")
    result = build(data, goals={"schlaf": {"metric": "sleep_hours", "target": 7.5}})
    assert {"sleep-duration", "sleep-regularity"} <= set(rules(result))


def test_protein_steps_and_weighing(tmp_path, monkeypatch, given):
    """Rules 4, 12 and 21: 1.2 g/kg protein, 6,000 steps and 2 weigh-ins a week each give a card."""
    food = [{"date": day(i).isoformat(), "calories_kcal": 2300, "protein_g": 96} for i in range(DAYS)]
    data = write(tmp_path, monkeypatch, food=food, garmin=garmin_rows(
        steps=6000, weight_kg=lambda i, d: 80.0 if d.weekday() in (0, 3) else None))
    given(protein="96 g at 80 kg", steps=6000, weigh_ins_per_week=2)
    result = build(data, goals={"koerper": {"metric": "weight", "target": 78}})
    assert {"protein", "steps", "weighing"} <= set(rules(result))
    steps = next(c for c in result["cards"] + result["more"] if c["rule"] == "steps")
    assert steps["title"]["vars"] == [{"n": 7000, "d": 0}]


def test_few_endurance_sessions_for_a_resting_hr_goal(tmp_path, monkeypatch, given):
    """Rule 6: one endurance session a week is below the 2–3 that lowered resting HR in studies."""
    data = write(tmp_path, monkeypatch, activities=endurance_rows(1))
    given(sessions_per_week=1, goal="resting HR 46")
    assert "endurance" in rules(build(data, goals={"erholung": {"metric": "resting_hr", "target": 46}}))
    data = write(tmp_path, monkeypatch, activities=endurance_rows(3))
    assert "endurance" not in rules(build(data, goals={"erholung": {"metric": "resting_hr", "target": 46}}))


def test_training_volume_names_the_muscle_groups_below_ten_sets(tmp_path, monkeypatch, given):
    """Rule 15: 12 sets of squats but only 4 of bench press a week flags the chest, not the quadriceps."""
    sets = []
    for i in range(DAYS):
        d = day(i)
        if d.weekday() == 0:
            sets += [{"date": d.isoformat(), "exercise": "Squat", "exercise_template_id": "SQ", "set_type": "normal",
                      "weight_kg": 100, "reps": 5}] * 12
            sets += [{"date": d.isoformat(), "exercise": "Bench Press", "exercise_template_id": "BP",
                      "set_type": "normal", "weight_kg": 70, "reps": 5}] * 4
    data = write(tmp_path, monkeypatch, sets=sets)
    given(quadriceps_sets_per_week=12, chest_sets_per_week=4)
    card = next(c for c in build(data, goals={"kraft": {"metric": "weekly_sets", "target": 10}})["cards"]
                if c["rule"] == "training-volume")
    assert card["muscles"] == ["chest"]


def test_at_most_three_cards_the_rest_one_level_deeper(tmp_path, monkeypatch, given):
    """Few instead of many: three cards in the area, further ones under "more", guidelines and studies first."""
    food = [{"date": day(i).isoformat(), "calories_kcal": 2300, "protein_g": 96} for i in range(DAYS)]
    data = write(tmp_path, monkeypatch, food=food, activities=endurance_rows(0),
                 garmin=garmin_rows(steps=5000, sleep_hours=6.0, weight_kg=lambda i, d: 80.0 if d.weekday() == 0 else None))
    given(protein="1.2 g/kg", steps=5000, sleep_hours=6.0, activities=0)
    result = build(data, goals={"koerper": {"metric": "weight", "target": 78},
                                "aktivitaeten": {"metric": "steps", "target": 10000},
                                "schlaf": {"metric": "sleep_hours", "target": 7.5}})
    assert len(result["cards"]) == 3 and len(result["more"]) >= 1
    order = {"guideline": 0, "B": 1, "data": 2, "C": 3}
    levels = [order[c["evidence"]] for c in result["cards"] + result["more"]]
    assert levels == sorted(levels)


def test_hidden_recommendations_stay_away_until_their_date(tmp_path, monkeypatch, given):
    """"Später" hides a card until a date, "Passt nicht" for good."""
    data = write(tmp_path, monkeypatch, garmin=garmin_rows(steps=5000, sleep_hours=6.0))
    goals = {"aktivitaeten": {"metric": "steps", "target": 10000}, "schlaf": {"metric": "sleep_hours", "target": 7.5}}
    hidden = {"steps": {"until": (TODAY + timedelta(days=3)).isoformat()}, "sleep-duration": {"dismissed": True}}
    given(hidden=hidden)
    assert {"steps", "sleep-duration"} <= set(rules(build(data, goals=goals)))
    assert not {"steps", "sleep-duration"} & set(rules(build(data, goals=goals, recommendations_hidden=hidden)))
    expired = {"steps": {"until": (TODAY - timedelta(days=1)).isoformat()}}
    assert "steps" in rules(build(data, goals=goals, recommendations_hidden=expired))


# --------------------------------------------------------------------------- experiments


def test_alcohol_experiment_when_hrv_is_lower_after_drinking(tmp_path, monkeypatch, given):
    """Rule 7: alcohol logged on 4 of 28 days and HRV 8 ms lower in the nights after: offered as a 14-day experiment."""
    drink = {day(i) for i in range(DAYS - 28, DAYS) if i % 7 == 0}
    lifestyle = [{"date": day(i).isoformat(), "behaviour_id": "11", "name": "Alcohol", "kind": "count",
                  "status": "yes" if day(i) in drink else "no", "value": 2 if day(i) in drink else 0}
                 for i in range(DAYS - 28, DAYS)]
    data = write(tmp_path, monkeypatch, lifestyle=lifestyle,
                 garmin=garmin_rows(hrv_last_night_ms=lambda i, d: 52 if d - timedelta(days=1) in drink else 60))
    given(alcohol_days=len(drink), hrv_after="52 vs 60")
    card = next(c for c in build(data, goals={"erholung": {"metric": "hrv"}})["cards"] if c["rule"] == "alcohol")
    assert card["kind"] == "experiment" and card["experiment"]["days"] == 14
    assert card["why"]["vars"][0] == {"n": 8.0, "d": 1}


def test_own_data_bedtime_finding_becomes_an_experiment(tmp_path, monkeypatch, given):
    """Rules 10 and 13: robust findings in insights.json become experiments, never facts; tendencies do not."""
    insights = {"findings": [
        {"driver": "bedtime_min", "outcome": "hrv", "status": "robust", "effect": -2.0, "effect_unit": "ms", "n": 90},
        {"driver": "training_load", "outcome": "hrv", "status": "robust", "effect": -3.1, "effect_unit": "ms",
         "effect_per": "100 points", "n": 80},
        {"driver": "steps", "outcome": "sleep_score", "status": "tendency", "effect": 1.0, "n": 70}]}
    data = write(tmp_path, monkeypatch, insights=insights)
    given(findings=insights["findings"])
    result = build(data, goals={"erholung": {"metric": "hrv"}, "schlaf": {"metric": "bedtime", "target": "22:45"}})
    cards = {c["rule"]: c for c in result["cards"] + result["more"]}
    assert cards["bedtime-hrv"]["title"]["vars"] == [{"clock": "22:45"}]
    assert cards["own-data"]["title"]["text"] == "Experiment: 14 Tage weniger {0}"
    assert all(cards[r]["kind"] == "experiment" for r in ("bedtime-hrv", "own-data"))


def test_experiment_result_needs_ten_days_per_phase(tmp_path, monkeypatch, given):
    """An experiment compares its days with as many days before: median and quartiles, only from 10 days per phase."""
    start = TODAY - timedelta(days=13)
    data = write(tmp_path, monkeypatch, garmin=garmin_rows(hrv_last_night_ms=lambda i, d: 66 if d >= start else 60))
    given(start=start.isoformat(), hrv="60 before, 66 during")
    done = recommend.evaluate_experiment(data, {"rule": "alcohol", "start": start.isoformat(), "days": 14,
                                                "metrics": ["hrv"]})
    assert done["status"] == "running" and done["elapsed"] == 14
    assert done["metrics"][0]["before"] == 60 and done["metrics"][0]["during"] == 66
    short = recommend.evaluate_experiment(data, {"rule": "alcohol", "start": (TODAY - timedelta(days=4)).isoformat(),
                                                 "metrics": ["hrv"]})
    assert "during" not in short["metrics"][0] and short["metrics"][0]["during_n"] == 5


def test_running_experiment_hides_its_card(tmp_path, monkeypatch, given):
    """While an experiment runs, its recommendation is not offered again; a finished one is not repeated."""
    insights = {"findings": [{"driver": "bedtime_min", "outcome": "hrv", "status": "robust", "effect": -2.0,
                              "effect_unit": "ms", "n": 90}]}
    data = write(tmp_path, monkeypatch, insights=insights)
    given(experiment="bedtime-hrv since 5 days")
    result = build(data, goals={"erholung": {"metric": "hrv"}},
                   experiments=[{"rule": "bedtime-hrv", "start": (TODAY - timedelta(days=4)).isoformat()}])
    assert "bedtime-hrv" not in rules(result) and result["experiments"][0]["status"] == "running"


# --------------------------------------------------------------------------- output


def test_output_is_valid_json_for_the_dashboard(tmp_path, monkeypatch, given):
    """run() writes recommendations.json without NaN, with the sources the cards cite."""
    write(tmp_path, monkeypatch, garmin=garmin_rows(steps=5000))
    monkeypatch.setattr(config, "SETTINGS", {"goals": {"aktivitaeten": {"metric": "steps", "target": 10000}}})
    given(steps=5000)
    recommend.run(TODAY)
    text = (tmp_path / "recommendations.json").read_text(encoding="utf-8")
    result = json.loads(text)
    assert "NaN" not in text and result["schema"] == 1
    cited = {s for c in result["cards"] + result["more"] for s in c["sources"]}
    assert cited <= set(result["sources"])


def test_daily_analysis_also_refreshes_the_recommendations(tmp_path, monkeypatch, given):
    """The data repository's workflow only calls `analyze`; that run writes recommendations.json as well."""
    from selftopo import __main__ as cli

    write(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "SETTINGS", {})
    given(command="python -m selftopo analyze")
    assert cli.main(["analyze"]) == 0
    assert (tmp_path / "insights.json").exists() and (tmp_path / "recommendations.json").exists()
