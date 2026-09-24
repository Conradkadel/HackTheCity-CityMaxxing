# Implemented features and developer handoff

This document is the single high-level handoff for the current Project 7 prototype. It explains what has been implemented, how the pieces fit together, which identifiers are authoritative, and where the important limitations are. Use the linked specialist documents when changing the database or analysis rules.

## 1. Current product scope

The repository contains a phase-one data exploration workspace for TML Challenge 7. It combines:

- recorded vehicle observations from the TML vehicle CSV exports;
- date-valid GTFS-like operation plans;
- exact trip-to-route and trip-to-timetable resolution;
- a replay map for inspecting vehicle movement;
- planned route overlays and stop markers;
- individual vehicle and public-line analysis;
- rule-based **possible bunching candidates** on the line chart and map;
- versioned precomputed multi-stop candidate episodes for statistics;
- a reproducible PostgreSQL import/export workflow, including a smaller privacy-safe CARRIS database for collaborators.

The application is an investigative visualization, not a production control system. Its bunching output is evidence for review, not a confirmed operational incident or alert.

## 2. Technology and runtime layout

| Layer | Implementation |
| --- | --- |
| Frontend | React 19, TypeScript, Vite, Leaflet, plain CSS |
| API | FastAPI with psycopg |
| Database | PostgreSQL 17 |
| Local services | Docker Compose |
| Tests | Vitest for frontend logic; pytest for backend and optional PostgreSQL integration tests |

The browser talks to Vite at `127.0.0.1:5173`. Vite proxies `/api` requests to FastAPI at `127.0.0.1:8000`. FastAPI reads PostgreSQL through the Compose network.

Important entry points:

- `src/UnifiedWorkspace.tsx`: the unified user interface and Leaflet orchestration;
- `src/LineAnalysisModal.tsx`: the large public-line time–space analysis;
- `src/workspaceState.ts`: default filters and draft/applied comparison;
- `src/replay.ts`: response validation, vehicle indexing, and replay snapshots;
- `src/bunching.ts`: current-map bunching candidate detection;
- `backend/app.py`: application startup, health/availability, and observation endpoint;
- `backend/workspace_api.py`: date-aware workspace catalog;
- `backend/observation_query.py`: vehicle query and date-valid route resolution;
- `backend/line_day.py`: public-line schedule comparison and convergence candidates;
- `backend/analyze_bunching.py`: reproducible batch analysis and episode persistence;
- `backend/bunching_results_api.py`: stored episode/statistics endpoints;
- `backend/vehicle_day.py`: whole-day vehicle summary;
- `backend/plans_api.py`: route catalog and batched geometry;
- `backend/config/analysis_presets.json`: Challenge 7 preset data and plan validity metadata.

## 3. Unified map workspace

The earlier duplicated viewers were replaced with one workspace that has a shared Leaflet map and three sidebar tabs: **Routes**, **Vehicles**, and **Details**.

### Date, time window, and loading

- The selected operational date and a complete 00:00–24:00 day overview remain visible above the tabs.
- A highlighted analysis window moves across the day in 15-minute increments; 30-minute, 1-hour, 2-hour, and 4-hour zoom presets change its width.
- Window changes remain pending until **Apply** is pressed. The lower replay slider then provides precise playback inside the loaded window.
- Times are interpreted in `Europe/Lisbon`.
- Windows may cross midnight but must be nonempty and no longer than four hours.
- Ambiguous or nonexistent Lisbon times around daylight-saving transitions are rejected with an actionable error.
- Changing a date reloads the database-derived catalog for that day.
- Vehicle filter changes are held as a draft until **Apply filters** is pressed.
- Route overlay changes load independently and never cause a vehicle-history query.
- The API includes 120 seconds of observation prehistory so vehicles are already visible at the beginning of the requested window.
- Requests above 200,000 observations are rejected rather than silently truncated.

### Replay behavior

- Observations are grouped by operator and vehicle ID.
- For each replay timestamp, the map shows the most recent report at or before that time.
- A vehicle remains visible for up to 120 seconds after its report.
- Reports older than 60 seconds are styled as stale.
- Replay supports play/pause, a loaded-window time slider, and selectable playback speed.
- The map status reports loaded/visible counts and matched/unmatched route coverage.
- Clicking a marker selects that report and opens the Details tab.

