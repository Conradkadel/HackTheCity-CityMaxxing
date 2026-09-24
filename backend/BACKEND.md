# Backend – Bus Bunching Early-Warning (FastAPI + Postgres)

> Owner: backend team (C). Stack: **FastAPI + Pydantic + PostgreSQL (psycopg 3)**. Frontend: React (Vite) on `localhost:5173`.
> The API reads the **team database** tables directly (`tb_gps_filtrado`, `tb_bunching_events`, `gtfs_*`).
> No database yet? `python -m backend.mock_data` fills a local Postgres with fake rows in the same tables.

---

## 0. Run it (from the `code/` folder)
```bash
pip install -r backend/requirements.txt
docker compose -f backend/docker-compose.yml up -d     # local Postgres on :5432 (or point DATABASE_URL at the team DB)
cp backend/.env.example backend/.env                   # adjust DATABASE_URL / MODEL_PATH

# pick ONE way to get data:
python -m backend.mock_data                            # fake data (refuses to run on a DB with real data)
python -m backend.duckdb_to_postgres ../hackthecity.db # copy the team DuckDB file into Postgres (+ indexes)
psql "$DATABASE_URL" -f backend/schema.sql             # DB already in Postgres? just add the indexes

uvicorn backend.main:app --reload --port 8000          # docs: http://localhost:8000/docs
pytest -q backend/test_api.py                          # smoke tests on mock data (local DB only)
```
Frontend types: `npx openapi-typescript http://localhost:8000/openapi.json -o src/types.ts`

---

## 1. Files
```
backend/
├── main.py                FastAPI app: CORS, GZip, error format, routes (thin: validate → service → schema)
├── schemas.py             Pydantic models = the contract with the frontend
├── services.py            one function per route (SQL on the team tables) + live model (from api_server.py)
├── schema.sql             the tables/columns the API uses + indexes (CREATE IF NOT EXISTS – safe on the real DB)
├── bunching_events.sql    tb_bunching_events build, copied from analysis/processar_filtros_backend.py (Postgres SQL)
├── mock_data.py           fake rows in the same tables (1 corridor, 2 lines, 10 stops, 1 h, 2 bunching episodes)
├── duckdb_to_postgres.py  one-off copy hackthecity.db (DuckDB) → Postgres, same table names/columns
├── test_api.py            TestClient smoke tests
├── requirements.txt · docker-compose.yml · .env.example
└── BACKEND.md             this file
```
Layer rule: **route** (HTTP, params, status codes) → **service** (SQL, no FastAPI imports) → **Postgres**.

### What came from `analysis/` (the originals stay there for now)
| analysis file | in backend | note |
|---|---|---|
| `api_server.py` | `GET /api/v1/buses/live` (main.py) + `services.get_live_buses` | same path, query, features, output. DuckDB → Postgres. Fixed: `dia_semana` now uses Sunday = 0 like the training query (pandas `dayofweek` is Monday = 0) |
| `processar_filtros_backend.py` step 4 | `bunching_events.sql` | same logic, Postgres syntax; used by `mock_data.py` |
| `processar_filtros_backend.py` step 3 | column list of `tb_gps_filtrado` in `schema.sql` | |
| `processar_dados.py`, `treinar_modelo_bunching.py`, `dataset_evidence.py` | – | data loading / ML / analysis, not API code → stay in `analysis/` (or move to `src/`) |

---

## 2. Database tables used (see `schema.sql`)
| table | used for | key columns |
|---|---|---|
| `tb_gps_filtrado` | replay, vehicle track, coverage, dates, live model | vehicle_id BIGINT, trip_id, stop_id (= NEXT stop, NULL = layover), latitude, longitude, operational_date BIGINT `20260901`, timestamp_criado TIMESTAMP (UTC), geohash_5, route_id, route_short_name |
| `tb_bunching_events` | events, alerts, KPIs, heatmap, hotspots, bus colours in replay | agency_id, linha, stop_id, vehicle_id (follower), vehicle_id_anterior (leader), timestamp_criado, headway_segundos, nivel_bunching `CRÍTICO` ≤ 90 s / `MODERADO` ≤ 180 s / `NORMAL` ≤ 300 s, latitude, longitude |
| `gtfs_routes`, `gtfs_trips`, `gtfs_shapes`, `gtfs_stops`, `gtfs_stop_times` | map (line shapes, stops, stop names) | all text, standard GTFS columns |
| `gps_pings`, `gtfs_calendar_dates`, `tb_calendario` | not used by the API | |

**Translation DB → API** (done in `services.py`):
`timestamp_criado` → `ts` (unix ms UTC) · `operational_date` 20260901 → `date` "2026-09-01" · `vehicle_id` BIGINT → string ·
`COALESCE(route_short_name, route_id)` / `linha` → `line_id` · `nivel_bunching` → `severity` (`critical`/`moderate`/`normal`) ·
`headway_segundos` → `headway_s` · `vehicle_id_anterior` → `leader_vehicle`.

**Corridors** are defined in `services.CORRIDORS` (lines + geohash squares, copied from `config.yaml` – keep in sync).
Pings belong to a corridor if `left(geohash_5,5)` is one of its squares **and** the line is a corridor line.
Bunching rows have no geohash → corridor = its bounding box + line.

---

