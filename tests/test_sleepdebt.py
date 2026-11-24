"""Sleep debt

The last four nights against the sleep need (goal or 8 hours): shortfalls add up, a longer night
pays back, never below zero; old nights do not count. The helper runs in Node; without Node these
tests are skipped.
"""

# ruff: noqa: E501

import json

from jsdashboard import run

DAY = 86_400_000
TODAY = 1_795_478_400_000  # Tue 24.11.2026, 00:00 UTC
HELPERS = ["DAY", "SLEEP_NEED_H", "sleepDebt"]  # SLEEP_NEED_H also declares DEBT_NIGHTS


def debt(hours, need=None, start=TODAY):
    days = [{"t": start - (len(hours) - 1 - i) * DAY, "sleepH": h} for i, h in enumerate(hours)]
    arg = "" if need is None else f", {need}"
    return run(HELPERS, f"sleepDebt({json.dumps(days)}, {TODAY}{arg})")


def test_shortfalls_of_four_nights_add_up(given):
    """7 + 7.5 + 6.5 + 7 hours against 8: 1 + 0.5 + 1.5 + 1 = 4 hours of debt."""
    given(nights=[7, 7.5, 6.5, 7])
    assert debt([7, 7.5, 6.5, 7]) == {"debtH": 4, "needH": 8, "nights": 4}


def test_only_the_last_four_nights_count_and_a_long_night_pays_back(given):
    """A short fifth night back is ignored; 9 hours pays back one; never below zero."""
    given(nights=[4, 7, 9, 8, 8])
    assert debt([4, 7, 9, 8, 8])["debtH"] == 0
    assert debt([9, 9, 9, 9])["debtH"] == 0


def test_need_follows_the_goal(given):
    """With a goal of 7 hours, 6.5 hours a night is 2 hours of debt."""
    given(goal=7)
    assert debt([6.5] * 4, need=7)["debtH"] == 2


def test_old_or_missing_nights_give_no_debt(given):
    """Fewer than four nights in the last six days: no value instead of a wrong one."""
    given(case="data ends 4 days ago")
    assert debt([6, 6, 6, 6], start=TODAY - 4 * DAY) is None
    assert debt([6, 6, 6]) is None