### Map and basemap resilience

- Vehicle observations are rendered as Leaflet markers and retain operator-specific colors.
- Planned route shapes, stops, area boundaries, reference zones, and bunching overlays use separate layers.
- A tile-loading warning is shown if the external basemap is unavailable; data overlays remain usable.
- The layout includes responsive behavior for narrower displays.

## 4. Map-owned area selection

Area filtering was removed from the sidebar and moved into a Leaflet-style control on the map.

- The control lists every five-character geohash area that has vehicle coverage on the selected date.
- Every available area is enabled by default, including when CARRIS is the default preset.
- **Select all** and **Clear** actions are available.
- Draft area changes do not alter loaded observations until **Apply filters** is pressed.
- Enabled, disabled, and pending areas use distinct boundary styles.
- Disabled boundaries remain visible, helping explain why a vehicle can disappear when crossing a cell edge.
- Apply is disabled when no area or no operator is selected, and the interface explains the requirement.
- Six-character Challenge 7 cells can be displayed as optional reference zones; they are not an invisible default data restriction.

For an explicit preset query that uses six-character geohashes, the backend first narrows to the five-character parent cell and then applies the precise decoded latitude/longitude bounds.

## 5. Routes tab and planned network overlays

The Routes tab displays only route variants from operation-plan packages valid on the selected date.

### Configured groups

- Challenge 7 groups are shown before the complete catalog.
- CARRIS Lisbon is the default and is marked as important.
- A complete configured group, one public line, or an individual route variant can be selected.
- One public line may resolve to multiple package-scoped internal route variants.
- Configured lines missing from the current database or date stay visible but are disabled and labelled unavailable.
- Per-preset plan and vehicle-coverage warnings explain partial data.

### Complete catalog

- All imported, date-valid route variants are grouped by operator.
- The catalog is searchable by public line, route name, operator, or internal route identifier.
- The viewer is not limited to the Challenge 7 presets.
- Route keys use the runtime form `<package_id>:<route_id>` so variants remain unambiguous inside the current database.
- These keys are API/UI values only; numeric package IDs are never stored in configuration.

### Geometry and stops

- Selected geometry is fetched separately in one batched request.
- All available shapes and directions for a selected route variant are drawn.
- Excessively large shape arrays are lightly downsampled for transport.
- If a route lacks a shape but has stop coordinates, the API constructs a fallback line from representative stops.
- Optional stop markers use the longest scheduled trip per direction as a representative stop sequence.
- The map can fit the bounds of loaded route geometry.
- Route selection does not modify the vehicle filter.

## 6. Vehicles tab and observation filters

The Vehicles tab controls recorded movement independently of route overlays.

- It lists carriers with vehicle observations on the selected date.
- Configured but unavailable operators remain visible and disabled.
- The default is the CARRIS Lisbon operator with all configured lines that have both plan and vehicle coverage.
- **Configured lines** mode restricts results to exact date-valid trip matches for the selected public lines.
- **All vehicles** mode includes matched routes, non-configured routes, and unresolved trip IDs for the selected operators and areas.
- Configured-line choices are preserved while temporarily switching to All vehicles.
- Configured lines are grouped by preset and show bus/tram mode where known.
- Filters for operators, lines, areas, date, and time only take effect together through the prominent Apply action.
- Loaded metadata reports total observations, window observations, focus/context counts, and matched/unmatched counts.

The API still accepts the older `preset_id`, `focus_line`, `include_context`, `schedule_mode`, `route_id`, and `direction_id` parameters for compatibility. New UI code uses repeated `area`, `operator`, and optional `line` parameters.

## 7. Vehicle Details tab

Selecting a marker automatically opens a detailed inspector.

### Selected report

The inspector shows the non-sensitive fields associated with the selected observation:

- operator and vehicle ID;
- public line and mode when resolved;
- internal route, route name, direction, and package ID;
- exact trip ID;
- reported stop ID;
- scheduled stop sequence/time and schedule difference when matched;
- route match status and focus/context status;
- latitude, longitude, geohash, report time, receipt time, and replay age.

Driver IDs are never returned by the API and never shown in the UI.

