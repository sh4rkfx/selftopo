# Changelog

All notable changes. Versions follow [semantic versioning](https://semver.org): within a major
version, data files and settings stay compatible. The workflow in each data repository follows
the tag of its major version (`v2`, before that `v1`).

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
