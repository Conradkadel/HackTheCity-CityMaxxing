# Database schema

The application uses PostgreSQL. The schema is created by the numbered files in `backend/migrations/`; the definitions below describe the current schema and the portable CARRIS database published in the private `database-v1` release.

PostgreSQL database IDs such as `version_id` and `package_id` are internal surrogate keys. They must not be placed in presets or treated as stable identifiers. Configuration uses event-facing agency IDs, public line codes, source names, and dates instead.

## Relationship overview

```text
dataset_versions ──< vehicle_events ──< event_sources
       │                    │
       ├── active_dataset   └── availability (date/area/operator summary)
       └── import_files

plan_packages ──< plan_records
      │
      ├──< schedule_routes
      ├──< schedule_trips
      └──< schedule_stop_visits

analysis_runs ──< bunching_episodes ──< bunching_evidence
```

A vehicle observation is resolved to a public line with these conditions:

```text
vehicle_events.agency_id = plan_packages.event_agency_id
vehicle_events.operational_date BETWEEN plan_packages.active_from AND active_until
vehicle_events.trip_id = schedule_trips.trip_id
schedule_trips.route_id = schedule_routes.route_id
package_id is equal throughout the plan-side joins
```

The optional scheduled-stop match additionally uses `vehicle_events.stop_id = schedule_stop_visits.stop_id`. Stop matching is not required to identify a route, so observations are retained when the stop is absent or unmatched.

## Dataset and import tables

### `dataset_versions`

One row describes one complete vehicle-data import.

| Column | Type | Rules / meaning |
| --- | --- | --- |
| `id` | `bigserial` | Primary key. |
| `inventory_hash` | `text` | Hash of the source-file inventory. The portable export appends its subset mode. |
| `status` | `text` | `loading` or `ready`. |
| `created_at` | `timestamptz` | Import creation time. |
| `completed_at` | `timestamptz` | Nullable completion time. |
| `source_root` | `text` | Source location; replaced with `portable-carris-export` in the shared database. |

### `active_dataset`

Selects the one dataset version exposed by the API.

| Column | Type | Rules / meaning |
| --- | --- | --- |
| `singleton` | `boolean` | Primary key constrained to `true`, ensuring at most one row. |
| `version_id` | `bigint` | Foreign key to `dataset_versions.id`. |

### `import_files`

Audit information for every imported vehicle CSV in a full source database.

| Column | Type | Rules / meaning |
| --- | --- | --- |
| `version_id` | `bigint` | Foreign key to `dataset_versions.id`; part of the primary key. |
| `path` | `text` | Source-relative file path; part of the primary key. |
| `checksum` | `text` | File checksum. |
| `bytes` | `bigint` | Source file size. |
| `counts` | `jsonb` | Import counters and validation results. |
| `elapsed_seconds` | `double precision` | Import duration. |

This table is empty in the portable CARRIS database because it exposes source-file history that the viewer does not need.

## Vehicle tables

### `vehicle_events`

The main fact table. One row is one deduplicated vehicle-position observation.

| Column | Type | Rules / meaning |
| --- | --- | --- |
| `version_id` | `bigint` | Foreign key to `dataset_versions.id`; part of the primary key. |
| `observation_key` | `text` | Deterministic deduplication key; part of the primary key. |
| `event_id` | `text` | Event identifier from the normalized observation. |
| `agency_id` | `text` | Event-facing operator code, for example CARRIS `IA9T6`. |
| `vehicle_id` | `text` | Vehicle identifier. |
| `driver_id` | `text` | Required by the source schema; always `redacted` in the shared database and never returned by the API. |
| `trip_id` | `text` | Exact trip identifier used for operation-plan resolution. It is not the public line number. |
| `stop_id` | `text` | Reported stop identifier; may fail to match a scheduled stop. |
| `created_at` | `timestamptz` | Time the source says the vehicle report was created. |
| `received_at` | `timestamptz` | Time the report was received. |
| `operational_date` | `date` | Service date used to choose the valid plan package. |
| `latitude` | `double precision` | WGS84 latitude, constrained to `-90..90`. |
| `longitude` | `double precision` | WGS84 longitude, constrained to `-180..180`. |
| `geohash_5` | `text` | Five-character parent area used for spatial filtering. |

Important indexes support `(version_id, geohash_5, created_at)`, operator/time, vehicle/time, and exact route resolution by `(version_id, agency_id, operational_date, trip_id, created_at)`.

