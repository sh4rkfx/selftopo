# Relationship analysis

`python -m selftopo analyze` looks for time-lagged relationships between what you do (training,
steps, bedtime) and how you recover and perform (HRV, resting heart rate, sleep, readiness,
strength). The code is in `selftopo/analyze.py`; this page explains what it does and how to
read the result.

## Timing conventions

Garmin attaches overnight values to the date you wake up. The HRV on 14 October is the HRV of
the night from 13 to 14 October. The analysis builds one row per calendar day and pairs values
with an explicit lag:

| Driver | Outcome | Lag | Meaning |
|---|---|---|---|
| Training load, active time, steps, hard sets, tonnage, daytime stress on day D | HRV, resting heart rate, sleep score, sleep duration, readiness, Body Battery | 1 and 2 days | The night after D, and the night after that |
| Bedtime and sleep duration of a night | HRV, resting heart rate, readiness of the same night | 0 | Same night |
| Bedtime, sleep duration, sleep score, HRV, resting heart rate, readiness | Strength form on the same day | 0 | Did the night before affect the workout? |
| Calories, protein, carbohydrates, fat on day D (YAZIO, optional) | HRV, resting heart rate, sleep score, sleep duration, readiness, Body Battery | 1 day | The night after D |
| Calories and carbohydrates on day D | Strength form on day D + 1 | 1 day | Did yesterday's food affect today's workout? |

Pairs where Garmin computes the outcome from the driver are left out, because they are related
by construction: Training Readiness uses sleep and HRV, Body Battery uses sleep, HRV and stress.
This leaves about 80 pairs, plus 26 with YAZIO data. Food is tested against the following night
only: a second night would add another 24 tests, which lowers the chance that any real effect
survives the correction. YAZIO days under 1,200 kcal count as not fully logged and are left out
(`MIN_COMPLETE_KCAL`), as are days without an entry; neither counts as zero.

## Method

| Step | What happens | Why |
|---|---|---|
| Daily table | One row per calendar day. Days without an activity or a workout count as zero load once that source has data | Rest days are information, not gaps |
| Strength form | For every exercise with a typical weight of at least 20 kg: best estimated 1RM of the day (Epley, sets of 1 to 10 reps) compared with its best of the prior 28 days, averaged over the exercises of the day | Comparable across exercises and independent of long-term progress |
| Detrending | Every value is replaced by its difference to the mean of the 28 days before it (at least 7 values) | Two metrics that both drift over months, such as weight and HRV during a diet, would otherwise look related |
| Correlation | Spearman rank correlation on these differences, at least 20 days per pair | Robust against single extreme days such as a long mountain tour |
| Effect size | Theil-Sen slope, reported per meaningful step of the driver (100 load points, 1 hour later to bed, 10 hard sets) | Says how much, not only whether |
| Multiple testing | Benjamini-Hochberg correction over all tested pairs | With 80 tests, about 4 would be "significant" at p < 0.05 by chance alone |

| Status | Rule | Reading |
|---|---|---|
| `robust` | q < 0.10 | Holds up against the correction. Among robust findings, about 1 in 10 is expected to be a false alarm |
| `tendency` | p < 0.05 but not robust | Worth watching; may become robust with more data or disappear |
| `none` | everything else | No evidence of a relationship in the current window |

On pure noise, about one run in ten reports any robust finding at all (checked in
`tests/test_analyze.py`). Injected effects of realistic size are recovered with the right sign and
magnitude.

## Reading the results

Correlation in self-tracking data is easy to misread. Before acting on a finding, check:

| Trap | Example | How to tell |
|---|---|---|
| Fixed weekly schedule | "More hard sets → better sleep two nights later", because two days after Thursday's workout always comes the long Friday-to-Saturday night | The lag lines up with a weekday pattern; the effect disappears when you look at single weeks |
| Common cause | "Less training → worse sleep", because a cold cut both | The finding is driven by a few consecutive days; check the daily table for that period |
| Overlapping drivers | Active time and training load both show up for the same outcome | They measure largely the same thing; read them as one finding |
| Indirect effects | "Later bedtime → lower readiness" | Real, but works through HRV and sleep; the direct pair (bedtime → HRV) is the more informative one |
| Small samples | A strong effect on strength form with 25 days | Look at `n`; findings on strength form depend on how many workouts are in the window |

A useful finding is one you can test: change one thing for two or three weeks (go to bed 45
minutes earlier on weekdays, move the heavy lower-body day away from bouldering) and see whether
the effect shows up again in the next analysis.

## Output

`data/insights.json`, see [data-reference.md](data-reference.md#insightsjson) for every field.
Findings are sorted by status, then by q, then by strength of correlation.

## Changing the analysis

| Setting in `analyze.py` | Default | Effect |
|---|---|---|
| `BASELINE_DAYS` | 28 | Length of the "normal" window for detrending |
| `MIN_PAIRS` | 20 | Days with both values needed to test a pair |
| `FDR_Q` | 0.10 | Accepted share of false discoveries among robust findings |
| `TENDENCY_P` | 0.05 | Threshold for tendencies |
| `candidate_pairs()` | | Which drivers, outcomes and lags are tested |
| `--days` on the command line | 180 | Length of the analysis window |
