# Bunching prediction, timing what-if and simulation

Phase two adds two tabs to the workspace, and nothing from phase one was removed:

- **Bunching** predicts, for one line or several lines that share a route, which buses are about to bunch. It also tests holding times on the real trips.
- **Simulate** replays a real day of one line with a timing change: leave on schedule, headway-based dispatch, a longer turnaround, or holding. It shows what would have changed and recommends one option by a fixed rule.

## Codebase overview (where the new parts sit)

```text
backend/
  app.py                  FastAPI app; also mounts bunching_api + sim_api (4 lines added)
  db.py, domain.py        connection, migrations, Lisbon time windows            (unchanged)
  workspace_api.py        date catalog: areas, operators, presets, routes         (unchanged)
  observation_query.py    vehicle observations for the replay map                 (unchanged)
  plans_api.py            route shapes + stops for overlays                        (unchanged)
  bunching.py             NEW  stop passages, headways, features, models, holding what-if
  bunching_api.py         NEW  /api/bunching/model, /lines, /shared, /diagram
  train_bunching_model.py NEW  trains both models -> models/bunching_model*.json
  simulator.py            NEW  replay simulator: scenarios, vehicle chains, KPIs
  validate_simulator.py   NEW  validation gate, fits k, held-out scenario grid -> models/simulator_validation.json
  sim_api.py              NEW  /api/sim/scenarios, /validation, /run
  models/*.json           NEW  the two models + the simulator validation
  requirements-model.txt  NEW  numpy + scikit-learn, only for training
  test_bunching.py, test_simulator.py  NEW  unit + endpoint tests (no database needed)
src/
  UnifiedWorkspace.tsx    map + sidebar; tabs "Bunching" and "Simulate" and their overlays were added
  BunchingPanel.tsx       NEW  prediction form, what-if table, diagram, "buses that bunch most"
  SimulatePanel.tsx       NEW  scenario cards, KPI cards, as-run vs changed diagrams, trade-off chart
  bunching.ts, sim.ts     NEW  API types, requests, helpers (+ tests)
  bunching.css, sim.css   NEW  styles
  style.css               tab bar now has 5 columns
```

The database is unchanged. Everything is derived from `vehicle_events` and the date-valid plan tables (`schedule_trips`, `schedule_routes`, `schedule_stop_visits`, `plan_records`).

## Data preparation (shared by both tabs)

1. **Stop passages.** `vehicle_events.stop_id` is the stop a bus is serving or heading to. The last ping that still reports stop *S* is taken as the time the bus left *S*. At the last stop of a trip, the first ping is used instead (the arrival, not the layover).
2. **Schedule repair.** About half the trips of 18 CARRIS lines repeat the trip's start time at every stop. For those trips, the planned time at a stop is the start time plus the typical *planned* running time to that stop, taken from other trips of the same route. Times written as 00:xx–03:xx belong to the next day (the CARRIS service day starts at 04:00).
3. **Wrong trip ids.** A trip whose median delay is still above 30 min after the repair almost certainly reports the wrong `trip_id`, so it is excluded. That is 5.3 % of trip-days (2,873 of 53,805). The handoff estimated 11 %, but that figure was before the flat-time repair.
4. **Waze is not used as a feature.** The handoff showed that its clock is UTC and its intensity labels are reversed. It adds nothing a GPS run time does not already show.

## Bunching tab: early warning

| | Same line (1 line selected) | Across lines (2–6 lines selected) |
| --- | --- | --- |
| Bus in front | previous bus of the same line and direction at the stop | previous bus of **any selected line** at the same stop |
| Bunched when | gap < 25 % of the planned gap | the two buses pass < 60 s apart although planned ≥ 2 min apart |
| Predicts | bunching within the next **10** stops, only while the gap is still ≥ 50 % of plan (P2 in the handoff) | bunching within the next 5 stops, for pairs that stay on the same route |
| Extra features | delay gap to the bus in front, delay carried over from the bus's previous trip | same line or not, share of the next 5 stops both buses serve, gap in minutes |

All the models also use: log gap ratio, gap change over the last 3 stops, own delay, delay of the bus in front, planned gap, position along the route, AM/PM peak and weekend. The model is a logistic regression. **Split by day:** Fri 4 and Sun 6 Sep are the test set; the other 5 days train.

| Model | Test rows | Base rate | ROC-AUC (baseline) | Avg. precision (baseline) |
| --- | --- | --- | --- | --- |
| Same line, early warning | 231,978 | 1.2 % | **0.82** (0.76) | **0.13** (0.06) |
| Across lines | 122,681 | 10.4 % | **0.75** (0.70) | **0.33** (0.31) |

**Alert level from data.** Each training day is predicted by a model that did not see it, and the level with the best F1 is kept (same line 10 %, across lines 20 %).

- On the test days, a same-line alert is right 20 % of the time and catches 28 % of the onsets. The best simple rule ("gap below 60 % of plan") is right only 9.5 % of the time and catches 27 %. At a budget of about 1 alert per 100 passages (level 16 %), 26 % of alerts are right.
- Across lines, the model is only slightly better than "the bus in front is less than 210 s ahead".