### `event_sources`

Many-to-one provenance linking a deduplicated observation back to every raw source occurrence.

| Column | Type | Rules / meaning |
| --- | --- | --- |
| `version_id` | `bigint` | Part of the primary and foreign key to `vehicle_events`. |
| `observation_key` | `text` | Part of the primary and foreign key to `vehicle_events`. |
| `source_file` | `text` | Original source file. |
| `source_event_id` | `text` | Original event ID. |
| `source_driver_id` | `text` | Sensitive source value; never exposed by the API. |
| `source_geohash` | `text` | Original geohash. |
| `source_received_at` | `timestamptz` | Original receipt time. |

This table is empty in the portable CARRIS database. Omitting it removes raw driver identifiers and most of the full database's provenance storage.

### `availability`

Precomputed coverage used to build the date-aware operator and map-area catalog without scanning all observations.

| Column | Type | Rules / meaning |
| --- | --- | --- |
| `version_id` | `bigint` | Foreign key to `dataset_versions.id`; part of the primary key. |
| `geohash_5` | `text` | Five-character map area; part of the primary key. |
| `calendar_date` | `date` | Lisbon-local calendar date; part of the primary key. |
| `agency_id` | `text` | Operator; part of the primary key. |
| `observations` | `bigint` | Observation count for the group. |
| `first_event` | `timestamptz` | Earliest report in the group. |
| `last_event` | `timestamptz` | Latest report in the group. |

The portable export rebuilds this table from only the observations it includes.

## Operation-plan tables

### `plan_packages`

One row describes one imported GTFS-like operation-plan package and its validity window.

| Column | Type | Rules / meaning |
| --- | --- | --- |
| `id` | `bigserial` | Primary key; internal and not stable across databases. |
| `source_name` | `text` | Stable source-directory/package name. |
| `checksum` | `text` | Hash of all source plan files. Unique together with `source_name`. |
| `agency` | `jsonb` | Preserved agency metadata. |
| `feed` | `jsonb` | Preserved feed metadata. |
| `counts` | `jsonb` | Imported row counts by GTFS table. The portable export records raw `stop_times` as zero because their JSON copies are omitted. |
| `imported_at` | `timestamptz` | Import time. |
| `event_agency_id` | `text` | Operator ID used by `vehicle_events`, for example `IA9T6`. |
| `active_from` | `date` | First operational date for route matching. |
| `active_until` | `date` | Last operational date for route matching. |
| `external_plan_id` | `text` | TML-facing plan ID such as `82YP2`. |
| `normalized_gtfs_id` | `text` | Normalized GTFS/source identifier. |

The agency and validity columns are indexed together. Configuration metadata supplies these stable mappings when a plan is imported.

### `plan_records`

Lossless storage of original GTFS rows. Each JSON object keeps the source strings and any additional columns supplied by TML.

| Column | Type | Rules / meaning |
| --- | --- | --- |
| `package_id` | `bigint` | Foreign key to `plan_packages.id`; part of the primary key. |
| `table_name` | `text` | Source filename without `.txt`, such as `routes`, `trips`, `stops`, or `shapes`; part of the primary key. |
| `row_number` | `integer` | One-based source row number; part of the primary key. |
| `data` | `jsonb` | Complete source row keyed by its original column names. |

Required imported source tables are `agency`, `feed_info`, `routes`, `trips`, `stops`, `shapes`, and `stop_times`; extra GTFS tables are preserved automatically. The portable database keeps all relevant CARRIS records except raw `stop_times` JSON. Stop times remain available in normalized form through `schedule_stop_visits`, avoiding a large duplicate representation.

JSON expression indexes accelerate route, trip, stop, and shape lookup in a full database.

## Normalized schedule lookup tables

These tables duplicate only the fields needed for fast route resolution and UI queries. Every identifier is package-scoped.

### `schedule_routes`

| Column | Type | Rules / meaning |
| --- | --- | --- |
| `package_id` | `bigint` | Foreign key to `plan_packages.id`; part of the primary key. |
| `route_id` | `text` | Internal route variant; part of the primary key, for example `118_0`. |
| `line_short_name` | `text` | Public line code, for example `755` or `28E`. |
| `route_long_name` | `text` | Passenger-facing route description. |
| `route_color` | `text` | GTFS display color, or an empty string. |

### `schedule_trips`