If the selected vehicle becomes stale, crosses a disabled area, or otherwise disappears from the current replay snapshot, the last loaded report remains in Details with a clear **No longer visible at this replay time** status.

### Whole operational day summary

The Details tab also requests all observations for that vehicle and operational date, independently of the current map areas and time window. It presents:

- first and last report;
- total and unresolved observation counts;
- all observed areas;
- public lines served, internal route variants, trips, and observation totals;
- chronological line/trip periods;
- gaps longer than 120 seconds, including area or line changes;
- reported-stop evidence with planned times and differences where exact schedule matching is possible.

This view makes it possible to distinguish a vehicle leaving the current filter from it disappearing from the source data.

## 8. Exact route and schedule resolution

No public line, internal route, or intended timetable is inferred from the coordinates. Resolution uses the source identifiers:

1. Choose a `plan_packages` row whose `event_agency_id` matches the vehicle event and whose inclusive validity range contains `operational_date`.
2. Match `vehicle_events.trip_id` exactly to `schedule_trips.trip_id` inside that package.
3. Join the package-scoped `route_id` to `schedule_routes` to obtain public line, route name, and direction.
4. Optionally match the reported `stop_id` to `schedule_stop_visits` for scheduled-stop information.

A stop match is not required to resolve a route. If the exact trip does not match, the observation remains available in All vehicles mode with `routeMatchStatus: "unmatched"`.

Known verification examples for the current CARRIS package are:

- `755` → route variant `118_0`;
- `12E` → `77_0`;
- `15E` → `76_0`;
- `28E` → `75_0`;
- trip `6656_20260606_118_0_2` → route `118_0` → public line `755`.

These are validation facts, not hardcoded mappings. A new operation plan may change internal route and trip IDs while retaining the same public line.

GTFS times are kept as strings because service-day values may exceed `24:00:00`. Schedule comparisons use a Lisbon service day beginning at 04:00 so after-midnight service is attached to the intended operational day.

## 9. Public-line analysis modal

Every date-valid public line in the Routes tab has an **Analyze** action. It opens a large modal because the visualization is too dense for the sidebar.

### Line-day data

- The backend finds observed vehicle–trip pairs for the selected operator, line, and operational date.
- Only exact trip matches are included; theoretical trips that have no vehicle observations are not drawn.
- One physical vehicle may produce several run rows when it operates several trips.
- The complete ordered planned stop schedule is loaded for each observed trip.
- Reported stop identifiers are associated with their matching planned stop; repeated stop IDs are disambiguated using the closest scheduled time.
- Unmatched stop identifiers are counted and surfaced as warnings rather than discarded silently.
- Responses are capped at 500 matched runs and 50,000 stop-report groups.

### Time–space chart

- Stops run horizontally and Lisbon service time runs vertically.
- Dashed paths show the planned stop schedule.
- Solid paths and points show reported-stop evidence.
- Runs for the same physical vehicle share a color.
- Direction 0 and direction 1 are separated.
- The user can inspect either the current workspace time window or the whole service day.
- Selecting a run or reported point shows vehicle, trip, route, planned span, observed span, report count, and schedule coverage.
- Coverage metrics summarize vehicles, runs, scheduled stops, matched reported stops, and unmatched reported stop IDs.
- A separate **Week** action beside each route opens its precomputed Monday–Sunday history. Each day lists episode time ranges, vehicles, first/last affected stops, evidence count, and headway gaps; missing analysis is visually distinct from an analyzed zero-candidate day.
- The Routes tab loads one aggregate weekly summary, ranks the eight lines with the most multi-stop candidates, and shows candidate/day-coverage badges beside every configured line and catalog route.
- Weekly rankings are labelled as raw candidate totals rather than probabilities because they are not normalized for service frequency.

### Line-chart convergence candidates

A possible candidate is produced when two different matched trips report the same scheduled stop:

- no more than 180 seconds apart in observed report time; and
- at least 300 seconds apart in the timetable.

Candidates are marked on the chart and listed with vehicle IDs, trip IDs, route, direction, stop, observed gap, planned gap, and report times.

## 10. Replay-map bunching candidates

The replay map applies a stricter real-time-style rule to vehicles visible at the current replay time. Two different vehicles qualify only when all of these are true:

