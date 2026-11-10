"""Where the dashboard opens

The page opens at the overview. A link opened fresh (#kraft) jumps to its area; a reload ignores
both the area in the address and the old scroll position. Runs the page's own startPosition in Node
with a stand-in browser; without Node these tests are skipped.
"""

from jsdashboard import run

BROWSER = """
globalThis.calls = [];
globalThis.location = { hash: HASH, pathname: "/selftopo/dashboard/", search: "" };
globalThis.history = { replaceState: (s, t, url) => { calls.push(["replace", url]); location.hash = ""; } };
globalThis.window = { scrollTo: (x, y) => calls.push(["scroll", y]) };
globalThis.requestAnimationFrame = (f) => f();
globalThis.knownTarget = (id) => ["kraft", "ernaehrung", "top"].includes(id);
globalThis.goTo = (id, push) => calls.push(["goTo", id, push]);
"""


def start(hash: str, reload: bool):
    setup = BROWSER.replace("HASH", repr(hash))
    return run(["startPosition"], f"(() => {{ {setup} startPosition({str(reload).lower()}); return calls; }})()")


def test_reload_starts_at_the_overview(given):
    """Refreshing after clicking Ernährung: no jump to Ernährung, the address loses #ernaehrung."""
    given(address="#ernaehrung", navigation="reload")
    assert start("#ernaehrung", reload=True) == [["replace", "/selftopo/dashboard/"], ["scroll", 0]]


def test_reload_without_area_starts_at_the_top(given):
    """A reload of the plain address scrolls to the top instead of the old position."""
    given(address="(none)", navigation="reload")
    assert start("", reload=True) == [["scroll", 0]]


def test_link_to_an_area_still_opens_it(given):
    """A bookmark or shared link like #kraft, opened fresh, goes to that area and keeps the address."""
    given(address="#kraft", navigation="navigate")
    assert start("#kraft", reload=False) == [["goTo", "kraft", False]]


def test_unknown_area_opens_the_overview(given):
    """An old or mistyped anchor is dropped and the page starts at the top."""
    given(address="#gibtsnicht", navigation="navigate")
    assert start("#gibtsnicht", reload=False) == [["replace", "/selftopo/dashboard/"], ["scroll", 0]]


def test_scroll_restoration_is_switched_off():
    """Without this, the browser puts a reloaded page back where it was scrolled, often further down."""
    from jsdashboard import SCRIPT

    assert 'history.scrollRestoration = "manual"' in SCRIPT
