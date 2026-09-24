# Database construction

This document describes how the local PostgreSQL database is built from the TML vehicle exports and operation-plan packages. It makes the result reproducible for colleagues and defines what a future reduced database must preserve.

## 1. Inputs

### Vehicle observations

The vehicle importer recursively reads every `*.csv` below one source root. The supplied data is normally partitioned as:

```text
vehicles/<five-character-geohash>/<YYYYMMDD>/<file>.csv
```

Each row must contain these columns:

```text
_id, agency_id, vehicle_id, driver_id, trip_id, stop_id,
created_at, received_at, operational_date, latitude, longitude, geohash_5
```

`created_at` and `received_at` are Unix milliseconds. `operational_date` is `YYYYMMDD`. Latitude and longitude must be finite WGS84 coordinates, and `geohash_5` must be a valid five-character geohash.

### Operation plans

Each direct child of the operation-plan source root is one GTFS-like package. A package must contain:

```text
agency.txt, feed_info.txt, routes.txt, trips.txt,
stops.txt, shapes.txt, stop_times.txt
```

Additional GTFS tables are preserved automatically. The official 2026 packages used for Challenge 7 are listed in [Project 7 selections](PROJECT_7_SELECTION.md). Their stable directory names are mapped to event-facing agency IDs and validity dates in `backend/config/analysis_presets.json`.

Raw inputs are not part of this repository and are mounted read-only into the importer containers.

## 2. Start PostgreSQL and apply the schema

Copy `.env.example` to `.env`, choose a local password, and point `VEHICLES_PATH` to the vehicle source root. Then start the services:

```sh
docker compose up -d --build --wait
```

The API applies every numbered SQL file in `backend/migrations` in a transaction while holding a migration lock. Migrations are idempotent and run in filename order.

The schema has four groups of tables:

| Purpose | Tables |
| --- | --- |
| Dataset lifecycle | `dataset_versions`, `active_dataset`, `import_files` |
| Vehicle facts and provenance | `vehicle_events`, `event_sources`, `availability` |
| Raw operation plans | `plan_packages`, `plan_records` |
| Normalised schedule lookup | `schedule_routes`, `schedule_trips`, `schedule_stop_visits` |
| Versioned analysis | `analysis_runs`, `bunching_episodes`, `bunching_evidence` |

## 3. Import vehicle observations

```sh
docker compose run --rm api \
  python import_vehicles.py --source-root /datasets/vehicles
```

The importer performs the following work:

1. Recursively inventories CSV files and computes a SHA-256 checksum for every file plus the complete inventory.
2. Validates headers and each row. Invalid rows are counted by reason and skipped.
3. Creates a deterministic observation identity from agency, vehicle, event time, coordinates, trip, and stop.
4. Collapses duplicate observations while retaining the earliest receipt and source provenance.
5. Commits each source file independently so an interrupted import can resume.
6. Builds `availability` totals by dataset version, five-character area, Lisbon calendar date, and agency.
7. Marks the new version ready and switches `active_dataset` only after all files succeed.

The existing active dataset remains usable if a rebuild fails. If the source inventory changes, the importer requires an explicit new version:

```sh
docker compose run --rm api \
  python import_vehicles.py --source-root /datasets/vehicles --rebuild
```

Do not use `--rebuild` merely to rerun an unchanged import; unchanged inventories are detected and skipped.

## 4. Import operation plans

Mount the directory containing the package folders and run:

```sh
docker compose run --rm \
  -v "$PWD/../raw-data/datasets/TML/operation-plans:/datasets/plans:ro" \
  api python import_plans.py --source-root /datasets/plans
```

For each package, the importer:

1. Validates required tables, identifiers, coordinate ranges, and sequence numbers.
2. Fingerprints all `*.txt` files together; an unchanged package is skipped.
3. Stores every source row as JSONB in `plan_records`, preserving source strings and leading zeroes.
4. Registers the stable source name, event agency ID, external TML plan ID, and inclusive validity dates in `plan_packages`.
5. Builds the normalised route, trip, and stop-visit lookup tables used by the API.
6. Rolls the whole package back if validation fails or source files change during import.

Local numeric `plan_packages.id` values are implementation details. They must not be copied into configuration or used as durable identifiers.

## 5. How a vehicle row is linked to a public line

Resolution happens when observations are queried, not when they are imported:

1. Use the vehicle row's `agency_id` and `operational_date` to choose the plan package whose inclusive validity range contains that date.
2. Match `vehicle_events.trip_id` exactly to `schedule_trips.trip_id` inside that package.
3. Follow `schedule_trips.route_id` to `schedule_routes` to obtain the public line, internal route, and route name.
4. Optionally match `stop_id` to `schedule_stop_visits` for scheduled-stop information.

A stop match is never required to identify the route. A vehicle row with no exact trip match remains available as `routeMatchStatus: "unmatched"` in All vehicles mode. No fuzzy trip matching is performed.

The relevant indexes are created by the migrations, including vehicle area/time, operator/time, vehicle/time, trip resolution, plan validity, routes, trips, stops, and shapes.

## 6. Derived data and privacy

`availability` is a query-acceleration summary, not another source of observations. The API reads only the active completed vehicle dataset unless the legacy incomplete-import preview is explicitly requested.

Driver IDs exist in the raw source and provenance tables so import fidelity can be audited. They are deliberately absent from every API response and frontend type.

## 7. Validate a constructed database

```sh
docker compose ps
curl http://127.0.0.1:8000/api/health
curl 'http://127.0.0.1:8000/api/workspace-catalog?date=2026-09-01'
docker compose run --rm api python verify_dataset.py
```

`verify_dataset.py` reports totals, representative timings, and PostgreSQL `EXPLAIN (ANALYZE, BUFFERS)` output. Also run the automated checks from the README before sharing a dump.

Useful database checks:

```sql
SELECT id, status, completed_at FROM dataset_versions ORDER BY id;
SELECT * FROM active_dataset;
SELECT calendar_date, agency_id, sum(observations)
FROM availability
GROUP BY calendar_date, agency_id
ORDER BY calendar_date, agency_id;
SELECT source_name, event_agency_id, active_from, active_until
FROM plan_packages
ORDER BY event_agency_id, active_from;
```

## 8. Requirements for a future reduced database

A CARRIS-only export may omit unrelated vehicle rows and plan packages. It must keep referentially complete rows for its chosen active dataset version and the CARRIS date-valid plan: dataset lifecycle rows, selected `vehicle_events`, relevant `event_sources` if provenance is required, rebuilt `availability`, the applicable `plan_packages`/`plan_records`, and their normalised schedule rows.

The export and restore workflow is documented in [Sharing the database](SHARING_DATABASE.md). The workspace treats omitted operators, lines, plans, shapes, stops, and observations as supported partial states.

## 9. Precompute bunching candidates

Database construction and bunching analysis are separate lifecycle steps. Imports preserve source facts; the batch analyzer creates replaceable/versioned analytical results against the active dataset.

```sh
docker compose run --rm api \
  python analyze_bunching.py --date 2026-09-01 --operator IA9T6
```

Every execution appends an `analysis_runs` record with its detector version and exact thresholds. Supporting stop detections are consolidated into episodes so one pair travelling together across several stops is not counted as several independent bunches. See [Precomputed bunching analysis](PRECOMPUTED_BUNCHING.md) for the algorithm, statistics endpoints, and limitations.