- same operator;
- same public line;
- same internal route variant;
- same direction;
- same nonempty reported stop ID with a matched scheduled stop;
- report timestamps no more than 180 seconds apart;
- planned stop times at least 300 seconds apart;
- current reported coordinates no more than 300 metres apart.

The geographic distance is calculated with the Haversine formula. Qualified vehicles receive red halos and a dashed red connector. The midpoint tooltip shows the line, vehicle IDs, observed gap, planned gap, and distance. The map displays the number of current candidate pairs, and the overlay can be shown or hidden without changing filters. Candidates recompute as replay time moves.

This is deliberately called a **possible bunching pair**. The source metadata does not prove that `created_at` is a door-open arrival time or that `stop_id` means the vehicle physically stopped there.

## 11. Precomputed bunching episodes and statistics

The batch analyzer turns repeated line-day detections into persistent, versioned results without replacing the live replay overlay.

- Every execution records the active dataset, date, operator, detector version, parameters, status, timing, and counts.
- Raw detections for the same unordered vehicle-trip pair, route, and direction are grouped when evidence points are at most 20 minutes apart.
- Two or more distinct affected stops produce a `multi_stop_candidate` episode.
- A one-stop signal is retained as `single_point` evidence for auditing but is excluded from normal candidate totals.
- Evidence rows retain both reported and scheduled times, both vehicles/trips, the stop, gaps, and scheduled-stop coordinates.
- New runs are appended; they never overwrite an earlier detector version or threshold set.
- Summary, episode-list, and episode-evidence APIs read the latest completed matching run.

The current `stop-headway-v1` detector explicitly records `usesPositionInterpolation: false`. See [PRECOMPUTED_BUNCHING.md](PRECOMPUTED_BUNCHING.md) for commands, API examples, schema relationships, and interpretation rules.

## 12. Challenge 7 configuration

`backend/config/analysis_presets.json` is the only hardcoded Challenge 7 selection definition. It contains stable values only:

- preset ID and display name;
- event-facing agency IDs;
- public line codes;
- line mode overrides such as CARRIS trams;
- display color;
- named brief-supplied geohashes;
- stable operation-plan source name, TML plan ID, normalized ID, and validity dates.

It does not contain local package IDs or individual trip IDs.

Configured presets are:

- CARRIS Lisbon;
- Mira-Sintra / Agualva-Cacém;
- Caneças / Pontinha;
- Estrada Nacional 10;
- Sesimbra / Quinta do Conde;
- MobiCascais.

CARRIS Lisbon is the default. CARRIS `12E`, `15E`, and `28E` are marked as trams; its other configured focus lines are buses.

Configuration validation runs before use and checks version, unique IDs, known operators, nonempty unique lines, line-mode references, valid five/six-character geohashes, valid plan date ranges, and non-overlapping validity windows for each operator.

## 13. Date-aware plan handling

Operation plans are registered with the event agency and an inclusive validity interval. This solves the previous problem of treating one package as permanently valid for an operator.

The configured 2026 packages are:

| Operator | TML plan | Validity |
| --- | --- | --- |
| CARRIS `IA9T6` | `82YP2` | 15 July–31 December |
| Area 1 `LA77N` | `XS3H8` | 3 August–13 September |
| Area 2 `BNA17` | `0277F` | 3–31 August |
| Area 2 `BNA17` | `JU98X` | 1–13 September |
| Area 3 `YA15B` | `2QDAD` | 3 August–13 September |
| Area 4 `A2L1N` | `F1M13` | 1 August–13 September |
| MobiCascais `HF16N` | `SBF83` | 8 June–13 September |

For example, Area 2 resolves to `0277F` on 31 August and `JU98X` on 1 September. Missing date-valid plans produce empty/partial states and warnings, never a guessed fallback package.

## 14. Database construction and import features

### Vehicle importer

