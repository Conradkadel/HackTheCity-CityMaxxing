# Bus Bunching Early-Warning – Hack the City #7 (TML + Cascais)

Tool for dispatchers: **replay** a day of real bus operations on a map, **detect** bunching,
**predict** it a few stops ahead, and **simulate** interventions (holding, bus lanes, express).

## Folder map (who owns what)

| Folder | Owner | What lives there |
|---|---|---|
| `config/` | everyone (A decides) | Paths, corridors, thresholds – single source of truth |
| `src/bunching/` | A (shared lib) | Helpers everyone imports: IO, trip_id parsing, geo, schemas |
| `pipeline/` | **A – Data** | Raw CSV/GTFS → clean tables → stop passages & headways |
| `analytics/` | **A/E – Analysis** | Bunching events, KPIs, trigger/cause analysis |
| `ml/` | **B – ML** | Features, labels, baseline, model, evaluation, predictions |
| `simulation/` | **D – Simulation** | What-if engine (holding, speed-ups), before/after KPIs |
| `backend/` | **C – API** | FastAPI + DuckDB (`app/`: routers → services → db, Pydantic schemas) |
| `frontend/` | **C – Map/UI** | React + TS + deck.gl/MapLibre: replay, analysis, simulator pages |
| `notebooks/` | everyone | Exploration only – nothing the app depends on |
| `pitch/` | **E – Pitch** | Storyline, figures, demo script |
| `tests/` | everyone | Contract checks (schemas of shared tables) |
| `data/` | – (git-ignored) | interim / processed / serving / mock outputs |

## Data flow

```
RAW (../vehicles, ../operation-plans, ../Waze, ../calendario.xlsx)
   │  pipeline/  (A)
   ▼
data/interim/     pings_clean, gtfs_*           (1 row = 1 GPS ping / GTFS record)
   ▼
data/processed/   stop_passages, headways       (1 row = 1 bus passing 1 stop)
   │        │                │
   │        ▼ analytics/ (A/E)  ▼ ml/ (B)        ▼ simulation/ (D)
   │   bunching_events, kpis   predictions      sim_results
   ▼
data/serving/     small, pre-computed files per corridor/day for the API
   ▼
backend/ (C)  →  frontend/ (C)
```

**Golden rule:** people only talk through the tables defined in `CONTRACTS.md`.
Until real data exists, build against `data/mock/` (same schema).

## Run order (once implemented)
1. `pipeline/run_pipeline.py`         → interim + processed
2. `analytics/run_analytics.py`       → bunching_events, kpis
3. `ml/train.py` → `ml/predict.py`    → predictions
4. `simulation/run_scenarios.py`      → sim_results
5. `pipeline/build_serving.py`        → data/serving/
6. `cd backend && uvicorn app.main:app --reload` + `cd frontend && npm run dev`

See `TASKS.md` for the split and milestones.
