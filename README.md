# Headway - Project 7 historical replay

A local React/TypeScript + Leaflet map of recorded vehicle positions. This first milestone displays observations, not bunching classifications or scheduled delays. Online OpenStreetMap tiles provide background context; transport data stays local.

## Run on your device

### PostgreSQL workflow (new default)

Install Docker Desktop (or Docker Engine with Compose v2) and Node 22.12+ first. Docker is now installed on the implementation machine; services and all 17 backend tests have passed, and the full import has been started. Final import verification and measured query performance remain pending; see `VERIFICATION.md`. No cloud resources are used.

Copy `.env.example` to `.env` and edit it locally: set a local database password and `VEHICLES_PATH` to the complete `raw-data/datasets/TML/vehicles` directory (absolute path recommended). Do not commit `.env`. The source directory is mounted read-only. The password is for this local development database, not an existing account.

Run these as separate steps from this directory:

```sh
docker compose up -d --build --wait
docker compose run --rm api python import_vehicles.py --source-root /datasets/vehicles
npm ci
npm run dev
```

Starting services never imports data. PostgreSQL and the API bind only to 127.0.0.1; Vite proxies `/api` to port 8000. Database storage uses the persistent `vehicle_db` named volume. `docker compose down` preserves it; **do not use `down -v` unless intentionally deleting the database**. Python runs inside the API container; teammates do not need host Python for normal use.

The importer discovers every CSV under the explicit root (the supplied inventory has 169, including standalone Soflusa), preserving all operators. It checksums files, COPY-loads bounded batches, and commits each completed file atomically. Repeating an unchanged import is a no-op; interrupted versions resume completed files. Changed inventories require the same command with `--rebuild`. A rebuild creates a separate version; the active pointer changes only after all files and availability summaries succeed. Old versions are retained, so allow disk space for raw data, indexes, lineage and multiple versions.

Bad rows are rejected with reason counts in `import_files.counts`; a malformed file header or failed batch rolls back that whole file. Import output reports per-file counts and total elapsed time. `event_sources` preserves contributing filenames and source identifiers. Identifiers remain text. Driver IDs stay in the local database/lineage only, never observation responses. Duplicate observation identity is operator + vehicle + event time + coordinates + trip + stop; earliest receipt wins. A source folder is not a vehicle identity. Actual row `geohash_5` determines strict cell membership; filenames are lineage only.

The UI defaults to eycs2, 1 September 2026, 07:00–09:00 with Carris and four CMet IDs when available. Choose multiple cells, operators, **Lisbon calendar date** and local start/end, then press **Load selection**. The map can overlay each available geohash cell; click a boundary to add or remove it from the pending area selection, and use **Zoom to selected areas** to inspect its coverage. End earlier than start crosses midnight; ambiguous/nonexistent DST endpoints are rejected. Limits: four elapsed hours and 200,000 observations including 120s prehistory. Larger selections fail explicitly, never sample. Empty results are genuinely empty. The previous replay remains while loading or on failure; edits cancel outdated loads. Visible-operator checkboxes filter the already loaded data, whereas query-operator checkboxes change the next request.

Strict filtering does not follow a vehicle outside selected cells. Its last in-area report may remain until the existing 120-second expiry. Carris can include trams; other imported operators are not assumed to be buses. No PostGIS, schedules, Waze, route inference or bunching scores are added.

### Preview while vehicles import

Enable **Preview incomplete import** in Vehicle replay. This reads only committed file transactions from the newest dataset version; it never activates or completes that version. Availability is grouped from actual event-time Lisbon dates, not operational-date folder names. A refresh can take up to 30 seconds and adds database read load, so it is manual and never starts a replay automatically. Choose available areas/operators/date, then **Load selection**. Refresh again to discover newly committed coverage.

The preview banner shows committed-file and observation counts at the availability refresh. Each replay response has its own committed snapshot; counts and earliest duplicate receipt times can change as later files commit. A replay already in the browser remains unchanged until loaded again. Absence in partial coverage is not evidence of no service. Existing prehistory, strict area, four-hour and 200,000-record limits apply. Uncheck preview and refresh to use the completed active dataset; previously loaded partial data stays labelled until replaced.

API: `/api/availability?preview=true`; `/api/observations?...&preview=true&dataset_version=ID`. Preview responses include `partialPreview` and `importProgress`; observation metadata retains these markers even if that version finishes between requests. Normal endpoints still use only the active completed dataset. Preview availability may time out under heavy load; retry later rather than repeatedly refreshing.

### Running verification

