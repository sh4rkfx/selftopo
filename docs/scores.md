# Daily scores: evidence-based design

Specification for four daily scores (0–100) shown as rings: **Recovery**, **Sleep**, **Load** and
**Strength**. The structure follows Oura's published contributor model; every contributor was then
checked against the research literature for three questions:

1. Does the signal carry information about recovery, performance or health?
2. How should it be normalised (absolute target or personal baseline, which time window)?
3. Can the Garmin watch measure it well enough?

Status: specification, not yet implemented.

## Key findings

**No composite score has validated weights.** A 2025 review of 14 composite "readiness",
"recovery" and "strain" scores from 10 wearable manufacturers found that none discloses its formula
or weights and none has been validated against outcomes in peer-reviewed research; correlated inputs
such as sleep and HRV are often counted twice [R1]. Oura's weights are not published either [O1–O3].
Any fixed weighting is therefore a choice, not a finding.

**Equal weights are the defensible default.** When each predictor's direction is known, equal
(unit) weights predict about as well as optimised regression weights and are more robust in small
samples; regression typically needs 15–20 observations per predictor before it wins on
cross-validation [R2]. With six contributors and a strength outcome that only exists on training
days, that is roughly a year of data. Until then, evidence decides **which** contributors enter a
score and **how** they are normalised; within a score they are weighted equally.

**Subjective wellbeing is the strongest single signal.** A systematic review of 56 studies found
self-reported measures (mood, stress, perceived recovery) responded to acute and chronic training
load with greater sensitivity and consistency than objective measures such as heart rate, and the two
generally did not correlate [R3]. Neither Garmin nor Hevy records it, so it is an optional contributor
that needs a daily 30-second check-in.

**Garmin measures sleep duration and timing reasonably, sleep stages poorly.** Garmin devices
overestimated total sleep time by 28–66 minutes against reference measurements (about 45 minutes on
average), detected wake epochs
poorly (specificity 27–30 %), and classified deep sleep with 28–45 % and REM with 34–50 %
sensitivity; agreement for stages was only fair (κ 0.20–0.25) [M1, M2]. Stage-based contributors are
dropped. For nocturnal HRV from Garmin wrist sensors there is little peer-reviewed validation; only
relative change against one's own baseline, averaged over several nights, is used.

## Evidence per contributor