## 3. Conventions
- Prefix **`/api/v1`**. JSON, snake_case, English names. GZip (min 1 KB). CORS from `CORS_ORIGINS`.
- Time: `ts` = unix **ms UTC**; `date` = operational date `YYYY-MM-DD` (day runs 05:00–04:59 Lisbon, hours 5..28).
- Errors: `{"error": {"code": "not_found" | "invalid_param" | "no_data" | "unavailable", "message": "...", "details": {...}}}` → 404 / 422 / 503.
- Lists: `limit` (default 100, max 1000) + `offset` → `{items, total, limit, offset}`.
- Caching: `get_meta()` (dates) and `get_network()` are `@lru_cache`d → restart the API after reloading the DB.

---

## 4. Endpoints
### System
| | |
|---|---|
| `GET /health` | `{status:"ok"}` (DB reachable) |
| `GET /meta` | `{dates:[...], thresholds:{critical_s:90, moderate_s:180, max_s:300}}` – load once on start |

### Network & coverage
| | |
|---|---|
| `GET /corridors` | `[{corridor_id, name, lines, zones, bbox, dates_available}]` |
| `GET /corridors/{id}` | corridor + `summary` (KPI row for the whole week) |
| `GET /network/{id}?include=lines,stops,zones&line_id=` | GeoJSON: GTFS shapes (`kind:"line"`, line_id, direction, color), stops (`kind:"stop"`, stop_id, name), geohash squares (`kind:"zone"`) |
| `GET /coverage/{id}?date=` | `[{geohash, covered, hours_covered:[5..28]}]` – grey out squares with no data |

### Replay (main demo)
**`GET /replay?corridor&date&from_ts&to_ts&line_id(csv)&format=trips|frames`** – window ≤ `MAX_REPLAY_MINUTES` (30) else 422.
```json
{"corridor":"mira_sintra","from_ts":1788285600000,"to_ts":1788287400000,
 "vehicles":[{"vehicle_id":"41501","line_id":"1715","trip_id":"1715_0_1_0",
   "path":[[-9.28,38.77],...],"timestamps":[1788285600000,...],
   "headway_status":["ok","bunched",...],"status":["moving","layover",...]}],
 "frames":[],
 "coverage":{"missing_zones":["eyckt"]}}
```
One entry per GPS ping (not a fixed 10 s grid). `headway_status` = latest `tb_bunching_events` row of that bus at its current stop (≤ 10 min old): CRÍTICO → `bunched`, MODERADO → `at_risk`, otherwise `ok`. `status` = `layover` when `stop_id` is NULL.

**`GET /vehicles/{vehicle_id}/track?date&from_ts&to_ts`** → the bus's pings + bunching rows where it is follower or leader.

**`GET /alerts?corridor&date&ts&window_s=60&min_severity=moderate|critical`** → bunching rows in `[ts − window_s, ts]` + `action:{type:"hold", vehicle_id, stop_id, seconds}` (hold the follower until the gap reaches 180 s, max 120 s).

### Analysis (`tb_bunching_events`)
| | |
|---|---|
| `GET /events?corridor&date&line_id&severity&stop_id&from_ts&to_ts&limit&offset` | paged `{event_id, ts, agency_id, line_id, stop_id, follower_vehicle, leader_vehicle, headway_s, severity, lat, lon}` |
| `GET /kpis?corridor&date&line_id&group_by=none\|hour\|line\|stop\|date\|day_type` | `[{group, n_events, n_critical, n_moderate, mean_headway_s, min_headway_s}]` |
| `GET /heatmap?corridor&metric=n_critical\|n_events\|n_moderate\|mean_headway_s&date&line_id&top_stops=30` | `{stops:[{stop_id,name}], hours:[5..28], values:[[...]]}` (`null` = no row) |
| `GET /hotspots?corridor&date&top=10` | stops ranked by critical rows, with name, lat/lon and counts |

### Live model (from `analysis/api_server.py`)
**`GET /buses/live?linha=1715`** → `{status, count, data:[{vehicle_id, linha, agency_id, latitude, longitude, last_ping, prediction:{are_we_close_to_bunching, risk_level, bunching_probability}}]}`. Needs `MODEL_PATH` (`modelo_bunching.pkl`), else 503.

---

## 5. Know the limits of the current tables (see `DATASET_DESIGN.md` §1/§5)
- `tb_bunching_events` is **ping level**: one real episode = many rows (≈ 12×), and it only compares buses of the **same line** – bunching between different lines (≈ 75 % of cases on shared corridors) is not in it. So KPI numbers are for comparing stops/hours/lines, not absolute rates.
- The model behind `/buses/live` uses a ping-level label → present it as a demo, not as a validated prediction.
- When `gold.stop_passages` / proper `bunching_events` from `DATASET_DESIGN.md` exist, only the SQL in `services.py` changes; the API shape can stay.
- Coverage: data is clipped to geohash squares and some days are missing → always use `/coverage` and `missing_zones`; never show "no data" as "no bunching".

## 6. Testing
`pytest -q backend/test_api.py` – every route returns 200 on mock data and matches `schemas.py`; invalid params → 422; replay window > 30 min → 422; `stop_id` keeps its leading zero. It needs a **local** Postgres (`DATABASE_URL`): the fixture reloads the mock tables and is skipped automatically if the DB has real data or can't be reached.
