"""Relationship analysis

Statistical behaviour of the analysis: finds real effects, ignores noise, reads the CSV files.
"""

import json

import numpy as np
import pandas as pd
import pytest

from selftopo import analyze, config


def synthetic_days(n: int = 200, effect: float = 0.0, seed: int = 1) -> pd.DataFrame:
    """Random daily data; `effect` ms of HRV per load point in the following night."""
    rng = np.random.default_rng(seed)
    index = pd.date_range("2026-01-01", periods=n, freq="D")
    load = rng.gamma(2.0, 40.0, n)
    hrv = 55 + rng.normal(0, 4, n)
    hrv[1:] += effect * load[:-1]
    return pd.DataFrame({
        "training_load": load,
        "steps": rng.normal(9000, 2500, n),
        "hrv": hrv,
        "resting_hr": 48 + rng.normal(0, 1.5, n),
        "sleep_score": 80 + rng.normal(0, 6, n),
    }, index=index)


def find(result, driver, outcome, lag):
    return next(f for f in result["findings"]
                if (f["driver"], f["outcome"], f["lag_days"]) == (driver, outcome, lag))


def test_finds_an_injected_next_night_effect_with_the_right_size(given):
    """200 synthetic days in which every training-load point lowers the next night's HRV by 0.04 ms.

    The analysis must mark load → HRV one night later as robust, estimate about −4 ms per 100 load
    points, and must not report the same effect two nights later.
    """
    given(days=200, injected_effect="-0.04 ms HRV per load point, the following night", seed=1, window_days=180)
    result = analyze.analyze_frame(synthetic_days(effect=-0.04), days=180)
    finding = find(result, "training_load", "hrv", 1)
    assert finding["status"] == "robust"
    assert finding["effect"] == pytest.approx(-4.0, abs=1.5)  # -0.04 ms per point = -4 ms per 100 points
    assert find(result, "training_load", "hrv", 2)["status"] != "robust"  # no effect two nights later


def test_false_alarm_rate_on_pure_noise_stays_near_the_fdr_level(given):
    """On 40 data sets of pure noise, at most 20 % of the runs may report any robust finding.

    With Benjamini-Hochberg at q = 0.10 about 1 run in 10 is expected; clearly more would mean the
    dashboard presents chance as an insight.
    """
    runs = 40
    given(runs=runs, data="200 random days each, no real effect", seeds="100-139", fdr_q=0.10)
    with_alarm = sum(analyze.analyze_frame(synthetic_days(seed=100 + s), days=180)["robust"] > 0 for s in range(runs))
    assert with_alarm / runs <= 0.2


def test_circular_garmin_pairs_are_not_tested(given):
    """Pairs in which Garmin derives one value from the other are not tested.

    Sleep score → Training Readiness and stress → Body Battery correlate by construction, so a
    finding there would say nothing. Bedtime → readiness is a real question and stays in.
    """
    pairs = analyze.candidate_pairs()
    given(candidate_pairs=f"{len(pairs)} pairs from analyze.candidate_pairs()")
    assert ("sleep_score", "readiness", 0) not in pairs
    assert ("stress_avg", "body_battery", 1) not in pairs
    assert ("bedtime_min", "readiness", 0) in pairs


def test_output_is_valid_json_without_nan(given):
    """The analysis result is strict JSON: no NaN or Infinity, which the dashboard could not parse."""
    given(days=200, injected_effect="-0.04 ms HRV per load point", window_days=180)
    result = analyze.analyze_frame(synthetic_days(effect=-0.04), days=180)
    text = json.dumps(result, allow_nan=False)  # raises ValueError on NaN or Infinity
    assert json.loads(text)["findings"]


def test_empty_data_gives_a_note(given):
    """No data gives an empty list of findings instead of an error, for new users."""
    given(data="empty DataFrame")
    assert analyze.analyze_frame(pd.DataFrame())["findings"] == []