The holding what-if in this tab replays the real trips, holds a bus when the model fires, and recomputes every gap. With no holding it reproduces the data exactly. It recommends the shortest hold that gets at least 75 % of the best reduction.

## Simulate tab: replay simulator (plan "Simulator and validation gate")

A scenario changes only **when** a bus leaves the terminal or waits at a stop. Everything else comes from what really happened that day.

- **Replay.** A bus on its real timeline keeps its own observed run time for every segment. With no change, the simulation reproduces the day exactly (checked on Mon–Fri and Sun).
- **Time shift.** A bus moved in time keeps its own run times, plus ±5 % seed noise once it is ≥ 30 s off its real time.
  - The plan also suggested scaling runs by the traffic at the new time (from the run-time bank). We tested that on the held-out days: it predicted run times *worse* (Fri 37.5 s vs 36.2 s mean error, Sun 33.5 s vs 32.4 s), so it is off.
- **Dwell feedback.** Extra stop time = k × (gap − the gap the bus really had). This is the "late bus gets later" effect. k is fitted on Mon–Thu (see below).
- **Vehicle chain.** A trip cannot start before its vehicle is back from its previous trip, plus the layover it really had (at most 1 min), so delays carry over. A trip whose previous trip is unknown never leaves earlier than it really did.
- **Broken records** are dropped: trips that took more than twice the usual time per stop, e.g. a bus that kept one trip id for 6 hours.
- **Seeds:** 10 in the UI (30 in the validation), with common random numbers.

| Code | Timing change | Package |
| --- | --- | --- |
| D1 | leave the terminal on schedule if the bus is there | ceiling (never recommended) |
| D2-2 / D2 / D2-5 | headway-based dispatch: wait until the gap to the bus in front is ≥ 90 % of plan, max 2 / 3 / 5 min | no cost |
| H1-60 / H1-120 | hold at 2 control stops (⅓ and ⅔ of the route) when > 3 min closer than planned, max 60 / 120 s | low cost |
| M-90 | hold where the early-warning model fires (max 3 holds per trip, 3 stops apart), max 90 s | low cost |
| D2+H1 | both | low cost |
| T2-2 / T2-4 | leave on schedule with 2 / 4 min more turnaround; extra buses = extra cycle time ÷ headway | investment |

**KPIs:**

- **Benefits:** bunched passages (gap < 25 % of plan), headway CV, excess wait time. Excess wait time is the average wait of a passenger arriving at random minus the wait if the same buses were evenly spaced.
- **Costs:** on-board hold per trip, terminal wait per trip, trip time, extra buses.

KPIs are computed over the trips that really started in the window, at the stops where they were really seen, so every scenario is scored on the same set.

### Validation gate (`validate_simulator.py`; 5 plan lines 742, 767, 728, 758, 735; 16–20 h)

| Check | Result |
| --- | --- |
| Replay with no change | exact on every day ✔ |
| k fitted on Mon–Thu | resampled baseline (every run drawn from the bank) matches the observed 11.9 % bunched at **k = 0.005**. A separate regression of run time on the gap deviation gives 0.004 |
| Held-out bunched share (±15 %) | Fri 12.3 % → 16.2 %, Sun 5.2 % → 6.9 % ✘ (with k = 0: 12.9 % and 5.3 % ✔) |
| Bunching by departure gap ratio (same ranking) | ✔ on both days (0.25–0.5 bunches most … 0.9–1.1 least) |
| Growth along the route (same direction) | ✔ on both days |

The gate status is **partial**: k is uncertain between 0 and 0.005. So every held-out scenario is run with both values. An option counts as **robust** only if it cuts excess wait in ≥ 95 % of the 30 seeds, on both held-out days, for both values of k.

### Recommendation rule (fixed in advance, plan "Scoring")

1. Keep the robust options. D1 is a ceiling and is never recommended.
2. Find the largest cut in excess wait.
3. Recommend the cheapest option with at least 75 % of it. Cost is compared by extra buses first, then on-board hold, then terminal wait.

Held-out results (Fri + Sun, both directions):

| Line | Recommended | Excess wait saved (s / passenger, range over days × k) | Why |
| --- | --- | --- | --- |
| 742 | **D2-5** headway dispatch | 24 (15–34) | buses leave too soon after the one in front; D2 (max 3 min) is robust too |
| 767 | **T2-2** +2 min turnaround, 1 extra bus | 34 (31–39) | late arrivals carry over into the next trip; D2 also robust (7–21) |
| 728 | **M-90** early-warning hold | 10 (3–17) | gaps open on the road; dispatch rules do not help here |
| 758 | **T2-2**, 1 extra bus | 62 (19–97) | late departures from the previous trip; D2 not robust |
| 735 | **T2-2**, 1 extra bus | 47 (28–64) | same as 758 |

The UI also applies the rule on the selected day alone, using its own seeds; that answer can differ from the held-out one. **Not modelled:** passenger loads, driver rules and breaks, other operators at shared stops. D1 and T2 assume the bus could leave as soon as it was back (+ at most 1 min). Where a real driver break forced a late departure, they overstate the gain.

