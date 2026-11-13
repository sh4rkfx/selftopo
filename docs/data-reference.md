# Data reference

All files live in `data/` (or `SELFTOPO_DATA_DIR`). Locally that is the clone of the private
data repository; in the data repository itself they sit at the root. CSV files are UTF-8 with a
header row; empty fields mean the value was not available.

## garmin_daily.csv

One row per calendar day. Overnight values belong to the night that ends on this date.

| Column | Unit | Notes |
|---|---|---|
| `date` | YYYY-MM-DD | Local calendar day |
| `weight_kg`, `fat_mass_kg`, `muscle_mass_kg`, `bone_mass_kg` | kg | First weigh-in of the day. `fat_mass_kg` is derived from weight and body fat % |
| `body_fat_pct`, `body_water_pct` | % | Bioimpedance estimates, use as weekly trends only |
| `bmi` | kg/m² | |
| `sleep_score` | 0–100 | |
| `sleep_hours` | h | Total sleep time |
| `sleep_start_local`, `sleep_end_local` | YYYY-MM-DD HH:MM | Falling asleep and waking up in the configured time zone (`timezone` in `settings.json`). On travel days this is home time |
| `deep_sleep_min`, `light_sleep_min`, `rem_sleep_min`, `awake_min` | min | Sleep stages |
| `hrv_last_night_ms`, `hrv_weekly_avg_ms` | ms | Overnight HRV average and Garmin's 7-day average |
| `hrv_status` | text | e.g. `BALANCED`, `UNBALANCED`, `LOW` |
| `hrv_baseline_low_ms`, `hrv_baseline_high_ms` | ms | Garmin's personal balanced range |
| `resting_hr` | bpm | |
| `body_battery_wake` | 0–100 | At wake-up, if Garmin provides it |
| `body_battery_high`, `body_battery_low` | 0–100 | Daily maximum and minimum |
| `body_battery_charged`, `body_battery_drained` | points | Gained and used during the day |
| `stress_avg` | 0–100 | Empty if Garmin had too little data |
| `steps` | count | |
| `calories_total`, `calories_active` | kcal | Garmin's estimate of energy burned: total (resting + active) and active only |
| `readiness_score` | 0–100 | Morning value; Garmin recalculates readiness after activities |
| `readiness_level` | text | e.g. `HIGH`, `MODERATE`, `LOW` |

## garmin_activities.csv

One row per activity recorded on the watch.

| Column | Unit | Notes |
|---|---|---|
| `date`, `start_time_local` | | Local date and time where the activity took place |
| `activity_id` | | Garmin Connect ID |
| `type` | text | Garmin type key, e.g. `bouldering`, `hiking`, `gravel_cycling`, `running`, `strength_training` |
| `name` | text | Activity name as shown in Garmin Connect |
| `duration_min`, `moving_min` | min | Total and moving time |
| `distance_km` | km | Empty for activities without distance |
| `elevation_gain_m` | m | |
| `avg_hr`, `max_hr` | bpm | |
| `calories` | kcal | |
| `training_load` | points | Garmin's EPOC-based load, comparable across sports |
| `aerobic_te`, `anaerobic_te` | 0–5 | Training Effect |
| `location` | text | If Garmin provides it |

Sport-specific details are not part of the activity list. For bouldering they are fetched
separately, see the next two files. `dump-raw` saves the full details of a day's activities.

## garmin_climbs.csv

One row per boulder logged on the watch in bouldering mode: grade chosen before the boulder,
LAP after it, then *Completed* or *Attempted*. Fetched per session from the activity's typed
splits (`CLIMB_ACTIVE`), so the `activities` source has to run first. Sessions of the last
`CLIMB_REFRESH_DAYS` (7) days are fetched again on every sync, because grades can still be
edited in Garmin Connect.

| Column | Unit | Notes |
|---|---|---|
| `date`, `activity_id` | | Session the boulder belongs to |
| `climb_no` | | 1, 2, 3 … in the order climbed |
| `start_time_local` | | When the route timer started |
| `grade` | text | As shown on the watch, e.g. `6B+` or `V4` |
| `grade_scale` | text | Garmin's name of the grading system, e.g. `VERMIN` for the V scale |
| `grade_order` | | Garmin's sort order within the scale; higher is harder |
| `status` | text | `completed` (top) or `attempted` |
| `duration_s` | s | Route timer |
| `rest_after_s` | s | Rest until the next boulder; empty after the last one |
| `avg_hr`, `max_hr` | bpm | During the boulder |

