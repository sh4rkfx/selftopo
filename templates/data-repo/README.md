# selftopo data

Personal data for [selftopo](https://github.com/sh4rkfx/selftopo): Garmin Connect daily
metrics and activities, Hevy sets and the relationship analysis.

> [!TIP]
> Looking at the template? Click **Use this template → Create a new repository** and choose
> **Private**, or let the dashboard's setup guide (*Set up your own data*, gear icon → *Setup*) prefill everything.

> [!IMPORTANT]
> Keep this repository **private**. Every file here is health data, and whatever is committed
> stays in the Git history.

| File | Content |
|---|---|
| `garmin_daily.csv` | One row per day: weight, sleep, HRV, resting heart rate, Body Battery, steps, readiness |
| `garmin_activities.csv` | One row per watch activity |
| `garmin_climbs.csv` | One row per boulder logged on the watch: grade, completed or attempted, route timer, heart rate |
| `garmin_climb_sessions.csv` | One row per bouldering session: boulders, tops, time on the wall, self evaluation |
| `garmin_blood_pressure.csv` | One row per blood pressure reading |
| `garmin_fitness.csv` | VO2max, race predictions, hill and endurance score per day |
| `garmin_fitness_status.json` | Today's training status, loads, load focus and fitness age |
| `hevy_sets.csv` | One row per set |
| `hevy_exercises.csv` | Muscle groups of the exercises used |
| `nutrition_daily.csv` | Optional, from YAZIO: calories, protein, carbohydrates, fat and water per logged day |
| `insights.json` | Result of `python -m selftopo analyze` |
| `settings.json` | Your settings: time zone, step goal, main lifts, grip-strength exercises. Edit it in the dashboard under gear icon → *General* |

The workflow in `.github/workflows/sync.yml` runs every morning. It checks out the public
selftopo code at the tag `v2` (the newest 2.x release), fetches the last 30 days and commits
changed files. Repository variables change that: `SELFTOPO_CODE_REF` (`main` for the development
state, or an exact tag such as `v2.0.0`) and `SELFTOPO_CODE_REPO` (your fork).

*Run workflow* takes optional inputs: `days`, `source` (for example `climbs` with `days` 2000 to
load older bouldering sessions without touching the other sources) and a date for a raw dump of
the Garmin or YAZIO responses of one day. The dump is attached to the run as a private artifact
and expires after a day.

## Secrets

Under *Settings → Secrets and variables → Actions → Repository secrets*:

| Secret | Value |
|---|---|
| `GARMIN_TOKENS_JSON` | Output of `python -m selftopo export-tokens` |
| `GARMIN_EMAIL`, `GARMIN_PASSWORD` | Alternative without Python, for accounts without two-step verification: the workflow logs in itself and caches the tokens. Delete `GARMIN_PASSWORD` after the first successful run |
| `HEVY_API_KEY` | Hevy API key from hevy.com/settings?developer |
| `YAZIO_TOKENS_JSON` | Optional. Output of `python -m selftopo yazio-tokens`. Without it, YAZIO is skipped |
| `YAZIO_EMAIL`, `YAZIO_PASSWORD` | Optional alternative: the workflow logs in itself. Delete `YAZIO_PASSWORD` after the first successful run |

## Working locally

Clone this repository into the `data/` folder of the code checkout. The code repository ignores
`data/`, so nothing in here can end up there by accident.

```bash
git clone https://github.com/sh4rkfx/selftopo.git
git clone https://github.com/<you>/selftopo-data.git selftopo/data
```

Run `git -C data pull` before opening the dashboard locally. After a local `sync`, discard the
changes with `git -C data restore .` before pulling, or commit them yourself.