- Recursively discovers source CSV files.
- Requires and validates the documented source columns.
- Checks identifiers, timestamps, dates, finite coordinates, and five-character geohashes.
- Computes per-file SHA-256 checksums and a full inventory hash.
- Creates deterministic observation keys from the operational identity of an event.
- Deduplicates repeated observations while retaining source provenance.
- Commits source files independently so interrupted imports can resume.
- Tracks invalid-row reasons and file-level import counters.
- Builds a new dataset version without disrupting the active one.
- Switches `active_dataset` only after a complete successful import.
- Skips an unchanged source inventory; changed data requires the explicit `--rebuild` path.
- Precomputes `availability` by date, area, and operator for fast catalog construction.
- Supports an explicit incomplete-import preview without exposing it as the normal active dataset.

### Operation-plan importer

- Discovers each direct plan-package directory.
- Requires agency, feed, routes, trips, stops, shapes, and stop-times source tables.
- Validates identifiers, coordinates, and sequence fields.
- Fingerprints all source text files and skips unchanged packages.
- Stores source rows losslessly as JSONB, preserving strings and additional columns.
- Builds normalized route, trip, and scheduled-stop lookup tables.
- Adds event-agency and validity metadata from stable configuration.
- Rolls back a complete package if validation fails or inputs change mid-import.
- Preserves additional GTFS tables automatically.

### Migrations and lifecycle

- Numbered SQL migrations run in order at API startup.
- Migration execution is transactional and guarded by a PostgreSQL advisory lock.
- Migrations are idempotent.
- The active ready dataset remains available while another version imports.
- Query indexes cover area/time, operator/time, vehicle/time, trip resolution, plan validity, routes, trips, stops, and shapes.

The full schema and every column are documented in [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md).

## 15. API inventory

### Main workspace endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /api/health` | Service and active-dataset health |
| `GET /api/workspace-catalog?date=YYYY-MM-DD` | Date-aware areas, operators, routes, presets, coverage flags, warnings, and limits |
| `GET /api/observations` | Filtered replay observations with route/schedule metadata and coverage counts |
| `POST /api/plans/routes-geometry` | Batched route shapes and representative stops for package-scoped keys |
| `GET /api/vehicles/{operator}/{vehicle}/day?date=...` | Whole-day history and summary for one vehicle |
| `GET /api/lines/{operator}/{line}/day?date=...` | Observed runs, exact schedules, and line convergence candidates |
| `GET /api/bunching/summary?date=...` | Latest completed pre-analysis totals by operator and line |
| `GET /api/bunching/episodes?date=...&operator=...` | Stored multi-stop episodes, optionally including single-point evidence |
| `GET /api/bunching/episodes/{id}/evidence` | Full stop-level evidence for a stored episode |
| `GET /api/bunching/week?date=...&operator=...&line=...` | Seven-day route history with analysis-coverage states and episode times |
| `GET /api/bunching/week-summary?date=...[&operator=...]` | Compact per-line weekly candidate totals and analyzed-day coverage |

### Additional and compatibility endpoints

- `GET /api/availability` returns broad coverage and supports incomplete-import preview.
- `GET /api/analysis-presets` resolves configured presets against date-valid plans.
- `GET /api/plans/routes-catalog` and `/api/plans/catalog` expose route catalogs, optionally by date.
- `GET /api/plans/routes-geometry` is the query-string geometry equivalent.
- Package/route/trip endpoints under `/api/plans` remain for backward compatibility.
- Existing schedule endpoints remain available through `backend/schedule.py`.

Read transactions use repeatable-read semantics where a consistent multi-query view matters. Expensive workspace reads set a 30-second statement timeout. Database exceptions are converted into a user-facing 503 response rather than exposing internals.

## 16. Partial and reduced database support

The interface derives available dates, areas, operators, routes, and line coverage from the active database. Therefore:

- missing configured operators and lines remain visible but disabled;
- missing plan packages, shapes, stops, observations, or route variants become warnings or empty states;
- unresolved observations remain usable in All vehicles mode;
- a CARRIS-only database does not require frontend or preset changes;
- route overlays can remain empty while vehicle replay still works, and vice versa.

The default portable `all-carris` database includes every CARRIS observation and route in the active dataset, the relevant CARRIS plan, shapes, stops, trips, and normalized stop visits. It excludes unrelated operators, sensitive provenance, and duplicate raw stop-time JSON.

## 17. Privacy and sharing features

