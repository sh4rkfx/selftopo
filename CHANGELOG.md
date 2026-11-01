# Changelog

All notable changes. Versions follow [semantic versioning](https://semver.org): within 1.x, data
files and settings stay compatible. The workflow in each data repository follows the tag `v1`.

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

### Project

- Data repository template `sh4rkfx/selftopo-data-template`, MIT license, contributing guide,
  security policy.
