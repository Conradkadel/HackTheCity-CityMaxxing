# Challenge 7 – Improving the bunching early-warning model (24 Sep 2026)

This note records the model experiments. They ran offline on `backend/models/experiments/passages_line.csv.gz`, which was exported with `export_passages.py` (1,146,383 passages, CARRIS, 31 Aug – 6 Sep). The model is only scored on 946,791 of them: the passages where the gap is still ≥ 50 % of plan and bunching hasn't started yet. The rebuilt labels match the production labels on 100 % of rows.

## Findings

- **The relationships are nonlinear (U-shaped).**
  - **Gap trend:** a fast-closing gap gives a 3.7 % chance of bunching within the next 10 stops. A stable gap gives 0.9 %. A gap that jumps up by more than 0.5 gives **18 %**. In 37 % of those jumps the bus in front changed, i.e. overtaking.
  - **The leader's own gap:** 1.7 % when the bus in front is squeezed against its own leader, 0.7 % when it's normal, and 2.6 % when it's far behind its leader.
  - **Planned headway:** 7 % for buses every 2–8 min, 0.8 % for every 15–30 min.
- **Overtaking:** when the bus in front changed since the previous stop, the rate is **3.4 % vs 1.2 %**.
- **How irregular the line is right now** (mean |log gap ratio| of the same line and direction over the last 30 min) is the strongest new single signal: AUC 0.72, and the rate goes from 0.2 % in the lowest quintile to 3.0 % in the highest.
- **Stop hotspots are stable:** stop bunching rates correlate at r = 0.62 between different day groups.
- **Dwell time** (a proxy for passenger load), **run times** and **the bus behind** added almost nothing.

## Models

The target is bunching within 10 stops. Scores are average precision; the base rate is 1.2–1.3 %.

| Model | Fixed test days (Fri 4 + Sun 6 Sep) | Leave-one-day-out mean (7 folds) |
|---|---|---|
| Gap rule | 0.064 | – |
| Logistic regression (production) | 0.133 | 0.138 |
| Logistic regression + new features | – | 0.170 |
| LightGBM, production features | 0.189 | 0.185 |
| **LightGBM "lean"** (production + time of day + leader gap + line irregularity + history/overtaking) | **0.223** | **0.225** |

- LightGBM lean beats production on **7/7 days**. Its mean AP is +63 % over production.
- On the test days: precision at 28 % recall rises from 20 % to 32 %. At 1 alert per 100 passages, 33 % of alerts are right and 27 % of bunching is caught (production: 24 % and 20 %).
- Adding the bus behind, dwell times, or stop and line rates on top of the lean model changes AP by less than 0.005.

## Horizon (k = number of stops ahead)

| k | Base rate | Production LR AP | LightGBM lean AP | Lift (lean) | Share of bunching caught at 1 alert/100 |
|---|---|---|---|---|---|
| 3 | 0.42 % | 0.118 | 0.196 | 47× | 43 % |
| 5 | 0.62 % | 0.120 | 0.191 | 31× | 36 % |
| 10 | 1.21 % | 0.133 | 0.223 | 18× | 27 % |

With a shorter horizon, a larger share of bunching gets caught (at a fixed alert budget) and the lift over chance is higher, but the warning comes later. AP stays about the same, so k is a product decision about warning time vs. share caught, not a question of which one is "more accurate".

## Caveats

- The results come from one operator and one week.
- For deployment, the tree model needs a pure-Python tree evaluator (or LightGBM in the API image). The simulator's M-90 holding scenario and its validation must also be recomputed after any model change.