- Driver IDs are never part of an API response or frontend type.
- The full internal database retains provenance for auditing and must be treated as sensitive.
- The portable CARRIS exporter replaces every retained driver ID with `redacted`.
- It omits `event_sources`, unrelated operators/plans, import-file history, and raw duplicated stop-time JSON.
- It rebuilds availability for the reduced content.
- Export modes are `all-carris`, `configured-lines`, and `challenge-areas`.
- Dumps are PostgreSQL custom-format archives with a SHA-256 checksum.
- Generated exports and local environment files are ignored by Git.
- Restore requires an explicit `--replace` because it replaces the local Compose `headway` database.
- The verified redacted archive is distributed through the private GitHub `database-v1` release instead of Git history.
- The download helper uses authenticated GitHub CLI access and verifies the checksum before restore.

See [SHARING_DATABASE.md](SHARING_DATABASE.md) for the exact commands and current archive details.

## 18. Data-quality and interpretation safeguards

- Exact trip matching is required; there is no fuzzy route assignment.
- Route resolution does not depend on a matching stop.
- Unresolved trips and unmatched stops are counted and reported.
- Public line codes are stable configuration identifiers; route IDs, trip IDs, and package IDs are treated as plan-derived values.
- Missing data is not interpreted as a skipped stop or absent service.
- `stop_id` and report time are labelled as reported-stop evidence, not confirmed arrival/departure events.
- Candidate convergence is not labelled confirmed bunching.
- Coordinate proximity is required for the replay-map candidate rule but not for the service-day chart rule.
- No driver data is exposed.
- The API refuses oversized requests rather than returning an incomplete sample without warning.

## 19. Automated verification and developer tooling

Frontend checks available through `npm run check`:

- ESLint;
- Prettier validation;
- Vitest unit tests;
- TypeScript compilation;
- Vite production build.

Frontend tests cover query construction, response validation, replay snapshots, geohash behavior, filter defaults/state, and map bunching qualification/rejection rules.

Backend pytest coverage includes configuration validation, domain/time handling, catalogs, observations, exact route matching, line-day analysis, vehicle-day summaries, export behavior, partial databases, limits, and legacy endpoints. Optional PostgreSQL integration tests use an isolated temporary schema and cover resumable imports, deduplication, atomic plan import, indexes/query behavior, and incomplete-import preview.

`backend/verify_dataset.py` provides production-data totals, representative endpoint checks, and PostgreSQL `EXPLAIN (ANALYZE, BUFFERS)` output. [VERIFICATION.md](../VERIFICATION.md) records the last completed automated and browser smoke checks.

## 20. Deliberately deferred work

The following have not been implemented and should not be assumed:

- confirmed arrival/departure event extraction;
- map matching or interpolation along route shapes;
- statistical or machine-learning bunching classification;
- persistent incidents, alerting, notifications, or an operator workflow;
- calibration of thresholds against ground truth;
- automatic diagnosis of the cause of a headway collapse;
- database hosting as a public service;
- a production authentication/authorization layer;
- automated deployment beyond the local Compose/Vite workflow.

A sensible next detection phase would validate stop semantics, track along-route progress, require repeated downstream convergence, calibrate per-line thresholds, and distinguish terminal layovers, diversions, missing reports, and genuine headway collapse.

## 21. Where to read next

- [README](../README.md): setup, quick start, and normal development commands.
- [PROJECT_7_SELECTION.md](PROJECT_7_SELECTION.md): authoritative operators, public lines, areas, plan dates, and query parameters.
- [DATABASE_CONSTRUCTION.md](DATABASE_CONSTRUCTION.md): repeatable raw-data import and route resolution.
- [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md): tables, columns, keys, relationships, and portable-database differences.
- [LINE_ANALYSIS.md](LINE_ANALYSIS.md): chart semantics, candidate rules, and evidence limitations.
- [PRECOMPUTED_BUNCHING.md](PRECOMPUTED_BUNCHING.md): versioned episode generation, evidence, and stored statistics.
- [SHARING_DATABASE.md](SHARING_DATABASE.md): reduced/full database export and restore.
- [VERIFICATION.md](../VERIFICATION.md): last verified tests, database checks, and browser smoke test.

When changing matching logic or configured selections, update this handoff and the relevant specialist document in the same commit. Keep Challenge 7 business selections in `analysis_presets.json`; do not introduce package IDs or trip IDs into frontend constants.