A session recorded without LAP has a single split as long as the whole session, with the grade set
at the start and status `completed`. The dashboard treats splits longer than 15 minutes as such a
session, not as a boulder.

Garmin does not know which boulder in the gym an entry is. Three falls and a top on the same
boulder are four rows, and a repeat of a boulder from last week is a new row.

## garmin_climb_sessions.csv

One row per bouldering session, also for sessions without logged boulders.

| Column | Unit | Notes |
|---|---|---|
| `date`, `activity_id`, `start_time_local` | | As in garmin_activities.csv |
| `climbs`, `completed`, `attempted` | count | Logged boulders, tops, attempts without top |
| `wall_s`, `rest_s` | s | Sum of route timers and of rests between boulders |
| `effort` | 1–10 | Perceived effort from the watch's self evaluation after saving; empty if skipped |
| `feel` | 0–100 | Feel from the same evaluation: 0 very weak, 25 weak, 50 normal, 75 strong, 100 very strong |

## garmin_blood_pressure.csv

One row per blood pressure reading in Garmin Connect, from a cuff such as the Index BPM or entered
by hand. The watch does not measure blood pressure. Each sync replaces the window it fetched;
notes typed with a reading are not copied.

| Column | Unit | Notes |
|---|---|---|
| `date`, `time_local` | | Local date and time of the reading |
| `systolic`, `diastolic` | mmHg | |
| `pulse` | bpm | If the device measures it |
| `source` | text | Garmin's source type, e.g. `DEVICE` or `MANUAL` |
| `category` | text | Garmin's own category; the dashboard uses the ESC 2024 home thresholds instead |

## garmin_lifestyle.csv

Lifestyle Logging, the habit diary of the Garmin Connect app (*More → Health Stats → Lifestyle
Logging*): one row per behaviour and day. Garmin lists every behaviour you have set up on every
day, answered or not. One request per day; days already stored are only fetched again within the
last few days, because answers are often logged the next morning. A day fetched with nothing set
up is kept as a row with only its `date`, so it is not asked for again. As long as no behaviour
has ever been found, the sync stops after 7 empty days in a row, so not using Lifestyle Logging
costs only the requests for the newest few days per run.

> **Not yet checked against real data.** Garmin does not document this endpoint; the mapping
> follows the `garminconnect` library and other projects that read it. If the file stays empty or
> looks wrong, run `python -m selftopo dump-raw --date YYYY-MM-DD` and look at the `lifestyle` part.

| Column | Unit | Notes |
|---|---|---|
| `date` | | Calendar day of the log |
| `behaviour_id` | | Garmin's id of the behaviour; stays the same when you rename it. `#n` if the answer has none |
| `name` | text | Name as shown in the app, e.g. `Alcohol` or `Late caffeine` (depends on the app language) |
| `kind` | | `check` (yes/no) or `count` (an amount, e.g. drinks) |
| `status` | | `yes`, `no`, or empty when not answered that day |
| `value` | | `1`/`0` for yes/no; for `count` the sum of the logged amounts (a yes without amount is `1`); empty when not answered. Empty is not the same as `0` |
| `sleep_related` | | `1` if Garmin marks the behaviour as relevant for sleep |

## garmin_fitness.csv

One row per day on which Garmin reports at least one of these values. Each sync replaces the
window it fetched (at most 365 days, the limit of the race predictor).

| Column | Unit | Notes |
|---|---|---|
| `date` | | |
| `vo2max`, `vo2max_cycling` | ml/kg/min | Only on days the watch updated the estimate |
| `race_5k_s`, `race_10k_s`, `race_half_s`, `race_marathon_s` | s | Garmin's race predictor, daily |
| `hill_score`, `hill_strength`, `hill_endurance` | 0–100 | |
| `endurance_score` | points | Weekly mean on the week's first day, today's value on today |
| `acute_load`, `chronic_load`, `acwr`, `fitness_age`, `training_status` | | Only reported for today, so their history starts with the first sync |

## garmin_fitness_status.json

Today's training status, acute and chronic load with Garmin's suitable chronic range, the load
focus of the last four weeks with target ranges, fitness age with its components, and the
endurance score's level limits. Overwritten on every sync.

## hevy_sets.csv

One row per set.

| Column | Notes |
|---|---|
| `date` | Local calendar day of the workout start |
| `start_time` | Workout start, UTC, ISO 8601 |
| `workout_id`, `workout_title` | Title as set in Hevy, used by the dashboard to compare workouts |
| `exercise_index`, `exercise` | Position and name within the workout |
| `exercise_template_id` | Stable exercise ID; unlike the name it survives renames |
| `set_index`, `set_type` | `set_type` is `normal`, `warmup`, `dropset` or `failure`. Everything except `warmup` counts as a hard set |
| `weight_kg`, `reps`, `rpe` | |
| `duration_s`, `distance_m` | For timed or cardio sets |