| Contributor (draft) | Evidence | Garmin measurement | Decision |
|---|---|---|---|
| HRV balance | Practice guideline: 7-day rolling lnRMSSD against a 60-day baseline, meaningful change = 0.5 × within-person CV [H1]. HRV-guided training improves performance only by a small, non-significant margin [H2]. After resistance training HRV is back to baseline within ~24 h while neuromuscular recovery takes ~48 h and perceived recovery longer; HRV did not track either [H3] | Nocturnal accuracy not well established | **Keep**, normalise per [H1]; do not rely on it alone for strength readiness |
| Resting heart rate | Deviation from a personal 28-day baseline flagged most COVID-19 infections at or before symptom onset, in retrospective analysis typically about 4 days earlier [H4] | Usable as relative change | **Keep**, as deviation from 28-day baseline, plus a warning rule |
| Last night's sleep | Acute sleep loss reduces physical performance by 7.6 % on average across 69 studies; consistently with total deprivation and with waking earlier than usual; evening tasks are affected, morning tasks largely not [S1] | Duration overestimated by ~30–45 min [M1, M2] | **Keep**, duration only, target set with the bias in mind |
| Sleep balance | 14 nights of ≤ 6 h produced cognitive deficits equivalent to up to 2 nights of total sleep deprivation, while subjective sleepiness plateaued [S2]. Habitual sleep under 7 h is a marker of inadequacy; needs are individual [S3] | Same as above | **Keep**, increase weight |
| Sleep regularity | In 60,977 adults, regularity predicted mortality more strongly than duration; the more regular four fifths had 20–48 % lower all-cause mortality than the least regular fifth [S4] | Sleep onset and wake times are measured | **Keep**, move to the Sleep score |
| Sleep timing (midpoint 0–3 h) | No evidence for a fixed window; social jetlag (weekday vs. weekend midpoint) of 2 h or more was associated with higher cortisol and resting heart rate in a small cross-sectional study of 145 adults [S5] | Measured | **Replace** by social jetlag, inside the regularity contributor |
| Deep sleep, REM, awake time | Stage share matters physiologically, but see measurement | Poor [M1, M2] | **Drop**, show as information only |
| Previous-day load | Neuromuscular and perceived recovery lag HRV by a day or more after resistance training [H3] | Hevy sets are exact | **Keep**, as hard-set load of the last 48 h |
| Activity balance (acute:chronic ratio) | Ratio metrics have conceptual and methodological flaws and cannot show whether a load change raises or lowers injury risk; adjust load to the individual response instead [L1] | – | **Drop** from scores, keep load charts |
| Training frequency | Strength gains increase with weekly frequency, with diminishing returns [L2]. Guideline: muscle strengthening on ≥ 2 days per week [L3] | Exact (Hevy, watch) | **Keep** |
| Training volume | Strength gains rise with weekly sets but with strongly diminishing returns [L2] | Exact (Hevy) | **Keep**, capped at the planned volume |
| Steps | Mortality benefit levels off at about 8,000–10,000 steps per day for adults under 60 [L4] | Good | **Keep**, target 8,000 |
| Moderate and vigorous minutes | Guideline: 150–300 min moderate or 75–150 min vigorous per week [L3] | Garmin intensity minutes | **Add** (needs two new Garmin fields) |
| Recovery days | No study defines an optimal number | – | **Drop**, show as information |
| Strength form (e1RM) | Rep-based 1RM equations, Epley included, predicted bench-press 1RM from 4–10 reps with a standard error of 2.7–3.2 kg in less experienced lifters [K1] | Exact inputs | **Keep** |
| Strength progression | No external target exists | Exact inputs | **Keep**, judged against the personal trend only |
| Subjective wellbeing | Most sensitive and consistent monitoring signal [R3] | Not recorded | **Add**, optional check-in |

## Specification

All contributors are mapped to 0–100 with piecewise-linear functions between the anchor points
below and averaged with **equal weights** within each score. Missing contributors are left out of the
average. Status bands follow Oura's convention (85 optimal, 70 good, below 70 attention); they are a
display convention, not a validated threshold.

### Recovery: "Is my body ready for hard training today?"

| Contributor | Signal | 100 | 50 | 0 |
|---|---|---|---|---|
| HRV trend | 7-day mean of ln(RMSSD), at least 3 nights, against 60-day mean; band = ± 0.5 × 60-day CV [H1] | inside or above band | 1 band width below | 2 band widths below |
| Resting heart rate | Last night against 28-day mean, in standard deviations [H4] | ≤ +0.5 SD | +1.5 SD | ≥ +2.5 SD |
| Sleep debt | Mean of last 14 nights ÷ sleep need [S2, S3] | ≥ 100 % | 85 % | ≤ 70 % |
| Last night | Sleep duration ÷ sleep need; extra penalty if woken > 1 h earlier than usual [S1] | ≥ 100 % | 80 % | ≤ 60 % |
| Muscular pre-load | Hard sets in the last 48 h ÷ typical 48-h hard sets (28 days) [H3] | ≤ 1.0 | 1.75 | ≥ 2.5 |
| Wellbeing (optional) | Mean of energy, soreness (reversed) and stress (reversed), each 1–5 [R3] | 5 | 3 | 1 |

**Warning rule** (overrides the average): resting heart rate ≥ +2 SD on two consecutive nights, or the
HRV trend below its band on 3 of the last 4 days, caps Recovery at 69 with the note "possible
infection or overreaching" [H1, H4]. The 2 SD threshold is a design choice; the method of comparing
against a personal 28-day baseline follows [H4].

### Sleep: "Am I sleeping enough and regularly?"

| Contributor | Signal | 100 | 50 | 0 |
|---|---|---|---|---|
| Duration | Last night ÷ sleep need [S1, S3] | ≥ 100 % | 80 % | ≤ 60 % |
| Sleep debt | Mean of last 14 nights ÷ sleep need [S2] | ≥ 100 % | 85 % | ≤ 70 % |
| Regularity | Mean of the 14-day SD of sleep onset and of wake time, plus social jetlag (weekend minus weekday midpoint, 28 days) [S4, S5] | ≤ 30 min and jetlag ≤ 1 h | 60 min or jetlag 2 h | ≥ 90 min or jetlag ≥ 3 h |

