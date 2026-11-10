"""Overview tiles and time range

Weight coloured by BMI, calories by energy balance, tiles filled by state with a summary above
them (design D), and the one-week range. The helpers run in Node; without Node these tests are
skipped.
"""

# ruff: noqa: E501

import re

import pytest
from jsdashboard import HTML, run

DAY = 86_400_000


@pytest.mark.parametrize(("bmi", "level"), [
    (None, ""), (17.9, "crit"), (18.5, "good"), (24.9, "good"), (25.0, "warn"), (29.9, "warn"), (30.0, "crit"), (34.2, "crit"),
])
def test_weight_tile_follows_bmi_classes(given, bmi, level):
    """Green from 18.5 to under 25, yellow from 25 to under 30, red from 30 and under 18.5; no BMI, no colour."""
    given(bmi=bmi)
    assert run(["bmiLevel"], f"bmiLevel({'null' if bmi is None else bmi})") == level


@pytest.mark.parametrize(("balance", "level"), [(None, ""), (-335, "good"), (-1, "good"), (0, ""), (1, "crit"), (420, "crit")])
def test_calorie_tile_follows_the_energy_balance(given, balance, level):
    """Intake below expenditure (negative balance) is green, above it red; exactly even or unknown stays white."""
    given(balance_kcal_per_day=balance)
    assert run(["balanceLevel"], f"balanceLevel({'null' if balance is None else balance})") == level


def test_summary_counts_states_in_order_and_skips_zero(given):
    """The chips above the tiles read poor, fair, good, then not rated, and leave out states no tile has."""
    levels = ["good", "", "crit", "good", "", "", "crit", "good", "", ""]
    given(tile_levels=levels)
    assert run(["tileSummary"], f"tileSummary({levels!r})".replace("'", '"')) == [
        {"level": "crit", "n": 2}, {"level": "good", "n": 3}, {"level": "none", "n": 5}]
    assert run(["tileSummary"], "tileSummary([])") == []


def test_every_state_has_an_icon_and_a_word(given):
    """Colour is never the only signal: good, fair and poor each have their own icon and word."""
    states = run(["TILE_STATE"], "Object.fromEntries(Object.entries(TILE_STATE).map(([k, v]) => [k, [v.icon, v.word(), v.sum(3)]]))")
    given(states=states)
    assert states == {"good": ["check", "gut", "3 gut"], "warn": ["mid", "mittel", "3 mittel"], "crit": ["alert", "schlecht", "3 schlecht"]}
    icons = set(re.findall(r'<symbol id="i-([a-z-]+)"', HTML))
    assert {"check", "mid", "alert"} <= icons


def test_one_week_is_the_first_range(given):
    """The range control starts with 1 week, before 4 and 12 weeks, 1 year and everything."""
    ranges = run(["RANGES"], "RANGES")
    given(ranges=ranges)
    assert [r["days"] for r in ranges] == [7, 28, 84, 365, 0]
    assert ranges[0]["label"] == "1 Woche"


def test_week_axis_has_a_tick_per_day(given):
    """In the one-week view every day gets its own date tick; four weeks keep one tick per week."""
    x0 = 1_762_128_000_000  # Mon 03.11.2025, 00:00 UTC
    helpers = ["DAY", "dow", "fmtDate", "ddmm", "timeTicks"]
    week = run(helpers, f"timeTicks({x0}, {x0 + 6 * DAY}).map((t) => t.label)")
    given(start="2025-11-03", days=7)
    assert week == ["03.11.", "04.11.", "05.11.", "06.11.", "07.11.", "08.11.", "09.11."]
    month = run(helpers, f"timeTicks({x0}, {x0 + 27 * DAY}).length")
    assert month == 4


def _tokens(block: str) -> dict[str, str]:
    return dict(re.findall(r"--(st-[a-z]+-[a-z]+):\s*(#[0-9a-f]{6})", block))


def _contrast(a: str, b: str) -> float:
    def lum(h):
        c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_state_colours_are_readable_in_light_and_dark(given):
    """Text on a filled tile has at least 4.5:1 contrast (WCAG AA), in light mode and both dark-mode blocks."""
    css = HTML[:HTML.index("</style>", HTML.index("--st-good-bg"))]
    light = _tokens(css[css.index(":root {"):css.index("@media (prefers-color-scheme: dark)")])
    dark_auto = _tokens(css[css.index("@media (prefers-color-scheme: dark)"):css.index(':root[data-theme="dark"]')])
    dark = _tokens(css[css.index(':root[data-theme="dark"]'):])
    ratios = {f"{mode} {s}": round(_contrast(t[f"st-{s}-ink"], t[f"st-{s}-bg"]), 2)
              for mode, t in (("light", light), ("dark", dark)) for s in ("good", "warn", "crit")}
    given(contrast=ratios)
    assert dark_auto == dark, "the two dark-mode blocks must define the same state colours"
    assert min(ratios.values()) >= 4.5


def test_fonts_of_design_d_are_loaded(given):
    """Inter for text, Space Grotesk for headings and tile values, IBM Plex Mono for chart labels."""
    link = re.search(r'href="(https://fonts.googleapis.com/css2[^"]+)"', HTML).group(1)
    given(stylesheet=link)
    assert all(f"family={f}" in link for f in ("Inter", "Space+Grotesk", "IBM+Plex+Mono"))
