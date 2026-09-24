# Headway · Challenge 7 analysis workspace

Phase-one data visualisation for TML Challenge 7: inspect recorded Lisbon vehicle positions beside the operation plan that was valid on the vehicle's operational date. The application is a local React/Leaflet workspace backed by FastAPI and PostgreSQL.

Phase one visualises source evidence. Phase two adds a separate **Bunching** tab that predicts bunching and tests holding times, and a **Simulate** tab that replays a real day with timing changes (dispatch, turnaround, holding); see [docs/BUNCHING_MODEL.md](docs/BUNCHING_MODEL.md).

## Contents

1. [What is new: bunching prediction and simulation](#what-is-new-bunching-prediction-and-simulation)
2. [Repository guide](#repository-guide)
3. [Prerequisites](#prerequisites)
4. [Quick start with the shared CARRIS database](#quick-start-with-the-shared-carris-database)
5. [Rebuild from the raw source data](#rebuild-from-the-raw-source-data)
6. [Workspace behaviour](#workspace-behaviour)
7. [Bunching tab: early warning](#bunching-tab-early-warning)
8. [Simulate tab: test timing changes](#simulate-tab-test-timing-changes)
   - [The timing options](#the-timing-options)
   - [Reading the screen](#reading-the-screen)
   - [How the recommendation is chosen](#how-the-recommendation-is-chosen)
   - [Can we trust it? The validation gate](#can-we-trust-it-the-validation-gate)
   - [Results on the held-out days](#results-on-the-held-out-days)
9. [Where the bunching code lives](#where-the-bunching-code-lives)
10. [Retrain the models and revalidate the simulator](#retrain-the-models-and-revalidate-the-simulator)
11. [Development](#development)
12. [Data safety and current scope](#data-safety-and-current-scope)

## What is new: bunching prediction and simulation

Two tabs were added on top of the phase-one workspace. Nothing from phase one was removed.

| Tab | Question it answers | In short |
| --- | --- | --- |
| **Bunching** | *Which buses are about to bunch?* | For every bus at every stop, a model gives the chance that it bunches within the next stops. It shows the risk on a time–space diagram, lists the pairs of buses that bunch most, and tests holding times. |
| **Simulate** | *What if buses left or waited at different times?* | Replays a real day bus by bus with one timing change (dispatch rule, longer turnaround, holding). It shows the day as it really ran next to the changed day, scores each option on benefit and cost, and recommends one by a fixed rule. |

Both tabs use the date and time window in the header, and CARRIS lines with at least 3 recorded trips in that window.

> **After pulling this branch, rebuild the API once:** `docker compose up -d --build --wait`. Otherwise the tabs show "Not Found".
> The first request of each tab takes 10–15 s (tables and simulations are built once and then cached).

## Repository guide

- [Database construction](docs/DATABASE_CONSTRUCTION.md) explains the raw inputs, schema, repeatable imports, deduplication, plan normalisation, and route-resolution logic.
- [Database schema](docs/DATABASE_SCHEMA.md) lists every table, column, key, relationship, and what is present in the portable CARRIS database.
- [Project 7 selections](docs/PROJECT_7_SELECTION.md) records the operator IDs, public lines, areas, dates, API parameters, and exact matching rules needed for the challenge.
- [Sharing the database](docs/SHARING_DATABASE.md) explains full and reduced exports and the one-command restore workflow.
- [Verification](VERIFICATION.md) records the checks completed for this version.
- [Bunching prediction](docs/BUNCHING_MODEL.md) explains the Bunching and Simulate tabs: stop passages, the same-line and across-lines prediction models, the replay simulator and its validation gate, and how to retrain.
- [`backend/config/analysis_presets.json`](backend/config/analysis_presets.json) is the only Challenge 7 preset configuration. It contains stable public line codes and plan-source metadata, never local database package IDs.

## Prerequisites

- Docker Desktop, or Docker Engine with Compose v2
- Node.js 22 (the exact major version is in `.nvmrc`)
- GitHub CLI (`gh`) authenticated with access to the private repository when using the shared database
- The raw TML vehicle CSV and operation-plan GTFS directories only when rebuilding the database from source

## Quick start with the shared CARRIS database

Repository collaborators do not need the raw TML files or the 51 GB development database. The private [`database-v1`](https://github.com/kudzus/project7-prototype/releases/tag/database-v1) release contains the verified 564 MiB redacted CARRIS archive.

```sh
git clone https://github.com/kudzus/project7-prototype.git
cd project7-prototype
cp .env.example .env
# Edit .env and replace the local database password.

npm ci
./scripts/download_shared_database.sh
./scripts/restore_database.sh exports/headway-carris-all-carris.dump --replace
npm run dev
```

Open <http://127.0.0.1:5173>. The download script verifies the release checksum before restore. GitHub access remains controlled by membership of the private repository.

The default layout is:

```text
hackathon challenge/
├── project7-prototype/                 # this repository
└── raw-data/datasets/TML/
    ├── vehicles/<geohash>/<date>/*.csv
    └── operation-plans/<package>/*.txt
```

Different locations are supported; set `VEHICLES_PATH` and change the read-only plan mount in the import command.

## Rebuild from the raw source data

```sh
cp .env.example .env
# Edit .env and replace the local database password.

docker compose up -d --build --wait
docker compose run --rm api python import_vehicles.py --source-root /datasets/vehicles
docker compose run --rm \
  -v "$PWD/../raw-data/datasets/TML/operation-plans:/datasets/plans:ro" \
  api python import_plans.py --source-root /datasets/plans

npm ci
npm run dev
```

Open <http://127.0.0.1:5173>. The API is available at <http://127.0.0.1:8000/docs>.

Both imports are checksum-aware and safe to rerun. PostgreSQL data lives in the named Docker volume `vehicle_db`; `docker compose down` preserves it. `docker compose down -v` deletes the imported database and should only be used intentionally.

## Workspace behaviour

The application has one map and five sidebar tabs:

- **Routes** shows date-valid operation-plan variants. Preset groups appear first; the complete catalog is grouped by operator. Route choices draw shapes and optional stops only and never change the vehicle query.
- **Vehicles** selects carriers and either configured public lines or all vehicles. Changes remain pending until **Apply filters**.
- **Details** opens when a marker is clicked and retains the last loaded report if the marker expires or crosses an area boundary.
- **Bunching** predicts, for one line or several lines sharing a route in the selected window, the chance that each bus bunches within the next stops (10 on one line, 5 across lines), simulates holding times on the real trips, recommends one, lists the buses that bunch most, and draws a time–space diagram over the map. See [docs/BUNCHING_MODEL.md](docs/BUNCHING_MODEL.md).
- **Simulate** replays a real day of one line with a timing change (leave on schedule, headway-based dispatch, longer turnaround, control-stop or early-warning holding): as-run vs changed time–space diagrams, KPI cards with seed ranges, a benefit-vs-cost chart and a rule-based recommendation. See [Simulate tab](#simulate-tab-test-timing-changes).

The area selector is on the map. Every five-character area present in vehicle data for the selected date starts enabled. Applied, disabled, and pending boundaries remain visible. The six-character Challenge 7 zones can be drawn as reference overlays but do not silently restrict the default query.

The interface derives availability from the database. Missing operators, plans, routes, shapes, stops, or observations are supported partial states, which allows a later CARRIS-only database to run without frontend changes.

## Bunching tab: early warning

**Bunched** means that a bus follows the bus in front too closely:

- **one line:** the gap is less than 25 % of the planned gap;
- **several lines on a shared route:** the two buses pass a stop less than 60 s apart although they were planned at least 2 min apart.

**How to use it:** choose a line and a direction. Optionally tick other lines that share at least 3 of its stops (bunching *between* lines), then press **Predict**.

| On screen | Meaning |
| --- | --- |
| Lines in the diagram | one bus each; time runs to the right, stops go up. Lines that converge are bunching. |
| Dots (light → dark orange) | predicted risk that this bus bunches soon |
| Outlined dots | alerts: the risk is above the alert level, which is chosen from data, not by hand |
| Red dots | the bus *is* bunched there |
| Dashed lines and `H` | the same bus in the what-if run, held at that stop |
| "Buses that bunch most" | bus pairs ranked by the number of stops they were bunched; click one to highlight the pair |
| What-if table | holding time (0–180 s) → number of holds, total holding time, bunched passages; ★ = shortest hold with ≥ 75 % of the best reduction |

**The model:** logistic regression, trained on 5 days and tested on Fri 4 and Sun 6 Sep, which it never saw.

| Model | Predicts | Quality on unseen days |
| --- | --- | --- |
| One line (early warning) | bunching within the next **10** stops, while the gap is still ≥ 50 % of plan | ROC-AUC 0.82 (simple gap rule 0.76). 20 % of its alerts are right, twice the best simple rule (9.5 %). |
| Several lines | bunching within the next 5 stops, for pairs that stay on the same route | ROC-AUC 0.75 (simple rule 0.70) |

Model inputs: the gap and how it changed, own delay, delay of the bus in front, the **delay gap** between the two buses, the **delay carried over from the bus's previous trip**, planned gap, position on the route, peak hours and weekend. For several lines, three more: same line or not, and shared next stops. Trips with a wrong `trip_id` (median delay > 30 min, 5.3 % of trips) are excluded. Waze is not used, because its clock is UTC and its intensity labels are reversed.

## Simulate tab: test timing changes

The simulator replays a real day of one line, bus by bus, from the GPS data. **A timing change only decides *when* a bus leaves the terminal or waits at a stop.** Everything else comes from what really happened:

- **Own run times.** Each bus keeps the run times it really had between stops. With no change, the replay reproduces the real day exactly.
- **Late bus gets later.** A bus with a bigger gap in front picks up more passengers: extra stop time = *k* × (gap − the gap it really had). *k* is fitted from data (see the validation gate).
- **Vehicle chain.** A trip cannot start before its bus is back from its previous trip, so delays carry over.
- **Random runs (seeds).** A bus that is moved in time gets a small random change (±5 %) in its run times. Every option runs 10 times (30 in the validation), and the screen shows the range.

**How to use it:** choose a line (the 5 validated lines are at the top), a direction and a timing option, then press **Simulate**. Click another option, or a dot in the chart, to switch; this is instant after the first run.

### The timing options

| Code | Timing change | Package | Cost |
| --- | --- | --- | --- |
| **AS** | nothing: the real day ("as run"), the baseline | – | – |
| **D1** | leave the terminal exactly on schedule, if the bus is back | ceiling | an upper limit only, never recommended |
| **D2-2 / D2 / D2-5** | **headway-based dispatch:** wait at the terminal until the gap to the bus in front is ≥ 90 % of plan, at most 2 / 3 / 5 min | no cost | terminal waiting |
| **H1-60 / H1-120** | **control-stop holding:** at 2 stops (⅓ and ⅔ of the route), hold a bus that is > 3 min closer than planned, at most 60 / 120 s | low cost | passengers on board wait |
| **M-90** | **early-warning holding:** hold where the Bunching model fires, at most 90 s, at most 3 times per trip | low cost | passengers on board wait |
| **D2+H1** | headway dispatch and control-stop holding (max 90 s) | low cost | both |
| **T2-2 / T2-4** | **longer turnaround:** 2 / 4 min more layover between trips, then leave on schedule | investment | extra buses (computed) |

### Reading the screen

**Two time–space diagrams on the same time axis.** Top: *As run* (what really happened). Bottom: *With &lt;option&gt;*.

| Mark | Meaning |
| --- | --- |
| diagonal line | one bus driving along the route; steeper = faster |
| **red segment** | bunched: gap < 25 % of plan |
| faint grey line (bottom) | where that bus really was, so you see how far it moved |
| blue **D** | a changed departure at the terminal (the short line shows the shift) |
| orange **H** | a hold at a stop |

**KPI cards.** Each card shows the simulated value, the change against the real day, and the range over the random runs ("seeds a–b").

| Card | Meaning | Better when |
| --- | --- | --- |
| Bunched passages | share of stop visits where the bus was bunched | lower |
| **Excess wait / passenger** | extra seconds a passenger waits because the gaps are uneven, against perfectly even buses. This is the headline number. | lower |
| Headway variation (CV) | how uneven the gaps are (0 = perfectly even) | lower |
| Held on board / trip | seconds passengers on the bus wait at holds | cost |
| Wait at terminal / trip | seconds a bus waits before leaving | cost |
| Trip time | average trip duration | cost |
| Extra buses | buses needed for a longer turnaround | cost |

Card colours: green = better, red = worse, orange = a cost.

**Trade-off chart** (right). Each dot is one option: **up** = more excess wait saved per passenger, **right** = more seconds held or waiting per trip. The best options sit top-left. Bars show the range over the random runs, **★** marks the recommended option, and "(+1 bus)" means extra vehicles. Click a dot to show that option.

### How the recommendation is chosen

The rule was fixed before looking at the results, so nothing is cherry-picked:

1. Keep only options that reduce excess wait in at least 95 % of the random runs. D1 is a ceiling and is never recommended.
2. Find the largest reduction among them.
3. Recommend the **cheapest** option that gets at least 75 % of that reduction. Cheapest means extra buses first, then on-board holding, then terminal waiting.

The sidebar shows the result for the selected day and, for the 5 validated lines, the result tested on the held-out days (both directions, 16–20 h). The held-out result is the one to trust.

### Can we trust it? The validation gate

Checked by `backend/validate_simulator.py` on lines 742, 767, 728, 758 and 735, 16–20 h. *k* is fitted on Mon–Thu and tested on Fri 4 and Sun 6 Sep:

| Check | Result |
| --- | --- |
| Replay with no change | exact on every day ✔ |
| Fitted *k* | 0.005 (a separate regression gives 0.004) |
| Which departure gaps bunch most (0.25–0.5 of plan most, 0.9–1.1 least) | same ranking as reality ✔ |
| Bunching grows along the route | same as reality ✔ |
| Bunched share on the held-out days | over-predicted by about 30 % with the fitted *k* ✘ (with *k* = 0: within 5 %) |
| Moving a bus in time: scale its run times by the traffic at the new time? | tested: worse than keeping its own run times, so it is off |

The status is **partial**: patterns are right, but the exact amount is uncertain. So every held-out option is run with *k* = 0 and with the fitted *k*. An option only counts as **robust** if it helps in both cases, on both held-out days.

**Not modelled:** passenger loads, driver rules and breaks, and other operators at shared stops. D1 and T2 assume a late bus could leave as soon as it was back (+ at most 1 min).

### Results on the held-out days

| Line | Recommended | Excess wait saved (s / passenger) | Why it bunches |
| --- | --- | --- | --- |
| 742 | **D2-5** headway dispatch (D2 also robust) | 24 (15–34) | buses leave too soon after the one in front |
| 767 | **T2-2** +2 min turnaround, 1 extra bus | 34 (31–39) | lateness carries over from the previous trip |
| 728 | **M-90** early-warning holding | 10 (3–17) | gaps open on the road |
| 758 | **T2-2**, 1 extra bus | 62 (19–97) | lateness carries over from the previous trip |
| 735 | **T2-2**, 1 extra bus | 47 (28–64) | lateness carries over from the previous trip |

## Where the bunching code lives

| File | What it does |
| --- | --- |
| `backend/bunching.py` | stop passages, schedule repair, gaps, model features, holding what-if |
| `backend/bunching_api.py` | `GET /api/bunching/model`, `/lines`, `/shared`, `/diagram` |
| `backend/train_bunching_model.py` | trains both models → `backend/models/bunching_model*.json` |
| `backend/simulator.py` | replay simulator: timing options, vehicle chains, KPIs |
| `backend/validate_simulator.py` | validation gate, fits *k*, held-out results → `backend/models/simulator_validation.json` |
| `backend/sim_api.py` | `GET /api/sim/scenarios`, `/validation`, `/run` |
| `backend/test_bunching.py`, `backend/test_simulator.py` | tests (no database needed) |
| `src/BunchingPanel.tsx`, `src/bunching.ts`, `src/bunching.css` | Bunching tab |
| `src/SimulatePanel.tsx`, `src/sim.ts`, `src/sim.css` | Simulate tab |
| [`docs/BUNCHING_MODEL.md`](docs/BUNCHING_MODEL.md) | full method, numbers and assumptions |

API docs with every parameter: <http://127.0.0.1:8000/docs>.

## Retrain the models and revalidate the simulator

```sh
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements-model.txt
export DATABASE_URL=postgresql://headway:<password>@127.0.0.1:5432/headway   # host port from compose.yaml
.venv/bin/python backend/train_bunching_model.py      # ~4 min, rewrites both model files
.venv/bin/python backend/validate_simulator.py        # ~2 min, rewrites the validation + held-out results
docker compose restart api
```

## Development

```sh
npm run check

python3 -m venv .venv
.venv/bin/pip install -r backend/requirements-test.txt
.venv/bin/pytest -q backend
```

`npm run check` runs ESLint, Prettier validation, Vitest, TypeScript, and a production build. `npm run format` applies frontend formatting.

PostgreSQL integration tests are opt-in and use an isolated temporary schema:

```sh
docker compose run --rm \
  api sh -c 'pip install -r requirements-test.txt && TEST_DATABASE_URL="postgresql://headway:$PGPASSWORD@db:5432/headway" pytest -q'

docker compose run --rm api python verify_dataset.py
```

## Data safety and current scope

- Never commit `.env`, raw TML data, database dumps, or generated replay files; the repository ignore rules exclude them.
- Driver IDs are retained only in protected import/provenance tables and are never returned by the API or displayed in the UI.
- Requests are limited to four hours and 200,000 observations, including 120 seconds of replay history.
- Use the documented export workflow to create a redacted CARRIS-only archive for collaborators; generated archives are never committed.
- Database archives belong in `exports/` and are ignored by Git. Share them as private release/cloud assets, never as normal repository files.