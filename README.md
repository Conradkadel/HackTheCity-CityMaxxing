# Bus Bunching Early-Warning – Hack the City #7 (TML + Cascais)

Replay a real day of bus operations on a map, **detect** bunching, **predict** it a few stops ahead,
and **simulate** fixes (holding, bus lanes, express).

## Structure
```
code/
├── README.md
├── requirements.txt          Python deps (src + backend)
├── config.yaml               paths, corridors, thresholds – the only place for constants
│
├── notebooks/
│   ├── explore_data.ipynb    EDA, quick checks
│   └── try_model.ipynb       model experiments
│
├── src/                      ← all data + ML logic (Python)
│   ├── __init__.py
│   ├── load_data.py          read raw vehicles / GTFS / calendar / Waze, clean, parse trip_id
│   ├── bunching_detection.py stop passages → headways → bunching events + KPIs
│   ├── feature_engineering.py labels, features, train/test split by day
│   ├── model_training.py     baseline + LightGBM, save model, predict
│   ├── model_analysis.py     metrics vs baseline, lead time, SHAP, figures
│   ├── simulation.py         what-if engine (holding, speed-ups), before/after KPIs
│   ├── pipeline.py           runs everything in order + writes files the backend serves
│   └── utils.py              config, geo (haversine, map-matching), time helpers, IO
│
├── backend/                  ← FastAPI (reads data/serving, never raw data)
│   ├── main.py               app + all endpoints
│   ├── schemas.py            Pydantic response models (= frontend/src/types.ts)
│   ├── services.py           DuckDB queries + call src/simulation.py
│   ├── mock_data.py          fake data with the real schema (frontend can start now)
│   └── .env.example
│
├── frontend/                 ← React + TypeScript (Vite)
│   ├── .env.example
│   ├── public/
│   └── src/
│       ├── main.tsx, App.tsx
│       ├── api.ts            fetch functions + React Query hooks
│       ├── types.ts          mirrors backend/schemas.py
│       ├── store.ts          UI state (corridor, date, time, play/pause)
│       ├── utils.ts          colours, time formatting
│       ├── pages/            ReplayPage, AnalysisPage, SimulatorPage
│       └── components/       MapView, TimeControls, KpiCards, EventTimeline, AlertList, Heatmap, SimulatorPanel
│
├── tests/                    one test file per src module + API
├── prototype/                ← working app (merged from kudzus/project7-prototype): map replay,
│                               Bunching + Simulate tabs, Postgres/CARRIS; see prototype/README.md
└── data/                     (git-ignored) outputs: processed/, serving/, models/
```

## Prototype app

`prototype/` is a self-contained app with its own backend (FastAPI + Postgres) and frontend (React/Leaflet).
Run it from that folder: `docker compose up -d --build --wait` then `npm install && npm run dev`.
The bunching model and the timing simulator are explained in `prototype/docs/BUNCHING_MODEL.md`.

## Data flow
```
raw data (../_processed/vehicles_bus_only, ../operation-plans, ../Waze, ../calendario.xlsx)
  → src/load_data → src/bunching_detection → src/feature_engineering → src/model_training
  → src/simulation → src/pipeline writes data/serving/  → backend → frontend
```

## Shared tables (don't rename columns without telling the team)
| table | key columns |
|---|---|
| pings | agency_id, vehicle_id, trip_id, line_id, direction, ts, lat, lon, stop_id (= NEXT stop), layover_flag |
| stop_passages | passage_id, trip_id, vehicle_id, line_id, corridor, stop_id, date, ts_pass, sched_time, delay_s |
| headways | passage_id, leader_passage_id, headway_s, sched_headway_s, headway_ratio |
| bunching_events | event_id, corridor, leader_trip, follower_trip, start_stop, ts_start, min_headway_s, cause |
| predictions | passage_id, prob_bunch, model_version |
| sim_results | scenario, corridor, kpi, before, after |

Rules: `stop_id` is a **string**; keys include `agency_id`; bunched = `headway_ratio < 0.25`; split train/test **by day**.

## API (FastAPI, prefix /api/v1)
`GET /corridors` · `GET /network/{corridor}` · `GET /replay?corridor&date&from_ts&to_ts` · `GET /alerts` ·
`GET /events` · `GET /kpis` · `GET /heatmap` · `GET /scenarios` · `POST /simulate` · `GET /health`

## Run
```bash
pip install -r requirements.txt
python -m src.pipeline                          # build data/serving
uvicorn backend.main:app --reload --port 8000   # API docs: localhost:8000/docs
cd frontend && npm install && npm run dev       # first time: npm create vite@latest . -- --template react-ts
pytest
```

## Team split
| Person | Owns |
|---|---|
| A – Data | load_data, bunching_detection, utils, pipeline |
| B – ML | feature_engineering, model_training, model_analysis |
| C – Backend | backend/ |
| D – Frontend | frontend/ |
| E – Simulation + pitch | simulation, pitch, questions to data partners |

Milestones: Thu 10:00 real stop passages end-to-end · Thu 16:00 model beats baseline + simulator result + map on real data ·
Fri 06:00 feature freeze + backup demo video · Fri 10:00 submit.
