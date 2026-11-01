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
pytest            # parsers, settings, analysis, dashboard dictionary
ruff check .      # lint, line length 120
```

The dashboard needs no build: run `python -m http.server 8000` in the repository root and open
<http://localhost:8000/dashboard/>. With a `data/` folder next to it, the page shows those files;
without one, it shows generated sample data. `?lang=en` or `?lang=de` switches the language.

The GitHub workflow `Tests` runs `ruff` and `pytest` on every push and pull request.

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
`dashboard/sw.js`, so installed apps drop their old copy.

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

1. Update `CHANGELOG.md`.
2. Tag the release and move the major tag the workflows follow:
   `git tag v1.2.0 && git tag -f v1 && git push origin v1.2.0 && git push -f origin v1`.
3. Create a GitHub release for the tag with the changelog entry.
4. If the data repository template changed, copy `templates/data-repo/` to
   `sh4rkfx/selftopo-data-template`.

Breaking changes to the data format or settings need a new major version (`v2`), which users opt
into with the repository variable `SELFTOPO_CODE_REF`.
