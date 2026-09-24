# Headway · Challenge 7 analysis workspace

Phase-one data visualisation for TML Challenge 7: inspect recorded Lisbon vehicle positions beside the operation plan that was valid on the vehicle's operational date. The application is a local React/Leaflet workspace backed by FastAPI and PostgreSQL.

This phase visualises source evidence. It does **not** yet detect bus bunching or claim that a vehicle is delayed.

## Repository guide

- [Database construction](docs/DATABASE_CONSTRUCTION.md) explains the raw inputs, schema, repeatable imports, deduplication, plan normalisation, and route-resolution logic.
- [Database schema](docs/DATABASE_SCHEMA.md) lists every table, column, key, relationship, and what is present in the portable CARRIS database.
- [Project 7 selections](docs/PROJECT_7_SELECTION.md) records the operator IDs, public lines, areas, dates, API parameters, and exact matching rules needed for the challenge.
- [Sharing the database](docs/SHARING_DATABASE.md) explains full and reduced exports and the one-command restore workflow.
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

The application has one map and three sidebar tabs:

- **Routes** shows date-valid operation-plan variants. Preset groups appear first; the complete catalog is grouped by operator. Route choices draw shapes and optional stops only and never change the vehicle query.
- **Vehicles** selects carriers and either configured public lines or all vehicles. Changes remain pending until **Apply filters**.
- **Details** opens when a marker is clicked and retains the last loaded report if the marker expires or crosses an area boundary.

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

## Data safety and current scope

- Never commit `.env`, raw TML data, database dumps, or generated replay files; the repository ignore rules exclude them.
- Driver IDs are retained only in protected import/provenance tables and are never returned by the API or displayed in the UI.
- Requests are limited to four hours and 200,000 observations, including 120 seconds of replay history.
- Use the documented export workflow to create a redacted CARRIS-only archive for collaborators; generated archives are never committed.
- Database archives belong in `exports/` and are ignored by Git. Share them as private release/cloud assets, never as normal repository files.
