# Verification status

## Partial-import preview follow-up

- All 21 backend tests passed against PostgreSQL, including reads during an uncommitted writer transaction, completed-only normal mode, preview progress, explicit version selection, empty windows and transition to ready.
- All 8 frontend tests passed, including preview query/version encoding and cancellation. TypeScript/Vite build passed.
- Only the API was recreated for deployment. Neither PostgreSQL nor either importer was restarted.
- Live browser verification succeeded: preview availability showed 96 committed files / 7,601,794 observations at refresh; eyc7w on 1 September 07:00–09:00 loaded real database observations with the incomplete-data banner. Play/pause advanced the replay and vehicle counts changed. These are intermediate counts, not final totals.

## Operation-plan feature follow-up

- All 20 backend tests passed in Docker/PostgreSQL, including plan import idempotency, atomic rollback, package-scoped endpoints, preserved leading-zero IDs, numeric geometry/stop order, missing stop details and service-day times after 24:00.
- The first combined test run encountered the real vehicle import's mutex; test importers now use a separate test-only mutex. Production locking and the running vehicle importer were not changed.
- Seven existing frontend tests and TypeScript/Vite build passed with the new plan viewer.
- All 46 supplied TXT headers checked against the required visualization fields with no missing headers.
- Browser verified: switching to operation-plan mode, reference-date warnings, selectors and the explicit not-yet-imported state.
- The real plan import is queued in `project7-plan-import`, waiting for the vehicle import lock. Real-package totals and populated-map browser verification are pending its completion. No successful full plan import is claimed yet.

## Completed locally

- Source inventory: 169 CSV paths found; raw sources were not modified.
- Frontend: 7 tests passed (deterministic replay, expiry, filtering, empty data and request cancellation).
- Backend without PostgreSQL: 16 tests passed (validation, identifier preservation, deduplication keys, Lisbon/DST/midnight windows, HTTP contract, prehistory query bounds, empty responses and limit/parameter errors).
- Follow-up with Docker installed: all 17 backend tests passed against PostgreSQL, including the isolated integration fixture (COPY, deduplication, rollback, resume and repeated imports).
- Compose clean start succeeded; PostgreSQL and API are healthy. The frontend `/api/health` proxy responds successfully.
- Full 169-file import started in background container `project7-vehicle-import`. First file committed 43,046 observations from 44,558 rows, collapsing 1,512 duplicates with no rejected rows. These are first-file counts, not final totals.
- Original preparation workflow: 1 unittest passed.
- TypeScript check and Vite production build passed.
- Browser: unavailable API gives an actionable message; explicitly selected synthetic demo is labelled and plays; local JSON fallback loads, operator filtering changes counts, and clicking a marker shows IDs, geographic cell, report age and event/receipt timestamps.
- `.env`, virtual environment and prepared JSON are ignored by Git. Database files, dumps and non-fixture CSVs are excluded.

## Not yet verified

Docker is now installed and the full import is in progress. The active dataset remains unset until the entire import succeeds. Remaining checks:

- Actual import totals/rejections/timings are unknown.
- Real API-backed selector changes and browser cancellation/loading/error flows require the running API and imported data. Cancellation logic itself passed unit tests.
- The default database selection has not been compared with `public/data/replay.json`.
- Query plans and response times have not been measured.
- Second-device setup must be checked by a teammate.

The README gives commands for all these checks. `backend/verify_dataset.py` produces measured totals, plans, timings and an optional extract comparison. No unmeasured database performance is claimed.
