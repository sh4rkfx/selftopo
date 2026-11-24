"""Dashboard layout, accessibility and wording

Acceptance criteria of the UI stories that are fixed in the markup, the stylesheet or small
helpers: landmarks and the skip link, text and touch-target sizes, the tile grid, series colours
that never look like a verdict, collapsed areas, and the wording of notices. Read from
dashboard/index.html; the helpers run in Node, without Node those tests are skipped.
"""

# ruff: noqa: E501

import colorsys
import re

import pytest
from jsdashboard import HTML, run

_START = HTML.index("<style>", HTML.index("<style>") + 1)  # the first block only pads the page
CSS = HTML[_START:HTML.index("</style>", _START)]
BODY = HTML[HTML.index("</style>", _START):]


def _root_tokens(block: str) -> dict[str, str]:
    return dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})", block))


LIGHT = _root_tokens(CSS[CSS.index(":root {"):CSS.index("@media (prefers-color-scheme: dark)")])
DARK = _root_tokens(CSS[CSS.index(':root[data-theme="dark"]'):])


def _hue(hex_colour: str) -> tuple[float, float]:
    r, g, b = (int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, _l, s = colorsys.rgb_to_hls(r, g, b)
    return h * 360, s


# ---- Keyboard and screen readers (#82, #83)

def test_skip_link_comes_first_and_has_a_target(given):
    """The first thing in the page is *Zum Inhalt springen*, and the element it points to exists."""
    first = re.search(r"<(a|div|svg|header|nav|main)\b[^>]*>", BODY)
    link = re.search(r'<a class="skip-link" href="#([\w-]+)">([^<]+)</a>', BODY)
    given(first=first.group(0), link=link and link.groups())
    assert first.group(0).startswith('<a class="skip-link"')
    assert link.group(2) == "Zum Inhalt springen"
    assert f'id="{link.group(1)}"' in BODY


def test_one_main_landmark_and_named_navigation(given):
    """Exactly one `main`; the area navigation is a labelled `nav`."""
    mains = re.findall(r"<main\b", BODY)
    nav = re.search(r'<nav class="nav" id="nav" aria-label="([^"]+)"', BODY)
    given(mains=len(mains), nav=nav and nav.group(1))
    assert len(mains) == 1 and nav.group(1) == "Bereiche"


def test_wide_tables_are_reachable_by_keyboard(given):
    """Every wide table that scrolls sideways becomes a focusable, named region (WCAG 2.1.1)."""
    given(code="tabIndex 0, role region, aria-label from the card title")
    assert re.search(r'for \(const wrap of document\.querySelectorAll\("\.table-wrap\.wide"\)\)', HTML)
    block = HTML[HTML.index('for (const wrap of document.querySelectorAll(".table-wrap.wide"))'):][:600]
    assert "tabIndex: 0" in block and 'setAttribute("role", "region")' in block and "aria-label" in block


# ---- Navigation names every area (#74)

def test_every_area_link_has_a_visible_label(given):
    """Each link of the area navigation carries its name as text, not only an icon and a tooltip."""
    nav = BODY[BODY.index('<nav class="nav"'):BODY.index("</nav>")]
    links = re.findall(r"<a href=\"#([\w-]+)\"[^>]*>.*?</a>", nav)
    labels = re.findall(r'<span class="lbl">([^<]+)</span>', nav)
    given(links=links, labels=labels)
    assert len(links) >= 10 and len(labels) == len(links)


# ---- Text and touch-target sizes (#79, #84)

def test_no_text_below_12_px(given):
    """Every font size is at least 0.75rem (12 px); the only exception is the glyph inside a state dot."""
    sizes = re.findall(r"([^{}]+)\{[^}]*?font-size:\s*([0-9.]+)(rem|px)", CSS)
    small = [(sel.strip()[-40:], v + u) for sel, v, u in sizes if (float(v) * (16 if u == "rem" else 1)) < 12]
    given(small=small)
    assert small == [(".pill .dot", "0.625rem")]


def test_touch_targets_reach_44_px_on_phones(given):
    """On phones and touch screens buttons, header tools and info buttons reach a 44 px hit area."""
    block = CSS[CSS.index("@media (max-width: 759px), (pointer: coarse) {"):]
    block = block[:block.index("\n}\n")]
    given(rules=[r.strip() for r in block.splitlines() if "44" in r])
    assert ".primary-btn, .ghost-btn { min-height: 44px; }" in block
    assert ".top-tools .icon-btn { width: 44px; height: 44px; }" in block
    assert "inset: calc(50% - 22px)" in block  # info and area toggle buttons
    assert ".seg button { min-height: 44px; }" in block


# ---- Tiles and large text (#73, #80)

def test_tile_grid_two_four_five_columns(given):
    """Two columns on phones, four from 640 px, five (ten tiles) only from 1000 px; widths in rem."""
    given(css="tiles")
    assert "@media (min-width: 640px) { .tiles { grid-template-columns: repeat(4, minmax(0, 1fr)); } }" in CSS
    assert "@media (min-width: 1000px) { .tiles.ten { grid-template-columns: repeat(5, minmax(0, 1fr)); } }" in CSS
    assert re.search(r"\.tiles \{[^}]*minmax\(min\(100%, [0-9.]+rem\)", CSS)


# ---- Colours: a data series never looks like a verdict (#76)

@pytest.mark.parametrize("theme", ["light", "dark"])
def test_series_colours_are_not_status_colours(given, theme):
    """Series 1–5 differ from the good, fair and poor colours: away from green, amber and red, or grey."""
    tokens = LIGHT if theme == "light" else {**LIGHT, **DARK}
    status = [_hue(tokens[k])[0] for k in ("good", "warn", "crit")]
    report = {}
    for k in ("s1", "s3", "s4", "s5"):
        hue, sat = _hue(tokens[k])
        nearest = min(min(abs(hue - h), 360 - abs(hue - h)) for h in status)
        report[k] = (round(hue), round(sat, 2), round(nearest))
    given(theme=theme, series=report)
    assert all(nearest >= 30 or sat < 0.25 for _hue_, sat, nearest in report.values())


# ---- Overview and areas (#75, #78)

def test_areas_start_collapsed_on_every_width(given):
    """Without a stored choice every area starts collapsed, phones and wide screens alike."""
    given(code="(saved ?? AREAS)")
    assert "for (const area of (saved ?? AREAS)" in HTML
    assert '(onPhone() ? "healthsync.collapsed.phone" : "healthsync.collapsed.wide")' in HTML


def test_an_open_area_shows_two_cards_first(given):
    """On wide screens an area shows its first two cards; the rest waits behind *Weitere n Karten zeigen*."""
    core = run(["CORE_CARDS"], "CORE_CARDS")
    given(core=core)
    assert core == 2
    assert 'T("Weitere {0} Karten zeigen", [n])' in HTML and 'T("1 weitere Karte zeigen")' in HTML


# ---- One verdict per metric (#72)

@pytest.mark.parametrize(("metric", "status", "expected"), [
    ("weight", "on-track", ["good", "auf Kurs"]),
    ("weight", "off-track", ["warn", "zu langsam"]),
    ("hrv", "off-track", ["warn", "außerhalb"]),
    ("hrv", "reached", ["good", "im Bereich"]),
    ("bedtime", "off-track", ["warn", "noch nicht"]),
    ("steps", "no-data", ["none", "keine Daten"]),
])
def test_goal_verdict_is_one_word_for_tile_card_and_conclusion(given, metric, status, expected):
    """Tile pill, goal card and area conclusion take their level and word from the same goalBadge()."""
    got = run(["GOAL_STATE", "goalBadge"], f'goalBadge({{ metric: "{metric}", status: "{status}" }})')
    given(metric=metric, status=status, badge=got)
    assert got == expected


# ---- Connection errors (#71, #86)

def test_connection_error_never_shows_sample_data(given):
    """A failed load shows an error with *Erneut versuchen*; sample data only without a connection set up."""
    block = HTML[HTML.index("function renderConnectionError()"):][:1500]
    given(code="renderConnectionError")
    assert "makeDemoData" not in block
    assert 'T("Ohne Verbindung zeigt die Seite keine Werte, auch keine Beispieldaten.")' in block
    assert 'T("Erneut versuchen")' in block


def test_network_error_keeps_the_last_good_data_marked_offline(given):
    """A network error after a good load keeps that data, marked offline, for the same repository only."""
    given(code="lastGithubLoad")
    assert "if (data.network && lastGithubLoad?.repo === cred.repo)" in HTML
    assert "offlineSince: lastGithubLoad.at" in HTML


# ---- Wording (#77, #81, #85)

def test_wording_of_estimates_and_sample_data(given):
    """Expenditure says it comes from the log; the scale's estimate says so; the sample notice says it is made up."""
    given(texts=["Verbrauch laut deinem Log", "Fett und Muskeln laut Waage", "Alle Werte sind erfunden"])
    assert "Tatsächlicher Verbrauch" not in HTML
    assert "<h3>Verbrauch laut deinem Log</h3>" in HTML
    assert "<h3>Fett und Muskeln laut Waage</h3>" in HTML
    assert "Alle Werte sind erfunden." in HTML and "etwa 15 Minuten" in HTML


def test_scale_composition_trend_is_folded_away(given):
    """The 28-day fat and muscle chart sits in a closed `details`, below the weight."""
    i = HTML.index("<h3>Fett und Muskeln laut Waage</h3>")
    block = HTML[i:i + 1500]
    given(block=re.findall(r"<details[^>]*>", block))
    assert re.search(r'<details class="daily comp-more">', block) and 'id="c-comp"' in block


# ---- Criteria of the 2.0.0 stories that had no test yet

def _contrast(a: str, b: str) -> float:
    def lum(h):
        c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_muted_text_is_readable_in_the_light_theme(given):
    """Muted and secondary text reach 4.5:1 on the page and on cards (WCAG AA)."""
    ratios = {f"{t} on {b}": round(_contrast(LIGHT[t], LIGHT[b]), 2) for t in ("muted", "ink-2") for b in ("page", "surface")}
    given(ratios=ratios)
    assert min(ratios.values()) >= 4.5


def test_font_sizes_follow_the_browser_setting(given):
    """Text sizes are in rem, so they grow with the browser's font size; px only for chart labels inside the SVG."""
    px = re.findall(r"([^{}]+)\{[^}]*?font-size:\s*[0-9.]+px", CSS)
    given(px=[p.strip() for p in px])
    assert {p.strip() for p in px} == {".tick", ".end-label", ".ref-label", ".axis-title"}


def test_readiness_is_named_as_a_level(given):
    """Garmin's readiness reads *Stufe mittel*, not a bare *Mittel* that looks like a 7-day mean."""
    got = run(["READINESS_LABELS", "readinessLevelText"], '["MODERATE", "LOW", "PRIME", null].map(readinessLevelText)')
    given(levels=got)
    assert got == ["Stufe mittel", "Stufe niedrig", "Stufe optimal", ""]


def test_relationships_are_worded_as_correlations(given):
    """No *führt zu* or *verursacht* as a claim; the glossary names Pearson r for charts and Spearman ρ for findings."""
    # The glossary's own negation, "nicht ob einer den anderen verursacht", is the one allowed use
    claims = re.findall(r"führt zu|(?<!den anderen )verursacht", BODY)
    glossary = BODY[BODY.index("<dt>r und ρ</dt>"):][:700]
    given(claims=claims)
    assert claims == []
    assert "nicht ob einer den anderen verursacht" in glossary
    assert "r (Pearson)" in glossary and "ρ (Spearman)" in glossary


@pytest.mark.parametrize(("value", "digits", "text"), [(-0.04, 1, "0,0"), (-2e-17, 0, "0"), (-0.06, 1, "−0,1"), (1234.5, 1, "1.234,5")])
def test_no_minus_sign_on_values_that_round_to_zero(given, value, digits, text):
    """fmt() drops the sign when only zeros remain; other values keep it, as a true minus sign."""
    got = run(["nf", "fmt"], f"fmt({value}, {digits})")
    given(value=value, text=got)
    assert got == text


def test_current_area_is_marked_in_the_navigation(given):
    """The highlighted area link carries aria-current, which the bar's caption and screen readers follow."""
    given(css='.nav a[aria-current="true"]')
    assert '.nav a[aria-current="true"]' in CSS and 'a.getAttribute("aria-current") === "true"' in HTML


def test_unusual_comes_before_the_tiles_and_a_calm_week_is_one_line(given):
    """*Auffällig diese Woche* sits above the tiles; with nothing unusual the card is calm (list hidden, compared values in ⓘ)."""
    notable, tiles = BODY.index('id="notable"'), BODY.index('id="tiles"')
    given(notable_before_tiles=notable < tiles)
    assert notable < tiles
    assert '$("notable").classList.toggle("calm", !odd.length);' in HTML
    assert ".notable.calm .notable-list { display: none; }" in CSS
    assert 'T("Verglichen werden diese Woche: {0}."' in HTML


def test_every_scatter_chart_names_its_y_axis(given):
    """Each scatter chart passes a yTitle with its unit; the top margin grows only when one is set."""
    calls = [HTML[m.start():m.start() + 600] for m in re.finditer(r"scatterChart\(host, \{", HTML)]
    given(calls=len(calls))
    assert len(calls) >= 5 and all("yTitle: T(" in c for c in calls)
    assert "t: o.yTitle ? 24 : 10" in HTML


def test_single_extreme_days_do_not_stretch_the_axis(given):
    """With clipOutliers and at least 20 points, values beyond 3 interquartile ranges do not set the axis."""
    given(rule="Tukey far out")
    assert "if (!o.clipOutliers || dots.length < 20) return () => true;" in HTML
    assert "return (v) => v >= q1 - 3 * iqr && v <= q3 + 3 * iqr;" in HTML


def test_only_ranges_the_data_can_fill_are_offered(given):
    """A range at least as long as the data shows the same as *Alles* and is not offered."""
    got = run(["DAY", "dataSpanDays", "rangeAvailable"],
              "(() => { globalThis.state = { model: { t0: 0, t1: 199 * DAY } }; return [7, 28, 84, 365, 0].map(rangeAvailable); })()")
    given(available=got)
    assert got == [True, True, True, False, True]