def test_load_daily_reads_all_three_files(tmp_path, monkeypatch, given):
    """The daily table combines Garmin days, Garmin activities and Hevy sets.

    Bedtime in minutes from midnight (negative before it), activity load summed per day and 0 on
    days without activity, hard sets without warm-ups and grip measurements, tonnage in tonnes,
    Body Battery falling back to the daily high.
    """
    (tmp_path / "garmin_daily.csv").write_text(
        "date,hrv_last_night_ms,sleep_start_local,body_battery_high\n"
        "2026-10-12,55,2026-10-11 23:30,80\n"
        "2026-10-13,52,2026-10-13 00:45,70\n"
        "2026-10-14,58,,75\n", encoding="utf-8")
    (tmp_path / "garmin_activities.csv").write_text(
        "date,duration_min,training_load\n2026-10-12,90,70\n2026-10-12,30,10\n", encoding="utf-8")
    (tmp_path / "hevy_sets.csv").write_text(
        "date,exercise,set_type,weight_kg,reps\n"
        "2026-10-13,Squat (Barbell),warmup,60,8\n"
        "2026-10-13,Squat (Barbell),normal,100,5\n"
        "2026-10-13,Squat (Barbell),normal,100,4\n"
        "2026-10-13,Right-hand Grip Strength,normal,52,1\n"
        "2026-10-13,left-hand grip strength ,normal,49,1\n", encoding="utf-8")
    given(**{path.name: path.read_text(encoding="utf-8") for path in sorted(tmp_path.glob("*.csv"))})
    monkeypatch.setattr(config, "GARMIN_CSV", tmp_path / "garmin_daily.csv")
    monkeypatch.setattr(config, "ACTIVITIES_CSV", tmp_path / "garmin_activities.csv")
    monkeypatch.setattr(config, "HEVY_CSV", tmp_path / "hevy_sets.csv")

    daily = analyze.load_daily()
    assert daily.loc["2026-10-12", "bedtime_min"] == -30  # 23:30 the evening before
    assert daily.loc["2026-10-13", "bedtime_min"] == 45
    assert daily.loc["2026-10-12", "training_load"] == 80  # two activities summed
    assert daily.loc["2026-10-13", "training_load"] == 0  # no activity counts as zero load
    assert daily.loc["2026-10-13", "hard_sets"] == 2  # warm-up and grip measurements excluded
    assert daily.loc["2026-10-13", "tonnage_t"] == pytest.approx(0.9)
    assert daily.loc["2026-10-14", "body_battery"] == 75  # falls back to the daily high


def test_nutrition_is_tested_against_the_following_night_and_next_training_day(given):
    """Nutrition is paired with the following night and the next day, not with two nights later.

    Protein → HRV one night later and calories → strength form the next day are tested; strength
    form one day later is labelled as the next day.
    """
    pairs = analyze.candidate_pairs()
    given(candidate_pairs=f"{len(pairs)} pairs from analyze.candidate_pairs()")
    assert ("protein_g", "hrv", 1) in pairs
    assert ("calories_kcal", "strength_form_pct", 1) in pairs
    assert ("protein_g", "hrv", 2) not in pairs
    assert analyze.timing("strength_form_pct", 1) == "next_day"


def test_incomplete_and_unlogged_food_days_stay_empty(tmp_path, monkeypatch, given):
    """Days without a YAZIO entry and days below 1200 kcal count as missing, not as low intake.

    Half-logged days would otherwise look like fasting and distort every nutrition finding.
    """
    monkeypatch.setattr(config, "GARMIN_CSV", tmp_path / "garmin_daily.csv")
    monkeypatch.setattr(config, "ACTIVITIES_CSV", tmp_path / "none.csv")
    monkeypatch.setattr(config, "HEVY_CSV", tmp_path / "none2.csv")
    monkeypatch.setattr(config, "NUTRITION_CSV", tmp_path / "nutrition_daily.csv")
    pd.DataFrame({"date": ["2026-10-01", "2026-10-02", "2026-10-03"], "hrv_last_night_ms": [50, 52, 54]}).to_csv(
        config.GARMIN_CSV, index=False)
    pd.DataFrame({"date": ["2026-10-01", "2026-10-03"], "calories_kcal": [2100, 800], "protein_g": [140, 30],
                  "carbs_g": [200, 90], "fat_g": [70, 30]}).to_csv(config.NUTRITION_CSV, index=False)
    given(**{path.name: path.read_text(encoding="utf-8") for path in sorted(tmp_path.glob("*.csv"))})
    daily = analyze.load_daily()
    assert daily.loc["2026-10-01", "protein_g"] == 140
    assert np.isnan(daily.loc["2026-10-02", "calories_kcal"])  # not logged
    assert np.isnan(daily.loc["2026-10-03", "protein_g"])  # below MIN_COMPLETE_KCAL: incomplete
