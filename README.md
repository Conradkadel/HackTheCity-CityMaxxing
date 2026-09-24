# RouteMaxxing · Hack The City 2026, Challenge 7 (bus bunching)

RouteMaxxing finds where, when and why CARRIS buses in Lisbon bunch, predicts which buses are about to bunch,
and simulates timetable changes that prevent it.

**Everything lives in [`prototype/`](prototype/).** It is the only app in this repository: a React/Leaflet
frontend, a FastAPI backend and a PostgreSQL database in Docker.

```
code/
├── README.md                 this file
└── prototype/                the RouteMaxxing app
    ├── src/                  frontend (React + TypeScript + Leaflet)
    ├── backend/              API, models, simulator, data import (Python / FastAPI)
    │   └── models/           trained models + findings.json
    ├── docs/                 how everything works (start with FINDINGS.md)
    │   └── research/         early data analysis and findings used in the pitch
    ├── scripts/              download / restore / export the shared database
    ├── compose.yaml          database + API containers
    └── package.json          frontend
```

## Run it

Always run the commands **inside `prototype/`**.

```sh
cd prototype
cp .env.example .env                              # once; set the database password
docker compose -p project7-prototype up -d --build   # database + API on :8000
npm ci                                            # once
npm run dev                                       # app on http://127.0.0.1:5173
```

To get the data, see [Quick start with the shared CARRIS database](prototype/README.md#quick-start-with-the-shared-carris-database).
Full documentation: [`prototype/README.md`](prototype/README.md).

## The app in four tabs

1. **Findings**: the weekly answer: problem lines, hours, stops and causes, and the best fix for each.
2. **Risk prediction**: the early-warning model replayed on a recorded day.
3. **Simulation**: replays a real day with one timetable change and compares.
4. **Explore data**: GPS replay, planned routes, weekly signals and vehicle details.
