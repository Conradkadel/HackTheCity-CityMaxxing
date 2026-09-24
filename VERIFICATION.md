# Verification status

Verified locally on 24 September 2026 after the unified-workspace overhaul.

## Automated checks

- Backend: 27 tests passed and 3 PostgreSQL-only tests skipped when `TEST_DATABASE_URL` was not supplied.
- Frontend: 12 Vitest tests passed across API encoding, replay, geohash, and workspace state.
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

Timings describe this local database and machine; they are not performance guarantees. Run `backend/verify_dataset.py` after constructing or restoring another database.

## Browser smoke test

The local production data was exercised through the Vite/FastAPI stack:

- the workspace opened on CARRIS Lisbon;
- all 30 areas available on the selected date began enabled;
- the default configured CARRIS query loaded 46,978 matched observations and reported zero unresolved rows for that selection;
- the replay timeline and map boundaries rendered;
- Routes showed configured groups and the complete date-valid catalog;
- Vehicles showed configured/all modes, carriers, configured lines, and loaded counts;
- route overlays remained independent from the loaded vehicle selection;
- the Details implementation retains a selected vehicle's last loaded report when it is no longer visible.

The initial full response is intentionally substantial. Smaller area/time/line selections load faster, and the API returns an actionable error rather than silently truncating above 200,000 observations.

## Deferred work

Detection/alerting logic for bus bunching and creation/upload of a reduced CARRIS-only database are not part of this phase.