The exercises listed under `grip_exercises` in `settings.json` (default „Right-hand Grip Strength“
and „Left-hand Grip Strength“, or „Handkraft rechts“ and „Handkraft links“) hold grip-strength
measurements, one set per try with the dynamometer reading as `weight_kg` and 1 rep.
They are left out of hard sets, tonnage and strength form in the analysis and the dashboard.

## hevy_exercises.csv

One row per exercise template used in `hevy_sets.csv`, from the Hevy API: `exercise_template_id`,
`title`, `type`, `primary_muscle_group`, `secondary_muscle_groups` (joined with `|`), `is_custom`.

## nutrition_daily.csv

Optional, from YAZIO (unofficial app API). One row per day with at least one food or water entry;
days without entries have no row. Calories, protein, carbohydrates and fat are the sums over all
meals of the day.

| Column | Notes |
|---|---|
| `date` | Local calendar day |
| `calories_kcal` | Energy intake. Empty on days with water entries but no food |
| `protein_g`, `carbs_g`, `fat_g` | Grams per day, rounded to 0.1 |
| `water_ml` | Logged water intake |

A partly logged day is indistinguishable from a day of low intake. The dashboard and the analysis
therefore treat days under 1,200 kcal (`MIN_COMPLETE_KCAL`) and the running day as not fully
logged and leave them out of means, the energy balance and the tests. Check the mapping against
your data with `python -m selftopo dump-yazio --date <day>` after the first login.

## recommendations.json

Written by `python -m selftopo analyze` (and `recommend`) from the goals in `settings.json`, the
CSV files and `insights.json`. Format, rules and thresholds: [recommendations.md](recommendations.md).

## sync_status.json

Written by every `python -m selftopo sync`, also when a source fails. Times are UTC in ISO 8601.

| Field | Meaning |
|---|---|
| `schema` | Format version, currently 1 |
| `started_at`, `finished_at` | Start and end of the last run |
| `trigger` | `schedule` or `workflow_dispatch` on GitHub, another GitHub event name, or `local` |
| `run_url` | Link to the run on GitHub; `null` for local runs |
| `sources.<name>.result` | `ok`, `failed` or `skipped` (YAZIO without setup) in the last run that included the source |
| `sources.<name>.at` | End of that run |
| `sources.<name>.last_ok` | End of the last run in which the source succeeded |

A run of a single source (`--source hevy`) updates only that source; the others keep their entry.

## insights.json

Written by `python -m selftopo analyze`. Method: [analysis.md](analysis.md).

| Field | Content |
|---|---|
| `generated_at` | UTC timestamp of the run |
| `period` | `start`, `end` and `days` of the analysis window |
| `method` | Short description of correlation, effect size and correction |
| `coverage` | Days with a value per variable inside the window |
| `tested`, `skipped_too_few_days`, `robust` | Counts of pairs |
| `findings` | One entry per tested pair, sorted by status, q and strength |

Each finding:

| Field | Example | Content |
|---|---|---|
| `driver`, `driver_label` | `bedtime_min`, "Bedtime" | What varies first |
| `outcome`, `outcome_label` | `hrv`, "Overnight HRV" | What is affected |
| `lag_days`, `timing` | `0`, `same_night` | `same_night`, `next_night`, `second_night` or `same_day` |
| `n` | `175` | Days used |
| `rho` | `-0.32` | Spearman correlation of the detrended values, -1 to 1 |
| `effect`, `effect_unit`, `effect_per` | `-2.0`, `ms`, "1 hour later" | Change of the outcome per step of the driver |
| `p`, `q` | `0.0001`, `0.001` | Uncorrected and Benjamini-Hochberg corrected p-value |
| `status` | `robust` | `robust`, `tendency` or `none` |

Variable keys: `training_load`, `active_min`, `steps`, `hard_sets`, `tonnage_t`, `stress_avg`,
`bedtime_min` (minutes relative to midnight, negative before midnight), `sleep_hours`,
`sleep_score`, `hrv`, `resting_hr`, `readiness`, `body_battery`, `strength_form_pct`.

## settings.json

Optional personal settings, read by the sync and the dashboard: `timezone`, `step_goal`,
`main_lifts`, `grip_exercises`. Format, defaults and examples are in the README under *Settings*.
