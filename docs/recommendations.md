# Recommendations

selftopo turns your goals, your data and published studies into a short list of things to do
next. The daily `python -m selftopo analyze` (and `python -m selftopo recommend` on its own)
writes them to `recommendations.json` in the data repository; the dashboard shows them.

selftopo is not a medical device. The recommendations are suggestions for healthy adults. Values
that could be medically relevant only lead to the advice to have them checked.

## Principles

- **Every recommendation shows its evidence:** a study or guideline (with the source), or a robust
  relationship in your own data. Without evidence there is no recommendation.
- **Correlation is not causation.** Anything that rests only on your own data is offered as a
  14-day experiment, never as a fact.
- **Few instead of many:** at most one Today card and three cards in the area; the rest is one
  level deeper.
- **Measurable:** each card names the metric and the period that show whether it works.
- **Rule-based:** every rule, threshold and source is in `selftopo/recommend.py` and below.

## Goals

Recommendations need a goal; without one, only the Today card and the blood-pressure rules
appear. Goals live in `settings.json`, at most one per area:

```json
{
  "goals": {
    "koerper": { "metric": "weight", "target": 75, "by": "2027-03-31" },
    "erholung": { "metric": "resting_hr", "target": 46 },
    "schlaf": { "metric": "bedtime", "target": "23:00" },
    "kraft": { "metric": "weekly_sets", "target": 10 },
    "fitness": { "metric": "vo2max", "target": 47 },
    "aktivitaeten": { "metric": "steps", "target": 10000 }
  }
}
```

| Area | Metrics | Target |
|---|---|---|
| `koerper` | `weight` | kg, 7-day mean; `by` optional |
| `erholung` | `resting_hr`, `hrv` | bpm, 7-day mean; `hrv` means "stay in Garmin's balanced range" and needs no target |
| `schlaf` | `sleep_hours`, `bedtime` | hours, 7-day mean; or a clock time like `"23:00"` (reached on 5 of 7 nights) |
| `kraft` | `weekly_sets` | hard sets per week and primary muscle group, mean of 4 weeks (at least 10) |
| `fitness` | `vo2max` | Garmin's VO2max |
| `aktivitaeten` | `steps`, `active_minutes` | steps per day, 7-day mean; or activity minutes per week |

Each goal shows the current value, the pace (least-squares trend: 28 days for weight, sleep and
steps, 8 weeks for resting HR and activity minutes, 12 weeks for VO2max) and the forecast: the
date the current pace reaches the target. With `by`, the pace the date needs as well. Invalid
entries are reported in the sync log and left out.

## Rules

Evidence: **guideline**, **B** (studies, not yet checked in your data), **C** (only in your data:
an experiment), **data** (a data-quality rule). Numbers follow the concept's catalogue; rule 18
(load spikes, acute:chronic workload ratio) is left out because its evidence is disputed.