Backend validation tests can run without Docker:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-test.txt
.venv/bin/python -m pytest backend -q
```

The integration test skips unless `TEST_DATABASE_URL` is supplied. It creates and drops a uniquely named test schema, not the application's tables. With Compose running, use the container's existing local credentials without copying them into commands:

```sh
docker compose run --rm -e TEST_DATABASE_URL=postgresql:// api sh -c 'pip install -r requirements-test.txt && pytest -q'
docker compose run --rm api python verify_dataset.py
docker compose run --rm -v "$PWD/public/data:/extract:ro" api python verify_dataset.py --extract /extract/replay.json
```

`verify_dataset.py` prints per-file import counts/timings, totals, representative one-cell/three-cell query timings and EXPLAIN ANALYZE/BUFFERS plans. The optional extract comparison counts differing observation identities and receipt times. Differences may reflect all-file coverage, stricter validation and cross-file deduplication; inspect nonzero differences rather than assuming parity. Until this runs after the full import, no response-time or total-row claims are made.

Integration fixture tests cover overlapping sources, leading zeros, rejected coordinates, Soflusa, strict cross-cell filtering, prehistory, empty results, invalid parameters, limits, failed batches, resumability and idempotency. Browser checks with real API selectors, changed dates, playback and details still require a running imported database. A teammate must perform second-device verification using the three startup commands and their privately supplied source directory.

Important files: `compose.yaml`; `backend/migrations/001_vehicles.sql` (schema/indexes); `backend/import_vehicles.py` (ETL); `backend/domain.py` (validation/time/contract); `backend/app.py` (API); `src/api.ts` (requests/cancellation); `src/main.tsx` (selectors/map); `src/replay.ts` (deterministic replay).

### Operation-plan explorer

### Schedule-linked route replay

The **Schedule-linked route replay** tab is the Project 7 route-analysis view. It is deliberately limited to Carris Metropolitana Areas 1–4, where observed `trip_id` values were measured against the imported plan packages. Select a Challenge 7 corridor, line/route variant and direction; the app loads only reports with an exact operator, trip and stop match. The inspector shows the planned stop time and the **reported-stop time difference**. A report timestamp is not a confirmed arrival/departure, so this is a schedule reference rather than a verified delay.

The operation plans declare 2025 validity while vehicle observations are from 2026. The UI keeps this mismatch visible. Route identity comes from exact IDs, but do not make 2026 adherence claims without a confirmed 2026 plan. The matched-stop panel compares actual and scheduled gaps between distinct trips without applying a bunching threshold.

Use the top **Operation plans · 2025 reference** tab. Choose an operator/package, a line/route variant, optionally a direction code, then a planned trip. The map draws the supplied shape and that trip's stop locations; click a marker or a scheduled visit in the sidebar to inspect the stop and scheduled times. Stop locations can be toggled. Missing geometry is not inferred. No vehicle overlay, schedule-adherence calculation or day-of-service claim is made. Times such as `25:10:00` remain service-day times, not converted to a misleading clock time.

Plans use separate `plan_packages` and `plan_records` tables in the same PostgreSQL database. All 46 supplied TXT tables and original string fields (including auxiliary calendars/fares/resources) are retained as indexed JSON records; only routes, trips, shapes and stop visits are currently visualized. IDs are scoped by immutable package ID, not merged across operators or versions. Each package commits atomically; the checksum makes unchanged reruns a no-op and changed packages create another selectable version. Failed packages roll back without deleting previous versions. This does not use the separate `TML/stops.csv`.

Explicit import command, run from the project directory (adjust the host source path if needed):

```sh
docker compose run --rm -v "$PWD/../raw-data/datasets/TML/operation-plans:/datasets/plans:ro" api python -u import_plans.py --source-root /datasets/plans --wait-for-vehicles
```

`--wait-for-vehicles` waits on the existing vehicle-import lock before loading plans; omit it only if concurrent loading is wanted. Starting the API never starts this import. The currently queued background container is named `project7-plan-import`; watch it with `docker logs -f --tail 20 project7-plan-import`. After completed packages become available, click **Refresh plan packages**. A committed package can be explored while remaining packages load.

Plan endpoints: `GET /api/plans/packages`, `GET /api/plans/{packageId}/routes`, `GET /api/plans/{packageId}/trips?route_id=...`, and `GET /api/plans/{packageId}/trip?trip_id=...`. None require an active vehicle dataset. The API process does not require a plan-source mount; only the explicit importer does. PostgreSQL backups include plan tables automatically.

### Run the JSON fallback

Install Node 22 LTS (22.12 or newer). With nvm, run `nvm install` and `nvm use` in this directory. Run:

```sh
npm ci
npm run dev
```

Open the localhost URL printed by Vite. If the API is unavailable, place your team's prepared `replay.json` in `public/data/` and choose **Load local JSON fallback**, or explicitly choose **Explore synthetic demo**. Neither is substituted automatically for an empty database selection.

Internet is needed for map tiles and optional Google Fonts. System fonts are the fallback. When tiles fail, markers, filters and replay remain available on a plain background. Keep the OpenStreetMap attribution visible and do not bulk-download tiles.

## Prepare the shared extract

Only the data-preparation teammate needs Python 3.9+ with IANA timezone data. No third-party Python packages are required. Windows users whose Python cannot locate Europe/Lisbon can install `tzdata` with `python -m pip install tzdata`.

```sh
python3 scripts/prepare.py
```

Default source: the sibling `raw-data/datasets/TML/vehicles/eycs2/20260901/1.csv`. For a different location of that same source file:

```sh
python3 scripts/prepare.py --source /path/to/1.csv
```

The date/window is deliberately fixed: 1 September 2026, 07:00-09:00 Europe/Lisbon, including 120 seconds of prehistory. The source is streamed, not loaded in full. Known bus operator IDs are retained. Invalid coordinates, timestamps and empty vehicle identifiers are rejected and counted. Duplicate observations with the same operator, vehicle, event time, coordinates, trip and stop are collapsed, keeping the earliest receipt time. Empty windows fail without replacing an existing output.

Distribute `public/data/replay.json` privately to the team, preserving source access conditions. Source and prepared data are excluded from Git. Do not put data into another public asset directory or commit it with force-add. `npm run build` copies the local extract to ignored `dist/`; treat this output as containing transport data and do not publish it automatically.

## Replay behaviour

One marker per operator/vehicle pair, using the latest event at or before the selected timestamp. Reports fade when older than 60 seconds and disappear when older than 120 seconds. No interpolation. Play advances simulated time at 1x, 10x, 30x or 60x. Scrubbing pauses playback and supports backward movement. At the end, Play restarts the window.

Same-timestamp conflicting observations are ordered deterministically by receipt time, coordinates, trip and stop during preparation; the final one is selected. This is a display tie-break, not a resolution of the true physical position. Receipt timestamps are shown for context; replay is based on event time, not what a live receiver knew then.

The eycs2 partition is a geographic area associated with Rua Morais Soares, not solely that street. Vehicle trajectories can leave the extract. Trip/stop IDs have no timetable lookup in this milestone. The supplied GTFS plans declare 2025 dates, unlike the 2026 observations; no schedule inference is made.

## Shared interface

`src/replay.ts` defines `Dataset` and `Observation`. JSON schema version is 1. Envelope fields: `schemaVersion`, `metadata`, `observations`.

Metadata contains title, sourcePartition, operationalDate, timezone, startTimestamp/endTimestamp, historySeconds, synthetic, operator ID/name mapping, and preparation counts. Observation fields: timestamp, receivedTimestamp (Unix milliseconds); operatorId, vehicleId, tripId, stopId (strings); latitude, longitude (decimal degrees). Observations are sorted ascending by timestamp. Driver IDs and source event hashes are excluded. The frontend validates the loaded data and indexes by operator/vehicle for binary-search replay.

## Team workflow

Use this directory as the shared repository root. No remote is configured or publication performed by this scaffold. Create a private remote and commit the code and lockfile; keep data in your agreed private shared folder. Use short feature branches and agree on changes to `src/replay.ts` before changing the contract.

| Person | Responsibility |
| --- | --- |
| 1 | Preparation and data contract |
| 2 | Map and markers |
| 3 | Playback and state selection |
| 4 | Filters, inspector and error states |
| 5 | Integration and cross-device verification |

## Verification

```sh
npm test
python3 -m unittest discover -s scripts -p 'test_*.py'
npm run build
```

Tests cover future exclusion, backward scrubbing, staleness boundaries, operator scoping/filtering, Lisbon summer-time conversion, leading-zero IDs, deduplication, coordinate rejection and empty-output protection.

Second-device acceptance: clone, `npm ci`, copy the shared extract, `npm run dev`; check playback, backward scrub, filters and marker details. With the data file absent, verify the actionable message and synthetic demo. With the network unavailable, verify playback survives tile failures. This human second-device check cannot be certified on the original machine alone.

The JSON fallback needs no backend/database. The default selectable-data workflow uses the local API above. Verified route matching, Waze and a properly evaluated bunching definition remain later milestones.
