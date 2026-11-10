"""Recommendations in the dashboard

The Today card computed in the browser, the texts from recommendations.json and the goals in
settings.json as the page reads them. The helpers run in Node; without Node these tests are
skipped. Every German text the Python rules write has an English translation.
"""

# ruff: noqa: E501

import ast
import json
import re
from pathlib import Path

from jsdashboard import HTML, run

ROOT = Path(__file__).resolve().parent.parent


def today(**values):
    base = {"level": "MODERATE", "readiness": 70, "hrv7": 60, "hrvLow": 50, "rhr7": 50, "rhr60": 50, "lastRhr": [50, 50, 50]}
    return run(["todayRule"], f"todayRule({json.dumps({**base, **values})})")


def test_today_card_matches_the_python_rule(given):
    """Same triggers as rule_today in selftopo/recommend.py: low readiness, or HRV below range with resting HR 5 bpm up."""
    given(cases="normal, readiness LOW, HRV low + RHR +5, HRV low + RHR +3")
    assert today() is None
    low = today(level="LOW", readiness=31)
    assert low["title"]["text"] == "Heute locker statt schwer" and low["reasons"] == [{"text": "Readiness {0}", "vars": [{"n": 31, "d": 0}]}]
    both = today(hrv7=46, rhr7=55.2)
    assert both is not None and [r["text"] for r in both["reasons"]] == ["HRV {0} ms unter deinem Bereich ab {1}", "Ruhepuls {0} bpm über deinem 60-Tage-Mittel"]
    assert today(hrv7=46, rhr7=53) is None


def test_today_card_says_pause_on_the_infection_pattern(given):
    """Resting HR 5 bpm up on each of the last 3 days and HRV below 92 % of the range: "Pause", never "train easy"."""
    given(rhr="56, 57, 58 vs 50", hrv="44 vs range from 50")
    card = today(hrv7=44, rhr7=57, lastRhr=[56, 57, 58])
    assert card["pause"] is True and card["title"]["text"] == "Heute Pause"
    assert today(hrv7=44, rhr7=57, lastRhr=[50, 57, 58])["pause"] is False


def test_texts_from_the_file_are_formatted_for_the_language(given):
    """Numbers with their decimals, dates, clock times, muscle groups and lists, filled into the German template."""
    helpers = ["nf", "fmt", "fmtDate", "ddmm", "isoToT", "MUSCLE_LABELS", "recoValue", "recoText"]
    text = {"text": "Für {0} kg bis {1}: {2} pro Woche, vor {3}; {4}",
            "vars": [{"n": 75, "d": 1}, {"date": "2027-03-31"}, {"n": -0.229, "d": 2}, {"clock": "23:00"}, {"list": [{"muscle": "chest"}, {"muscle": "quadriceps"}]}]}
    given(text=text)
    assert run(helpers, f"recoText({json.dumps(text)})") == "Für 75,0 kg bis 31.03.: −0,23 pro Woche, vor 23:00; Brust, Quadrizeps"
    assert run(helpers, 'recoText(null)') == ""


def test_goals_in_settings_are_checked_like_in_python(given):
    """One goal per area; unknown areas or metrics, bad targets and dates are reported, the rest is kept."""
    goals = {"koerper": {"metric": "weight", "target": 75, "by": "2027-03-31"}, "erholung": {"metric": "hrv"},
             "schlaf": {"metric": "bedtime", "target": "11pm"}, "garten": {"metric": "weight", "target": 1},
             "fitness": {"metric": "vo2max", "target": 47, "by": "bald"}}
    given(goals=goals)
    result = run(["goalMetric", "GOAL_METRICS", "readGoals"], f"(() => {{ const p = []; return [readGoals({json.dumps(goals)}, p), p.length]; }})()")
    kept, problems = result
    assert sorted(kept) == ["erholung", "fitness", "koerper"] and kept["fitness"]["by"] is None and problems == 3
    assert kept["erholung"] == {"metric": "hrv", "target": None, "by": None}


def test_goal_metrics_match_the_python_rules(given):
    """The dashboard offers exactly the areas and metrics selftopo/recommend.py accepts."""
    from selftopo import recommend

    offered = run(["GOAL_METRICS"], "Object.fromEntries(Object.entries(GOAL_METRICS).map(([a, ms]) => [a, ms.map((m) => m[0])]))")
    given(offered=offered)
    assert offered == {area: list(metrics) for area, metrics in recommend.GOAL_METRICS.items()}


def _python_texts() -> set[str]:
    tree = ast.parse((ROOT / "selftopo" / "recommend.py").read_text(encoding="utf-8"))
    texts = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "text" and node.args and isinstance(node.args[0], ast.Constant):
            texts.add(node.args[0].value)
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values, strict=True):
                if isinstance(k, ast.Constant) and k.value == "t" and isinstance(v, ast.Constant):
                    texts.add(v.value)
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) in ("OWN_DATA_DRIVERS", "OUTCOME_NAMES", "EFFECT_PER"):
            texts.update(v.value for v in node.value.values)
    return texts


def test_every_text_of_the_rules_has_an_english_translation(given):
    """recommendations.json carries German templates; the dashboard's dictionary must translate every one, or English shows German."""
    dictionary = json.loads(re.search(r'<script type="application/json" id="i18n-en">(.*?)</script>', HTML, re.S).group(1))
    texts = _python_texts()
    given(templates=len(texts))
    missing = sorted(t for t in texts if t not in dictionary)
    assert not missing, missing[:10]
    placeholders = [t for t in texts if sorted(re.findall(r"\{\d+\}", t)) != sorted(re.findall(r"\{\d+\}", dictionary[t]))]
    assert not placeholders
