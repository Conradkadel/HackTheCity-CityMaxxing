# Verification status

Verified locally on 24 September 2026 after the unified-workspace overhaul.

## Automated checks

- Backend: 43 tests passed and 3 PostgreSQL-only tests skipped when `TEST_DATABASE_URL` was not supplied.
- Frontend: 16 Vitest tests passed across API encoding, replay, geohash, workspace state, full-day window positioning, and map-candidate detection.
- ESLint and Prettier checks passed.
- TypeScript compilation and the Vite production build passed.
- Python module compilation passed.

Run the same checks with:

```sh
npm run check
.venv/bin/pytest -q backend
```

The integration suite uses an isolated PostgreSQL schema when `TEST_DATABASE_URL` is set. It covers resumable/deduplicating vehicle imports, atomic plan imports, exact trip resolution, route metadata, incomplete import preview, limits, and legacy endpoints.

## Database checks

- The date-aware workspace catalog returned successfully for 1 September 2026.
- Catalog construction completed in approximately 0.4 seconds on the development database after indexing/query optimisation.
- CARRIS mappings verified include `755 → 118_0`, `12E → 77_0`, `15E → 76_0`, and `28E → 75_0`.
- Exact trip matching was verified with `6656_20260606_118_0_2`.
- Area 2 validity changes from plan `0277F` on 31 August to `JU98X` on 1 September.
- A reduced/partial catalog fixture keeps missing configured entries visible and unavailable instead of failing.
- The line-day endpoint for CARRIS `755` on 1 September returned in approximately 0.75 seconds with 13 vehicles, 109 observed vehicle–trip runs, 4,468 scheduled stops, and 3,232 matched reported-stop encounters.
- Migration `006_bunching_analysis.sql` applied successfully to the development database.
- A `stop-headway-v1` batch smoke test for CARRIS `755` on 1 September persisted 106 raw stop detections as 9 consolidated episodes: 7 multi-stop candidates and 2 retained single-point signals.
- The stored summary and episode APIs returned the completed run, exact parameters, per-line totals, episode locations, and supporting counts.
- A weekly batch for CARRIS `755` covering 31 August–6 September completed all seven days and stored 27 qualified multi-stop candidates. The daily qualified counts were 2, 7, 8, 5, 3, 2, and 0.
- The weekly endpoint returned every day explicitly, including Sunday as analyzed with zero qualified candidates, so missing analysis is distinguishable from an analyzed day with no result.

Timings describe this local database and machine; they are not performance guarantees. Run `backend/verify_dataset.py` after constructing or restoring another database.

## Browser smoke test

The local production data was exercised through the Vite/FastAPI stack:

- the workspace opened on CARRIS Lisbon;
- all 30 areas available on the selected date began enabled;
- the default configured CARRIS query loaded 46,978 matched observations and reported zero unresolved rows for that selection;
- the replay timeline and map boundaries rendered;
- the full-day control changed the 07:00–09:00 selection to a one-hour 07:30–08:30 zoom, marked it pending, and loaded 24,336 observations after Apply; the lower replay range updated to the applied hour;
- Routes showed configured groups and the complete date-valid catalog;
- Vehicles showed configured/all modes, carriers, configured lines, and loaded counts;
- route overlays remained independent from the loaded vehicle selection;
- the Details implementation retains a selected vehicle's last loaded report when it is no longer visible.
- opening **Day** for line `755` rendered a large direction-aware time–space modal;
- the default 07:00–09:00 view showed nine direction-0 runs, while the whole-day direction-0 view showed 54 runs;
- selecting a reported-stop marker displayed the exact vehicle, trip, route, planned span, observed span, and report count;
- whole-day candidate rows showed both observed and planned gaps and retained the stop-evidence warning.
- at the default 07:00 replay position, the map detected one schedule-and-distance-qualified candidate pair, drew the red vehicle halo/connector overlay, and exposed a working Hide/Show control.
- opening **Week** for line `755` rendered the Monday–Sunday history with 7/7 analyzed days, 27 multi-stop candidates, exact time ranges, vehicles, stops, observed gaps, and planned separation;
- days without a completed batch were shown as **Not analyzed**, while the analyzed Sunday with no qualified events was shown as **Analysis completed: no multi-stop candidates found**.
- the Routes tab weekly overview ranked the top eight lines and displayed candidate totals plus analyzed-day coverage for every configured CARRIS line; line `742` led the smoke-test week with 259 candidates across 7/7 days, while line `755` showed 27 across 7/7.

The initial full response is intentionally substantial. Smaller area/time/line selections load faster, and the API returns an actionable error rather than silently truncating above 200,000 observations.

## Deferred work

Operational detection, alerting, and calibration against confirmed arrival/departure events remain deferred. The current convergence rule produces investigation candidates and deliberately does not label them confirmed bunching incidents.

The precomputed detector does not interpolate positions. Its multi-stop requirement improves persistence evidence but does not remove the source `stop_id` timing limitation.

## Portable CARRIS database

- The source development database measured approximately 51 GB.
- The verified `all-carris` subset contains 4,874,153 `IA9T6` observations, 174 routes, 165,820 trips, and 4,654,086 normalised scheduled-stop rows.
- Every exported `driver_id` is `redacted`; `event_sources` contains zero rows.
- Only the CARRIS plan `20260715_IA9T6_CARRIS_82YP2` is included.
- The temporary subset database measured 4.25 GB; the final PostgreSQL custom-format archive measured 564 MiB (approximately 576 MB decimal).
- Its SHA-256 checksum passed, and a clean restore into an isolated temporary database completed successfully.
- The archive and checksum are published in the private `database-v1` GitHub release; the generated local files remain ignored by Git.
