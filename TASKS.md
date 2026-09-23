# Task split & milestones

## People
- **A – Data engineer:** pipeline/, src/bunching/, build_serving
- **B – ML:** ml/
- **C – Backend + Map:** backend/ (FastAPI), frontend/ (React). If 2 people: C1 backend, C2 frontend
- **D – Simulation:** simulation/
- **E – Analysis + Pitch:** analytics/ (causes, KPIs), pitch/, data-partner questions, Carris/MobiCascais GTFS

## Can start immediately (no dependencies)
- [ ] A: clean pings + parse trip_id (start from ../_processed/)
- [ ] B: label + split + baseline on ../_processed/stop_passages.parquet
- [ ] C1: FastAPI skeleton + mock_data.py + all endpoints returning mock
- [ ] C2: Vite React app, BaseMap + NetworkLayer + TimeSlider + BusLayer on mock replay
- [ ] D: simulation engine on synthetic buses
- [ ] E: Waze processing, pitch storyline, get missing GTFS

## Dependencies
- C real data  ← A (stop_passages, replay) , B (predictions), D (sim_results)
- B final model ← A (headways vs schedule)
- D calibration ← A (real headways, dwell/speed distributions)

## Milestones
- [ ] Wed 23 night : contracts agreed, corridor chosen, skeletons + mocks run
- [ ] Thu 24 10:00  : real stop_passages/headways end-to-end (ugly is fine) + questions to partners
- [ ] Thu 24 16:00  : ML beats baseline, simulator before/after, map shows real replay
- [ ] Thu 24 night  : integration + polish, pitch draft
- [ ] Fri 25 06:00  : FEATURE FREEZE, record backup demo video
- [ ] Fri 25 10:00  : submit on Devpost