| Column | Type | Rules / meaning |
| --- | --- | --- |
| `package_id` | `bigint` | Foreign key to `plan_packages.id`; part of the primary key. |
| `trip_id` | `text` | Exact trip ID; part of the primary key, for example `6656_20260606_118_0_2`. |
| `route_id` | `text` | Internal route variant joined to `schedule_routes` within the same package. |
| `shape_id` | `text` | Shape referenced by `plan_records` where `table_name='shapes'`. |
| `direction_id` | `text` | Direction value from the plan. |
| `service_id` | `text` | GTFS service/calendar identifier. |

An index on `(package_id, route_id, direction_id)` supports route catalog and overlay queries.

### `schedule_stop_visits`

| Column | Type | Rules / meaning |
| --- | --- | --- |
| `package_id` | `bigint` | Foreign key to `plan_packages.id`; part of the primary key. |
| `trip_id` | `text` | Trip; part of the primary key. |
| `stop_id` | `text` | Scheduled stop; part of the primary key. |
| `stop_sequence` | `integer` | Position in the trip; part of the primary key. |
| `arrival_time` | `text` | GTFS time string. Kept as text because service times may exceed `24:00:00`. |
| `departure_time` | `text` | GTFS time string with the same convention. |

The trip/stop index supports the optional scheduled-stop lookup shown in vehicle details.

### `schedule_operator_packages`

| Column | Type | Rules / meaning |
| --- | --- | --- |
| `agency_id` | `text` | Primary key. |
| `package_id` | `bigint` | Foreign key to `plan_packages.id`. |

This is a legacy one-package-per-operator lookup retained for backward compatibility. Current code selects packages by `event_agency_id` **and operational date** from `plan_packages`; the shared database does not populate this legacy table.

## Precomputed analysis tables

These tables are created by `006_bunching_analysis.sql`. They remain empty until the versioned batch command in [Precomputed bunching analysis](PRECOMPUTED_BUNCHING.md) is run.

### `analysis_runs`

One row records one detector execution for an active vehicle dataset, operational date, and operator.

| Column | Type | Rules / meaning |
| --- | --- | --- |
| `id` | `bigserial` | Primary key. |
| `dataset_version` | `bigint` | Vehicle dataset that was analyzed. |
| `operational_date` | `date` | Service day. |
| `operator_id` | `text` | Event-facing operator. |
| `detector_version` | `text` | Immutable algorithm name, currently `stop-headway-v1`. |
| `scope` | `text` | `all_observed_lines` or `selected_lines`. |
| `selected_lines` | `text[]` | Exact public lines included by this run. |
| `parameters` | `jsonb` | Exact thresholds and behavioral flags. |
| `status` | `text` | `running`, `completed`, or `failed`. |
| `started_at`, `completed_at` | `timestamptz` | Execution timestamps. |
| `counts` | `jsonb` | Lines, raw detections, episodes, and classifications. |
| `error_message` | `text` | Truncated failure detail; null after success. |

Runs are append-only analysis history. APIs choose the latest completed matching run instead of relying on one mutable result.

### `bunching_episodes`

One row represents repeated evidence for one unordered pair of vehicle trips on a route and direction. It stores operator, public line, package/route, both vehicle and trip IDs, time extent, first/last stop, evidence counts, minimum observed gap, maximum planned gap, approximate stop-centroid coordinates, and classification.

`multi_stop_candidate` requires at least two distinct affected stops. A `single_point` row is retained for audit and threshold research but excluded from normal candidate statistics.

### `bunching_evidence`

Ordered stop-level support for an episode. Each row stores stop ID/name/sequence, both vehicle/trip IDs, reported and scheduled timestamps, observed and planned gaps, and scheduled-stop coordinates. Deleting an analysis run cascades through its episodes and evidence.

## What is present in `database-v1`

The published default `all-carris` archive contains:

- one ready active dataset version;
- all imported CARRIS `IA9T6` observations, with `driver_id='redacted'`;
- availability summaries rebuilt from those observations;
- the date-valid CARRIS plan package metadata;
- route, trip, stop, shape, and normalized scheduled-stop data required by the application.

It intentionally leaves `import_files`, `event_sources`, and `schedule_operator_packages` empty, removes unrelated operators and plans, and omits duplicated raw `stop_times` JSON from `plan_records`. Empty tables remain part of the schema, so the same backend code works with full and reduced databases.

The published `database-v1` archive predates precomputed results. On first startup the migration creates the analysis tables as empty tables; collaborators can then run the batch analyzer against the restored observations.