| # | Id | Switched on by | Trigger | Recommendation | Evidence |
|---|---|---|---|---|---|
| 1 | `today` | always | Readiness LOW/POOR today, or HRV 7-day mean below Garmin's range and resting HR ≥ 5 bpm above its 60-day mean | Today easy instead of hard. If resting HR was ≥ 5 bpm up on each of the last 3 days and HRV is below 92 % of the range: *pause*, with the hint not to train when feeling ill | B: [Manresa-Rocamora 2021](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8507742/), [Düking 2021](https://pubmed.ncbi.nlm.nih.gov/34489178/) |
| 2 | `late-training` | sleep goal | 2 or more intense activities (aerobic TE ≥ 4 or anaerobic TE ≥ 2) in 14 days ending less than 1 h before falling asleep | Move intense sessions earlier | B: [Stutz 2019](https://pubmed.ncbi.nlm.nih.gov/30374942/) |
| 3 | `weight-pace` | weight goal with `by` | Losing slower than the goal date needs | The missing deficit in kcal/day (7,700 kcal per kg) | B: [Garthe 2011](https://lida.sport-iat.de/ta/Record/4020442?lng=en) |
| 4 | `protein` | weight or strength goal | Protein below 1.6 g/kg (7-day mean of completely logged days) | Raise protein | B: [Morton 2018](https://pubmed.ncbi.nlm.nih.gov/28698222/) |
| 5 | `food-logging` | weight goal, YAZIO data | Fewer than 5 of the last 7 days logged completely (≥ 1,200 kcal) | Log every day this week | data |
| 6 | `endurance` | recovery goal | Fewer than 2 endurance activities of 20 min or more per week (4 weeks) | 2–3 easy endurance sessions a week | B: [Reimers 2018](https://www.mdpi.com/2077-0383/7/12/503/htm) |
| 7 | `alcohol` | recovery or sleep goal | Alcohol logged (Lifestyle Logging) on 3 or more of 28 days and HRV lower in the nights after | Experiment: 14 days without alcohol | B: [Pietilä 2018](https://pubmed.ncbi.nlm.nih.gov/29549064/) |
| 8 | `sleep-duration` | sleep or recovery goal | Sleep below 7 h (or the goal) in the 7-day mean | Go to bed 30 min earlier | B: [Watson 2015](https://pmc.ncbi.nlm.nih.gov/articles/PMC4434546/) |
| 9 | `sleep-regularity` | sleep goal | Sleep midpoint on weekend nights more than 1 h later than on weekdays (28 days) | Same wake-up time ± 30 min | B: [Windred 2024](https://www.broadinstitute.org/publications/broad1346196) |
| 10 | `bedtime-hrv` | recovery or sleep goal | Robust finding "later bedtime → lower HRV" (or another goal outcome) in `insights.json` | Experiment: 14 days asleep before the bedtime goal (default 23:00) | C |
| 11 | `caffeine` | sleep goal | Late caffeine logged on 2 or more of 14 days | No caffeine in the 6 hours before sleep | B: [Drake 2013](https://pmc.ncbi.nlm.nih.gov/articles/PMC3805807/) |
| 12 | `steps` | activity or weight goal | Steps below 8,000 in the 28-day mean | Raise the step goal by 1,000 | B: [Paluch 2022](https://ora.ox.ac.uk/objects/uuid:c77d223f-33ce-4d5c-9124-a00e5a43fcc1) |
| 13 | `own-data` | recovery or sleep goal | Robust finding between a behaviour (load, active time, steps, sets, tonnage, intake) and a goal outcome | Experiment: 14 days more or less of that behaviour | C |
| 14 | `blood-pressure-high` | always | Mean of 3 or more readings in 30 days ≥ 140/90 mmHg | Have it checked by a doctor; no experiments at all | Guideline: [ESC 2024](https://escardio.org/Congresses-Events/ESC-Congress/Congress-news/2024-esc-clinical-practice-guidelines-for-the-management-of-elevated-blood-press) |
| 15 | `training-volume` | strength goal | A primary muscle group gets fewer than 10 (or the goal's) hard sets per week (4 weeks of Hevy data) | Raise sets by about 2 a week | B: [Schoenfeld 2017](https://doi.org/10.1080/02640414.2016.1210197), [Schoenfeld 2019](https://doi.org/10.1080/02640414.2018.1555906) |
| 16 | `intervals` | fitness goal | VO2max not higher than 8 weeks ago and no activity with anaerobic TE ≥ 2 in 4 weeks | One interval session a week | B: [Milanović 2015](https://doi.org/10.1007/s40279-015-0365-0) |
| 17 | `activity-minutes` | activity, recovery or fitness goal | Fewer than 150 activity minutes per week (4 weeks of watch activities) | 150–300 min a week | Guideline: [Bull 2020](https://doi.org/10.1136/bjsports-2020-102955) |
| 19 | `blood-pressure-elevated` | always | Mean 120–139 / 70–89 mmHg | Endurance 2–3× a week, less salt, weight goal | B: [Cornelissen 2013](https://pubmed.ncbi.nlm.nih.gov/23525435/), [He 2013](https://doi.org/10.1136/bmj.f1325), [Neter 2003](https://doi.org/10.1161/01.HYP.0000094221.86888.AE) |
| 20 | `late-meal` | sleep goal | Late meal logged on 3 or more of 28 days and the sleep score lower in the nights after | Experiment: 14 days, last big meal 3 h before sleep | C |
| 21 | `weighing` | weight goal | Fewer than 4 weigh-ins in 7 days | Weigh every morning | data: [Zheng 2015](https://pubmed.ncbi.nlm.nih.gov/25521523/), [Madigan 2015](https://pubmed.ncbi.nlm.nih.gov/26293454/) |

Lifestyle Logging names depend on the app language; rules 7, 11 and 20 match `alcohol`/`Alkohol`,
`caffeine`/`Koffein` and `late meal`/`spätes Essen`.

**Order:** safety first, then the Today card; the cards are sorted by evidence (guideline, B,
data, C), then by effort, then by number.

**Safety limits in the code:** from 140/90 mmHg no experiments; never a pace faster than 1 % of
body weight per week; no weight-loss card below BMI 20 or towards a goal below it; never an intake
below Garmin's resting energy (total minus active calories); experiments only change habits.

## Experiments, later, does not fit

```json
{
  "experiments": [{ "rule": "alcohol", "start": "2026-11-12", "days": 14, "metrics": ["hrv", "resting_hr", "sleep_score"],
                    "title": { "text": "Experiment: 14 Tage ohne Alkohol", "vars": [] } }],
  "recommendations_hidden": {
    "steps": { "until": "2026-11-24" },
    "late-meal": { "dismissed": true, "reason": "Schichtdienst" }
  }
}
```

An experiment compares its days with as many days before it: median and quartiles per metric,
only from 10 days per phase; `title` is the card's title, written by the dashboard. While it runs, its card is not offered; once done, it is not
suggested again. `until` hides a card up to that date, `dismissed` for good.

## recommendations.json

| Key | Content |
|---|---|
| `as_of` | Day the rules were evaluated for |
| `today` | The Today card or `null`; `reasons` lists the values behind it, `pause` the infection pattern |
| `safety` | Cards that only advise a medical check |
| `goals` | Per goal: `current`, `pace_per_week`, `needed_per_week`, `eta`, `status` (`reached`, `on-track`, `off-track`, `no-data`) |
| `cards`, `more` | At most three cards, then the rest. Each has `rule`, `number`, `kind` (`lever`, `experiment`), `evidence`, `sources`, `title`, `why`, `measure`, `current` and, for experiments, `experiment` |
| `experiments` | State of each experiment in `settings.json` with per-metric results |
| `notes` | Hints such as conflicting goals |
| `sources` | Label and link of every cited source |

Texts are German templates with `{0}`, `{1}` …; the dashboard translates them and formats the
values: `{"n": 0.11, "d": 2}` a number with decimals, `{"date": …}`, `{"clock": "23:00"}`,
`{"muscle": "chest"}` a Hevy muscle group, `{"t": "…"}` a word to translate, `{"list": [...]}` a list.
