# Backend – FastAPI + DuckDB (owner: C)

Thin, read-mostly API over the pre-computed parquet files in `../data/serving/`
(or `../data/mock/` when `USE_MOCK=true`). The only endpoint that computes live is `/simulate`.

## Layout
```
backend/
├── .env.example            DATA_DIR, USE_MOCK, CORS_ORIGINS
├── app/
│   ├── main.py             FastAPI app, CORS, router registration, /api/v1 prefix
│   ├── core/config.py      Settings from env (pydantic-settings)
│   ├── db/duckdb.py        one DuckDB connection, parquet files registered as views
│   ├── schemas/            Pydantic response/request models  ← mirror CONTRACTS.md
│   ├── services/           query + business logic (no HTTP stuff here)
│   ├── api/routers/        thin HTTP layer: params → service → schema
│   └── mock/mock_data.py   generates fake serving files with the contract schema
└── tests/test_api.py
```
**Rule:** routers never query data directly → router → service → db. Schemas are the contract with the frontend
(`frontend/src/types/contracts.ts` must mirror them).

## Endpoints (prefix `/api/v1`)
| Method | Path | Router | Returns |
|---|---|---|---|
| GET | /health | health | status, data source (mock/real) |
| GET | /corridors | network | list of corridors + available dates |
| GET | /network/{corridor} | network | GeoJSON lines + stops + coverage zones |
| GET | /replay?corridor&date&from_ts&to_ts | replay | frames (ts, vehicle, line, lat, lon, headway_ratio, status, prob_bunch) |
| GET | /events?corridor&date | events | bunching episodes |
| GET | /kpis?corridor&date | kpis | KPI cards |
| GET | /heatmap?corridor&metric | kpis | stop × hour matrix |
| GET | /alerts?corridor&date&ts | replay | buses with prob_bunch > threshold + suggested action |
| GET | /scenarios | simulate | available scenarios + default params |
| POST | /simulate | simulate | before/after KPIs (+ optional simulated replay) |

## Run (once implemented)
`uvicorn app.main:app --reload --port 8000` → docs at http://localhost:8000/docs
