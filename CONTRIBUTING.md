# Contributing to selftopo

Thanks for helping. Bug reports, field mappings for other Garmin devices, new cards, translations
and documentation are all welcome.

## Before you start

- **Never post health data.** Not in issues, pull requests, test fixtures or screenshots. Use the
  dashboard's sample data (open it without a connection) for screenshots, and replace real values
  in raw dumps before you share them.
- For larger changes, open an issue first and describe the problem you want to solve. That saves
  work on both sides.
- Security problems: see [SECURITY.md](SECURITY.md), not a public issue.

## Development setup

```bash
git clone https://github.com/sh4rkfx/selftopo.git && cd selftopo
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest            # parsers, settings, analysis, dashboard dictionary and helpers; writes test-results/results.json
ruff check .      # lint, line length 120
```

Tests of the dashboard's pure helpers (tile colours, summary, time axis) cut those functions out of
`dashboard/index.html` and run them in Node.js (`tests/jsdashboard.py`); GitHub's runners have Node.
Without Node they are skipped. A helper that touches the page or the data files stays untested there.

The dashboard needs no build: run `python -m http.server 8000` in the repository root and open
<http://localhost:8000/dashboard/>. With a `data/` folder next to it, the page shows those files;
without one, it shows generated sample data. `?lang=en` or `?lang=de` switches the language.

The GitHub workflow `Tests` runs `ruff` and `pytest` on every push and pull request. On `main` it
publishes the results to the branch `test-results`, which the test page `dashboard/tests.html` reads.

## Tests

Tests are plain pytest. A small plugin, `tests/report_plugin.py`, records each run for the test
page, so a test needs a little more than an assert to be useful there:

```python
@pytest.mark.critical  # only if a failure can store wrong values, lose data or break a login
def test_hevy_dates_use_local_time(given):
    """A Hevy workout at 22:30 UTC counts for the next day in Vienna (00:30), not the day before."""
    workout = {...}
    given(workout=workout, timezone="Europe/Vienna")
    (row,) = hevy.flatten(workout)
    assert row["date"] == "2026-10-14"
```

- **Name:** a sentence in snake case; the page shows *Hevy dates use local time*.
- **Docstring:** what the test checks and why it matters, in one or two sentences. The page shows it
  as *What it checks*.
- **Inputs:** pass the values the code under test receives to the `given` fixture. Parameters of
  `pytest.mark.parametrize` are recorded on their own.
- **Checks:** write `assert actual == expected`, actual on the left. Every executed assert and every
  `with pytest.raises(...)` is recorded with its expected and actual value; asserts not reached
  after a failure are listed as well.
- **Critical:** `@pytest.mark.critical`, or `pytestmark = pytest.mark.critical` for a whole file,
  when a failure means wrong or lost data or a broken or leaking login. One failing critical test
  turns the page red.
- **Group:** the first line of a test file's module docstring is the heading of its group on the
  page, the rest the description.

Run `pytest`, then `python -m http.server 8000` and open
<http://localhost:8000/dashboard/tests.html> to see the page for your local run. If passing asserts
do not show up there after changing `enable_assertion_pass_hook`, delete `tests/__pycache__`.

## Code

- Code, comments, commit messages and documentation are in English.
- Python: standard library plus the packages in `requirements.txt`; keep new dependencies to a
  minimum. Parsing functions are pure and tested; network calls stay in `sync` functions.
- Garmin's field names are undocumented. For a new or changed mapping, run
  `python -m selftopo dump-raw --date YYYY-MM-DD`, then add a parser test with a small, anonymized
  fixture built from the dump.
- Data format: within 1.x, new columns and files are fine, but do not rename or remove existing
  ones. The dashboard must cope with missing files and empty columns, because users update the code
  and their data at different times.

## Dashboard and translations

`dashboard/index.html` holds the whole dashboard. The user interface text is written in German
in the code; English comes from the dictionary in the script block `i18n-en`.

- **Text in the script:** wrap it in `T()`: `T("Keine Daten")`. Values go in numbered
  placeholders: `T("{0} von {1} Tagen", [n, total])`. When one German word needs two English
  translations, pass a context: `T("Mittel", null, "endurance")` looks up `endurance|Mittel` first.
- **Text in the HTML:** nothing to wrap. Each element whose own text sits next to inline markup
  is translated as a whole, keyed by its normalized `innerHTML`; icons are written as `⟨i⟩`.
- **English entry:** add the German key and the English text to the `i18n-en` block. Keep
  placeholders, `⟨i⟩` and inline tags exactly as in the key.
- **Check:** `pytest tests/test_dashboard.py` catches script text without an entry. For HTML
  text, open the page with `?lang=en`, show every info box and look at
  `window.selftopoI18nMissing` in the browser console: it lists everything still German.

After changing `index.html`, `manifest.webmanifest` or the icons, raise `VERSION` in
`dashboard/sw.js`, so installed apps drop their old copy. `tests.html` has its own small German and
English dictionary in its script (`EN`).

Design rules the dashboard follows: green, yellow and red only for states past a threshold that
is explained in the card's ⓘ; numbers come with their unit; every card says where its data comes
from; claims rest on cited studies or on the user's own baseline, not on guesses.

## Pull requests

- One topic per pull request, with a description of what changes for the user and why.
- Tests and lint pass. New parsing or calculation logic has a test.
- User-facing text exists in German and English.
- Screenshots of dashboard changes use sample data, on a phone width and a desktop width.
- The README and `docs/` describe the change if users or contributors need to know about it.

Commit messages: a short summary in the imperative (*Add grip strength card*), then, if needed, a
body that explains why.

## Releases (maintainers)

1. Update `CHANGELOG.md` and push it to `main`; wait for the tests.
2. Publish a GitHub release with a new tag such as `v2.1.0` on `main` and the changelog entry as
   notes. The workflow *Move major tag* then points `v2` at it, and every data repository uses the
   new version with its next run.
3. If the data repository template changed, copy `templates/data-repo/` to
   `sh4rkfx/selftopo-data-template`.

Breaking changes to the data format or settings need a new major version (`v3`), which users opt
into with the repository variable `SELFTOPO_CODE_REF`.
