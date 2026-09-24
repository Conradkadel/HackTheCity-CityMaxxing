# RouteMaxxing · Challenge 7 analysis workspace

Phase-one data visualisation for TML Challenge 7: inspect recorded Lisbon vehicle positions beside the operation plan that was valid on the vehicle's operational date. The application is a local React/Leaflet workspace backed by FastAPI and PostgreSQL.

The workspace keeps the complete 00:00–24:00 day visible while a movable 30-minute to four-hour analysis window selects the data to load. Replay then runs precisely inside that applied window.

This phase visualises source evidence and marks rule-based **possible bunching candidates**. It does not claim that a candidate is a confirmed operational incident or that a vehicle is delayed.

## Repository guide

- [Database construction](docs/DATABASE_CONSTRUCTION.md) explains the raw inputs, schema, repeatable imports, deduplication, plan normalisation, and route-resolution logic.
- [Implemented features and developer handoff](docs/IMPLEMENTED_FEATURES.md) gives a complete product, architecture, API, analysis, privacy, and limitation overview for new contributors.
- [Database schema](docs/DATABASE_SCHEMA.md) lists every table, column, key, relationship, and what is present in the portable CARRIS database.
- [Typical route traffic](docs/TRAFFIC_MAP.md) explains the Waze map filter, matching, historical averaging and coverage limits.
- [Bus-line schedule comparison](docs/LINE_ANALYSIS.md) explains exact trip-to-timetable resolution, the time–space chart, candidate bunching rules, and interpretation limits.
- [Precomputed bunching analysis](docs/PRECOMPUTED_BUNCHING.md) documents versioned batch runs, consolidated multi-stop episodes, and statistics APIs.
- [Findings](docs/FINDINGS.md) explains the Findings tab: weekly problem lines, hours, stops and causes, shared-stretch analysis, and `build_findings.py`.
- [Bunching prediction](docs/BUNCHING_MODEL.md) explains the Bunching and Simulate tabs, the v4 early-warning model, holding simulation, and retraining workflow.
- [Project 7 selections](docs/PROJECT_7_SELECTION.md) records the operator IDs, public lines, areas, dates, API parameters, and exact matching rules needed for the challenge.
- [Sharing the database](docs/SHARING_DATABASE.md) explains full and reduced exports and the one-command restore workflow.
- [Research background](docs/research/README.md) holds the early data analysis, dataset design and findings used in the pitch.
- [Verification](VERIFICATION.md) records the checks completed for this version.
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

The sidebar has four numbered tabs, in the order of the pitch:

1. **Findings** (opens first): where, when and why buses bunch every weekday, and the change to make on each problem line. It has an action-plan board, a map of terminals, worst stops and shared stretches, and an "Open in Simulation" button per line. See [docs/FINDINGS.md](docs/FINDINGS.md). Live vehicles, areas and the replay dock are hidden here.
2. **Risk prediction** (formerly *Bunching*): the early-warning model replayed on a recorded day (not a live feed), with the holding what-if. Shows a plain-language summary, a "how to read" guide and a list of every warning and what happened next.
3. **Simulation** (formerly *Simulate*): replays a real day with one change. The changes have plain names (e.g. "Wait for a proper gap at the terminal", "2 more minutes of break at the terminal"); the short codes (D2, T2-2, …) are only used inside the backend.
4. **Explore data**: *Network & routes* (formerly *Routes*, with line analysis and the weekly signals) and *Vehicle details* (formerly *Details*).

The panels in detail:

- **Routes** shows date-valid operation-plan variants. Preset groups appear first; the complete catalog is grouped by operator. Route choices draw shapes and optional stops only and never change the vehicle query.
- **Analyze line** opens a large time–space comparison for a public line. It shows each observed vehicle–trip run against its exact planned stop schedule and marks possible convergence where observed headways collapse relative to the timetable.
- **Week** beside a route opens the precomputed Monday–Sunday history, listing the times and affected stops for each consolidated multi-stop candidate and clearly marking dates that have not been analyzed.
- **Map bunching candidates** update with replay time. Nearby vehicle pairs that report the same scheduled stop after a planned headway collapse receive red halos and a dashed connector; the map count can be hidden without changing vehicle filters.
- **Details** opens when a marker is clicked and retains the last loaded report if the marker expires or crosses an area boundary.
- **Bunching** predicts near-term bunching risk, compares holding scenarios, and provides a time–space diagram.
- **Simulate** replays a real operating day with dispatch, turnaround, and holding interventions.

Vehicle, carrier, line, region, route, traffic, and overlay controls live in **Map Settings**.

The area selector is on the map. Every five-character area present in vehicle data for the selected date starts enabled. Applied, disabled, and pending boundaries remain visible. The six-character Challenge 7 zones can be drawn as reference overlays but do not silently restrict the default query.

The interface derives availability from the database. Missing operators, plans, routes, shapes, stops, or observations are supported partial states, which allows a later CARRIS-only database to run without frontend changes.

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

To precompute reproducible multi-stop candidates for later statistics:

```sh
docker compose run --rm api \
  python analyze_bunching.py --date 2026-09-01 --operator IA9T6
```

Precompute the Monday–Sunday week containing a date with:

```sh
docker compose run --rm api \
  python analyze_bunching.py --week-containing 2026-09-01 \
  --operator IA9T6
```

The replay map remains an on-demand view. Batch results are versioned separately and are described in [Precomputed bunching analysis](docs/PRECOMPUTED_BUNCHING.md).

## Data safety and current scope

- Never commit `.env`, raw TML data, database dumps, or generated replay files; the repository ignore rules exclude them.
- Driver IDs are retained only in protected import/provenance tables and are never returned by the API or displayed in the UI.
- Requests are limited to four hours and 200,000 observations, including 120 seconds of replay history.
- Use the documented export workflow to create a redacted CARRIS-only archive for collaborators; generated archives are never committed.
- Database archives belong in `exports/` and are ignored by Git. Share them as private release/cloud assets, never as normal repository files.