Sleep need defaults to 7:30 h *as measured by Garmin*, which corresponds to roughly 7 h of actual sleep
given the measured overestimation [M1, M2] and the 7-hour inadequacy marker [S3]. Deep sleep, REM and
awake time are shown next to the score but do not enter it.

### Load: "Am I moving and training enough?"

| Contributor | Signal | 100 | 50 | 0 |
|---|---|---|---|---|
| Active minutes | Last 7 days: moderate minutes + 2 × vigorous minutes [L3] | ≥ 300 | 150 | 0 |
| Strength days | Days with ≥ 1 hard set in the last 7 days [L2, L3] | ≥ planned (default 3) | 2 | 0 |
| Steps | Days with ≥ 8,000 steps in the last 7 [L4] | ≥ 5 | 3 | 0 |

### Strength: "Am I getting stronger?"

| Contributor | Signal | 100 | 50 | 0 |
|---|---|---|---|---|
| Form | Best e1RM of the latest session ÷ best of the prior 28 days, per exercise, averaged [K1] | ≥ 100 % | 93 % | ≤ 86 % |
| Plan adherence | Hard sets in the last 7 days ÷ planned hard sets, capped at 100 % [L2] | ≥ 90 % | 60 % | ≤ 30 % |
| Progression | 8-week trend of the main lifts' e1RM, % per month | ≥ +1 % | 0 % | ≤ −2 % |

The progression anchors are heuristics without external evidence; they should be adjusted to the
observed personal trend.

## Personal targets

| Target | Default | Basis |
|---|---|---|
| Sleep need (Garmin-measured) | 7:30 h | [S3], [M1, M2] |
| Planned strength sessions per week | 3 | personal plan; ≥ 2 per [L3] |
| Planned hard sets per week | 30 | personal plan (e.g. 3 sessions × 5 exercises × 2 hard sets) |
| Step target | 8,000 | [L4] |

## Validation in your own data

Literature can justify the selection of contributors, not their weights for one person. Once enough
data exists, `selftopo analyze` can test:

| Question | Test | When |
|---|---|---|
| Does Recovery predict the day's strength form? | Spearman correlation of morning Recovery with same-day strength form, against Garmin Training Readiness as comparison | ~60 training days |
| Are fitted weights better than equal weights? | Leave-one-month-out cross-validation predicting strength form | ~15–20 training days per contributor [R2] |
| Is a contributor useless? | Contributor with no relationship to any outcome after the correction for multiple tests | ~120 days |

Weights change only if fitted weights clearly beat equal weights out of sample.

## Implementation notes

- New Garmin fields from the daily summary for active minutes: moderate and vigorous intensity
  minutes. Field names to be confirmed with `dump-raw`.
- The optional wellbeing check-in needs an input channel that writes to the repository, which is not
  decided yet.
- Output: `data/scores.csv` with one row per day, each score and every contributor's raw value and
  sub-score, so each number on the dashboard can be traced.

## References

**Composite scores and weighting**
- [R1] Readiness, recovery, and strain: an evaluation of composite health scores in consumer wearables. De Gruyter, 2025. https://doi.org/10.1515/teb-2025-0001
- [R2] Dawes RM. The robust beauty of improper linear models in decision making. American Psychologist 1979;34(7):571–582. https://www.cmu.edu/dietrich/sds/docs/dawes/the-robust-beauty-of-improper-linear-models-in-decision-making.pdf
- [R3] Saw AE, Main LC, Gastin PB. Monitoring the athlete training response: subjective self-reported measures trump commonly used objective measures. British Journal of Sports Medicine 2016;50(5):281. https://bjsm.bmj.com/content/50/5/281