## Use it

```sh
docker compose up -d --build --wait     # REQUIRED once: the API image must be rebuilt to include the new files
npm run dev                             # Bunching tab -> line -> Predict;  Simulate tab -> line -> timing change -> Simulate
```

If a tab reports that the API lacks its endpoints (or shows "Not Found"), rebuild with the command above. The first request after the API starts takes 10–15 s: the Bunching tab builds its route tables, and the first Simulate run of a line replays every scenario with every seed. After that, switching scenarios is instant.

**Simulate view:**

- Top: KPI cards, with the change against what really happened and the range over the seeds.
- Middle: two time–space diagrams on the same axes, *as run* and *with the change*. Grey marks where the buses really were, red segments are bunching, `D` marks a changed departure and `H` a hold.
- Right: the trade-off chart. Each dot is one timing change, placed by wait saved (up) against seconds held or waiting per trip (right), with bars for the seed range and ★ for the recommended one. Click a dot to switch to it.

## Model v4 (same line): gradient-boosted trees + context features

The same-line early warning is now **gradient-boosted trees** (scikit-learn HistGradientBoosting, 100 trees, the count is chosen by leave-one-day-out on the training days). The trees are exported to `models/bunching_model.json` and evaluated in plain Python (`bunching.predict_trees`), so the API image needs no new packages.

**New inputs** (`bunching.CONTEXT_FEATURES`). Each one is known at the moment the bus passes the stop:

| Feature | Meaning | Why |
| --- | --- | --- |
| `line_irreg30`, `line_n30` | mean \|log gap ratio\| and number of passages of the same line and direction in the last 30 min | a line that is already irregular keeps bunching: the bunching rate is 0.2 % in the calmest fifth and ≈3 % in the most irregular fifth |
| `leader_changed` | the bus in front is not the one of the previous stop (overtaking) | 3.4 % vs 1.2 % |
| `close1`, `close3`, `close5` | gap change in s per stop over the last 1 / 3 / 5 stops | the gap trend is U-shaped: gaps that suddenly **grow** by more than 0.5 of plan bunch in 18 % of cases |
| `leader_log_ratio`, `lead_close3` | the gap of the bus in front to ITS leader, and how that gap changes | squeezed or stretched leaders both raise the risk (U-shaped) |
| `delay_change3` | own delay change over the last 3 stops | |
| `hour_sin`, `hour_cos` | time of day as a smooth cycle | |

Tested and **not** useful: dwell time, run times, the bus behind, and stop/line hotspot rates. Once the features above are in the model, these add less than 0.005 AP.

**Results** (same data and split as v3; test = Fri 4 + Sun 6 Sep):

| | v3 logistic regression | **v4 trees** |
| --- | --- | --- |
| ROC-AUC | 0.822 | **0.903** |
| Average precision (base rate 1.2 %) | 0.133 | **0.240** |
| AP Fri / Sun | 0.136 / 0.138 | **0.233 / 0.270** |
| At 1 alert per 100 passages: alerts right / bunching caught | 26 % / 18 % | **36 % / 26 %** |
| At the F1 alert level: alerts right / bunching caught | 20 % / 28 % (level 10 %) | **29 % / 34 %** (level 15 %) |
| Leave-one-day-out, all 7 days: mean AP | 0.138 | **0.241** (better on 7/7 days) |

**Holding still uses v3.** In the simulator, holding where the v4 trees fire saved *less* wait than holding where v3 fires. Offline check, 5 validation lines, Fri + Sun, 16–20 h, 30 seeds, k = 0 and 0.005, mean excess wait saved per passenger:

| | 742 | 767 | 728 | 758 | 735 | mean |
| --- | --- | --- | --- | --- | --- | --- |
| v3 | 2.6 s | 4.1 s | 6.0 s | 1.0 s | −0.4 s | 2.7 s |
| v4 | 5.7 s | −2.2 s | 0.0 s | 3.0 s | −1.7 s | 1.0 s |

The Bunching tab what-if agrees: a 60 s hold avoids 8.6 % of bunched passages with v3 and 6.6 % with v4. The trees are better at *who will bunch*. But they also flag cases where holding the follower does not help (overtaking, lines that are already chaotic), and a hold trigger needs *where a hold helps*. So:

- `models/bunching_model.json`: v4 trees → alerts and risk in the Bunching tab.
- `models/bunching_hold_trigger.json`: v3 logistic regression → holds in the Bunching what-if and in the Simulate scenario M-90 (`bunching.load_model('hold')`). The simulator results therefore do not change.

A natural next step would be a model that predicts the *benefit* of a hold (uplift), trained on simulator runs.

## Retrain / revalidate

```sh
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements-model.txt
export DATABASE_URL=postgresql://headway:<password>@127.0.0.1:5433/headway
.venv/bin/python backend/train_bunching_model.py        # ~6 min, rewrites bunching_model.json (trees), bunching_hold_trigger.json and the corridor model (--mode line|corridor)
.venv/bin/python backend/validate_simulator.py          # ~2 min, rewrites models/simulator_validation.json
```

Use the host port from `compose.yaml`, and restart the API afterwards.
