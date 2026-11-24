# Changelog

All notable changes, one version per change. Versions follow
[semantic versioning](https://semver.org): a new feature raises the minor version, a fix or a
wording change the patch version; within a major version, data files and settings stay
compatible. The workflow in each data repository follows the tag of its major version (`v2`,
before that `v1`).

## 2.16.1 – 2026-11-24

[#138](https://github.com/sh4rkfx/selftopo/pull/138)

### Project

- Every merged version is published by itself: after the tests pass on `main`, the new workflow
  *Release* tags each version of this changelog on the squash commit of its pull request,
  publishes it as a GitHub release with its entry as notes, and moves `v2` to the newest one
  (`tools/release.py`). Each version names its pull request. Started by hand, it catches up on
  versions without a release.

## 2.16.0 – 2026-11-24

[#136](https://github.com/sh4rkfx/selftopo/pull/136)

### Project

- Every change gets its own version, a GitHub release and a user story with acceptance criteria
  that tests cover; see *Versions and updates* in the README and *Pull requests* in
  CONTRIBUTING.md. The 27 changes since 2.0.0 got their versions after the fact (2.1.0–2.15.0).
- The version shows under gear icon → *App* → *About selftopo*, with a link to its release notes;
  `python -m selftopo --version` prints it. `selftopo.__version__`, the dashboard and this file
  are kept equal by a test.
- New tests for acceptance criteria that had none: skip link and landmarks, text and touch-target
  sizes, tile grid, series colours, collapsed areas, one verdict per goal, connection errors,
  wording, and the sync time in the header.

## 2.15.0 – 2026-11-24

[#95](https://github.com/sh4rkfx/selftopo/pull/95)

### Befunde

- Reports without readable text (photos, scans) can be read by the Claude API. With the secret
  `ANTHROPIC_API_KEY`, the new data-repository workflow *Read reports* sends each new file in
  `files/` once and adds its values as proposals; the card shows them per file to accept or
  discard (`python -m selftopo evaluate-reports`, ledger `report_evaluations.json`). Existing data
  repositories do not get the workflow by themselves: copy
  [templates/data-repo/.github/workflows/reports.yml](templates/data-repo/.github/workflows/reports.yml)
  to `.github/workflows/reports.yml` in your data repository and add the secret.

## 2.14.0 – 2026-11-24

[#94](https://github.com/sh4rkfx/selftopo/pull/94)

### Befunde

- *Befund hochladen*: a PDF, JPG or PNG goes to `files/` in the data repository. For a PDF with
  text the dashboard reads the values in the browser (resting metabolic rate and RER, lab VO2max,
  DEXA, waist, lab lines with reference ranges) and the report date, and lists them for review
  before they count. pdf.js comes from a copy next to the dashboard, not from a CDN.

## 2.13.0 – 2026-11-24

[#93](https://github.com/sh4rkfx/selftopo/pull/93)

### Befunde

- *Befund eintragen* adds a value with checks for date, unit and plausible range (the RER goes
  with the resting metabolic rate); every entry can be edited or deleted. With a read-only token
  the dialog gives the CSV lines to paste on GitHub.

## 2.12.0 – 2026-11-24

[#92](https://github.com/sh4rkfx/selftopo/pull/92)

### Befunde

- *Befunde* under Rohdaten: values from labs and tests in a new `measurements.csv` (resting
  metabolic rate with RER, waist, DEXA, lab VO2max, blood values with the report's reference
  range), newest per measure, with links to report files.

## 2.11.0 – 2026-11-24

[#91](https://github.com/sh4rkfx/selftopo/pull/91)

### Dashboard

- Sleep debt: the Schlaf area shows how far the last 4 nights fell short of your sleep-duration
  goal (otherwise 8 hours), net of longer nights and never below zero; yellow from 2 hours.

## 2.10.0 – 2026-11-24

[#90](https://github.com/sh4rkfx/selftopo/pull/90)

### Sync

- `dump-yazio` also saves the day's single entries and up to five of their products and recipes,
  to find where YAZIO keeps fibre and other nutrients. The sync itself is unchanged.

## 2.9.0 – 2026-11-24

[#89](https://github.com/sh4rkfx/selftopo/pull/89)

### Dashboard

- When the dashboard opens after 08:00 and no sync has run today, it starts one itself and the
  header shows *GitHub · Abruf läuft …*; at most once in 3 hours per browser. Without the Actions
  permission it pauses for a week. Off under gear icon → *Connection* → *Sync automatically in
  the morning*.

## 2.8.6 – 2026-11-24

[#88](https://github.com/sh4rkfx/selftopo/pull/88)

### Dashboard

- English dates name the month (*Tue 24 Nov*, push: *31 Mar*) instead of *24/11*.

## 2.8.5 – 2026-11-24

[#87](https://github.com/sh4rkfx/selftopo/pull/87)

### Project

- The changelog lists the dashboard changes of 2.2.1–2.8.4.

## 2.8.4 – 2026-11-24

[#86](https://github.com/sh4rkfx/selftopo/pull/86)

### Dashboard

- Fixes from the review of the UI changes: after a good load a network error keeps that data,
  marked offline; the steps tile counts days against your steps goal; a resting-HR goal is shown
  even without a baseline; tiles without a value count as *ohne Wert*, not as neutral.

## 2.8.3 – 2026-11-24

[#85](https://github.com/sh4rkfx/selftopo/pull/85)

### Dashboard

- *Tatsächlicher Verbrauch* is now *Verbrauch laut deinem Log*, since it inherits whatever the
  food log misses; neutral tiles are called neutral.

## 2.8.2 – 2026-11-24

[#84](https://github.com/sh4rkfx/selftopo/pull/84)

### Dashboard

- No text below 12 px; chart margins grow to fit their labels.

## 2.8.1 – 2026-11-24

[#83](https://github.com/sh4rkfx/selftopo/pull/83)

### Dashboard

- A `main` landmark, a named first column in the sleep table, and wide tables that can be
  scrolled with the keyboard.

## 2.8.0 – 2026-11-24

[#82](https://github.com/sh4rkfx/selftopo/pull/82)

### Dashboard

- A skip link *Zum Inhalt springen* past the area navigation.

## 2.7.3 – 2026-11-24

[#81](https://github.com/sh4rkfx/selftopo/pull/81)

### Dashboard

- The sample-data notice explains what the page is and that setting it up takes about 15 minutes.

## 2.7.2 – 2026-11-24

[#80](https://github.com/sh4rkfx/selftopo/pull/80)

### Dashboard

- Tablets show four tiles per row, five only from 1000 px.

## 2.7.1 – 2026-11-24

[#79](https://github.com/sh4rkfx/selftopo/pull/79)

### Dashboard

- Every control on phones reaches a 44 px hit area.

## 2.7.0 – 2026-11-24

[#78](https://github.com/sh4rkfx/selftopo/pull/78)

### Dashboard

- Wide screens start with all areas collapsed, like phones; an opened area shows two cards and
  *Weitere n Karten zeigen*. Körper starts with weight and loss pace.

## 2.6.0 – 2026-11-24

[#77](https://github.com/sh4rkfx/selftopo/pull/77)

### Dashboard

- The scale's fat and muscle estimate is a 28-day trend in a folded card, *Fett und Muskeln laut
  Waage*; the chips next to the weight are gone.

## 2.5.1 – 2026-11-24

[#76](https://github.com/sh4rkfx/selftopo/pull/76)

### Dashboard

- Data series 3–5 are violet, magenta and slate, so no series looks like a green, amber or red
  verdict.

## 2.5.0 – 2026-11-24

[#75](https://github.com/sh4rkfx/selftopo/pull/75)

### Dashboard

- Overview: *Auffällig diese Woche* comes before the tiles and is one line when nothing stands
  out. Good tiles keep the neutral card and say *gut* only in their pill; yellow and red still
  fill the card.

## 2.4.0 – 2026-11-24

[#74](https://github.com/sh4rkfx/selftopo/pull/74)

### Dashboard

- Navigation names every area in words; range, refresh and settings sit in the header row on
  every width, help too except on phones, where it is in the footer and the settings.

## 2.3.1 – 2026-11-24

[#73](https://github.com/sh4rkfx/selftopo/pull/73)

### Dashboard

- Header, tiles and area headings reflow at 200 % text size instead of overflowing.

## 2.3.0 – 2026-11-24

[#72](https://github.com/sh4rkfx/selftopo/pull/72)

### Dashboard

- One verdict per metric: with a goal (weight, HRV, resting HR, bedtime, sleep hours, steps) the
  tile shows the goal's state (*Ziel: zu langsam*), the same word as the goal card. Area
  conclusions start with what is off and then say what is unremarkable compared with your last
  four months.

## 2.2.1 – 2026-11-24

[#71](https://github.com/sh4rkfx/selftopo/pull/71)

### Dashboard

- A connection error shows an error page, never the sample data.

## 2.2.0 – 2026-11-13

[#70](https://github.com/sh4rkfx/selftopo/pull/70)

### Dashboard

- The header shows when the data was last fetched (*GitHub · synced yesterday 15:32*) instead of
  only when the page loaded, which moves to the tooltip. It turns yellow when the last sync is
  older than 30 hours and names sources that failed. GitHub often starts the scheduled run hours
  late; *Sync now* under gear icon → *Connection* starts it right away and reloads the page when
  it is done. That needs *Actions: Read and write* on the dashboard token; new tokens are
  prefilled with it.

### Sync

- Every `sync` writes `data/sync_status.json`: start, end, trigger, a link to the GitHub run and
  each source's result with the time of its last success. The existing workflow commits it like
  the other data files; nothing in the data repository needs changing.

## 2.1.0 – 2026-11-10

[#69](https://github.com/sh4rkfx/selftopo/pull/69)

### Dashboard

- *Save* writes `settings.json` to the data repository directly when the dashboard token has
  *Contents: Read and write*: settings, goals, recommendation choices, push notifications and main
  lifts. It reads the current file first, so changes from other devices stay. With a read-only
  token, saving by hand on GitHub works as before. New tokens are prefilled with write access.

## 2.0.0 – 2026-11-10

New major version because the data repository gets a new workflow (push notifications, input
`push_test`, follows `v2`). Data files and `settings.json` of 1.x stay valid as they are; nothing
needs converting.

### Upgrade from 1.x

1. Copy [templates/data-repo/.github/workflows/sync.yml](templates/data-repo/.github/workflows/sync.yml)
   over `.github/workflows/sync.yml` in your data repository. It checks out `v2`.
   Without that step your workflow stays on `v1` (1.0.0); setting the repository variable
   `SELFTOPO_CODE_REF` to `v2` also works, just without push notifications.
2. Optional: push notifications, see [docs/push.md](docs/push.md).

### Recommendations

- Goals in `settings.json`, one per area, with pace and forecast.
- Rules 1–17 and 19–21 of the recommendation catalogue with their sources and safety limits;
  relationships in your own data only as 14-day experiments. `python -m selftopo analyze` writes
  `recommendations.json`; `python -m selftopo recommend` runs the rules alone.
  See [docs/recommendations.md](docs/recommendations.md).
- Push notifications: the Today card on the installed dashboard, sent by the daily workflow
  (`python -m selftopo push-keys`, secret `VAPID_PRIVATE_KEY`, new workflow step and input
  `push_test`; copy the workflow template into existing data repositories). See
  [docs/push.md](docs/push.md).

### Sync

- Garmin Lifestyle Logging in `garmin_lifestyle.csv` (source `lifestyle`).

### Dashboard

- New area *Empfehlungen* (first in the bar, key 1; the keys of the other areas move up by one),
  Today card at the top of the overview, goals under gear icon → *General*.
- Design D: tiles filled by state with a pill, warmer palette, summary of the states.
- Weight tile coloured by WHO BMI class, calorie tile by energy balance.
- One-week range; ranges the data cannot fill are left out.
- Accessibility: contrast of muted and green text in the light theme, touch targets of 44 px,
  text sizes in rem so the browser's text size applies.
- Orientation: the current area is named under the icon bar; a reload opens at the overview
  instead of the old scroll position or the last area in the address.
- Texts: relationships worded as correlations, Readiness as a level, no repeated numbers under
  the chips, a short calm message in *Notable this week*, r and ρ explained.
- Charts: y-axis captions on scatter charts, no "−0,0", single extreme calorie days no longer
  stretch the axis.

## 1.0.0 – 2026-11-01

First public release.

### Sync

- Garmin Connect: daily values (weight and body composition, sleep with times, HRV, resting heart
  rate, Body Battery, stress, steps, calories, Training Readiness), activities, bouldering with
  one row per boulder and per session, blood pressure, VO2max, race predictions, Hill and
  Endurance Score, training status, load focus and fitness age.
- Hevy: sets and exercise templates with muscle groups; grip-strength readings kept separate.
- YAZIO (optional, unofficial): daily calories, protein, carbohydrates, fat and water.
- Garmin login in the workflow with `GARMIN_EMAIL` and `GARMIN_PASSWORD` for accounts without
  two-step verification, or with tokens from a local login; tokens are carried in the Actions cache.
- `settings.json` in the data repository: time zone, step goal, main lifts, grip exercises.
- Relationship analysis: about 100 pairs, Spearman correlation of deviations from the 28-day mean,
  Theil-Sen effects, Benjamini-Hochberg correction.

### Dashboard

- Overview tiles for the last 7 days and *Notable this week*: weekly values outside the 5th to
  95th percentile of your own previous 120 days.
- Areas Body, Nutrition, Recovery, Sleep, Sport (strength and bouldering), Fitness, Activities and
  Insights, each with chips that link to their cards and a conclusion: what is unusual, the period
  in one sentence and the strongest robust finding.
- Raw data with weekly and daily tables and a glossary.
- Ranges of 4 weeks, 12 weeks, 1 year and all.
- Settings overlay: language, personal settings saved via GitHub, connection with file status,
  guided setup, app.
- German and English, numbers and dates per language.
- Installable as an app, offline copy of the last loaded data.

### Tests

- Test page `dashboard/tests.html`, linked in the footer and the settings: overall traffic light
  (critical tests, 10 % limit), per test what it checks, inputs, every check with expected and
  actual value, duration, source link; history of the last 30 runs, newly failed and fixed tests,
  flaky and slower tests, slowest tests. German and English.
- 52 tests with descriptions and inputs; 39 marked critical (stored values, data loss, logins).
- The workflow *Tests* publishes the results to the branch `test-results`, also when tests fail.

### Project

- Data repository template `sh4rkfx/selftopo-data-template`, MIT license, contributing guide,
  security policy.