**Heart rate and HRV**
- [H1] Australian Institute of Sport. Resting heart rate and heart rate variability monitoring: best practice guidelines (citing Plews et al. 2013, 2014; Altini 2021). https://www.ais.gov.au/__data/assets/pdf_file/0013/1130260/HRV-BPG_FINAL.pdf
- [H2] Manresa-Rocamora A, Sarabia JM, Javaloyes A, Flatt AA, Moya-Ramón M. Heart rate variability-guided training for enhancing cardiac-vagal modulation, aerobic fitness, and endurance performance: a methodological systematic review with meta-analysis. IJERPH 2021;18:10299. https://mdpi-res.com/d_attachment/ijerph/ijerph-18-10299/article_deploy/ijerph-18-10299.pdf
- [H3] Flatt AA, Globensky L, Bass E, Sapp BL, Riemann BL. Heart rate variability, neuromuscular and perceptual recovery following resistance training. Sports 2019;7(10):225. https://www.mdpi.com/2075-4663/7/10/225
- [H4] Mishra T, Wang M, Metwally AA, et al. Pre-symptomatic detection of COVID-19 from smartwatch data. Nature Biomedical Engineering 2020;4:1208–1220. https://www.nature.com/articles/s41551-020-00640-6

**Sleep**
- [S1] Effects of acute sleep loss on physical performance: a systematic and meta-analytical review. Sports Medicine 2022;52(11):2669–2690. https://lida.sport-iat.de/ta/Record/4078085
- [S2] Van Dongen HPA, Maislin G, Mullington JM, Dinges DF. The cumulative cost of additional wakefulness. Sleep 2003;26(2):117–126. https://www.gwern.net/doc/melatonin/2003-vandongen.pdf
- [S3] Walsh NP, Halson SL, Sargent C, et al. Sleep and the athlete: narrative review and 2021 expert consensus recommendations. British Journal of Sports Medicine 2021;55(7):356. https://bjsm.bmj.com/content/55/7/356
- [S4] Windred DP, Burns AC, Lane JM, et al. Sleep regularity is a stronger predictor of mortality risk than sleep duration. Sleep, 2023. https://doi.org/10.1093/sleep/zsad253
- [S5] Rutters F, Lemmens SG, Adam TC, et al. Is social jetlag associated with an adverse endocrine, behavioral, and cardiovascular risk profile? Journal of Biological Rhythms 2014;29(5):377–383. https://journals.sagepub.com/doi/10.1177/0748730414550199

**Measurement accuracy**
- [M1] Accuracy of Fitbit Charge 4, Garmin Vivosmart 4, and WHOOP versus polysomnography: systematic review. JMIR mHealth and uHealth 2024;12:e52192. https://mhealth.jmir.org/2024/1/e52192
- [M2] Miller DJ, Sargent C, Roach GD. A validation of six wearable devices for estimating sleep, heart rate and heart rate variability in healthy adults. Sensors 2022;22(16):6317. https://www.mdpi.com/1424-8220/22/16/6317

**Load and activity**
- [L1] Training load and its role in injury prevention, part 2: conceptual and methodologic pitfalls. Journal of Athletic Training 2020;55(9):893–901. https://doi.org/10.4085/1062-6050-501-19
- [L2] Resistance training dose-response: meta-regressions of weekly volume and frequency on hypertrophy and strength. Sports Medicine 2026;56(2):481–505. https://sponet.de/sponet/Record/4097139
- [L3] World Health Organization. Physical activity fact sheet and 2020 guidelines. https://www.who.int/news-room/fact-sheets/detail/physical-activity
- [L4] Paluch AE, Bajpai S, Bassett DR, et al. Daily steps and all-cause mortality: a meta-analysis of 15 international cohorts. Lancet Public Health 2022;7:e219–e228. https://discovery.ucl.ac.uk/id/eprint/10170017/1/1-s2.0-S2468266721003029-main.pdf

**Strength**
- [K1] Lacio ML, Damasceno VO, Vianna JM, et al. Precision of 1-RM prediction equations in non-competitive subjects performing strength training. Motricidade 2010;6(3):31–37. https://revistas.rcaap.pt/motricidade/article/view/143

**Oura**
- [O1] Oura: Readiness Score. https://ouraring.com/blog/readiness-score/
- [O2] Oura: Sleep Score. https://ouraring.com/blog/sleep-score/
- [O3] Oura: Activity Score. https://ouraring.com/how-to-track-activity/
