# Frontend – React (owner: C)

**Stack:** Vite + React + TypeScript · deck.gl (TripsLayer / ScatterplotLayer / PathLayer) on
react-map-gl + MapLibre (free, no token) · TanStack Query (API fetching/caching) · Zustand (global UI state) ·
Recharts (heatmap, KPI charts) · Tailwind (styling).

Init: `npm create vite@latest . -- --template react-ts`, then install the libs above.
Env: `VITE_API_URL=http://localhost:8000/api/v1`.

## Layout
```
frontend/
├── .env.example
├── public/
└── src/
    ├── main.tsx / App.tsx        providers (QueryClient), router, layout
    ├── api/                      client.ts (fetch wrapper) + endpoints.ts (one fn per endpoint)
    ├── types/contracts.ts        TS types mirroring backend/app/schemas  ← the contract
    ├── state/store.ts            Zustand: corridor, date, currentTs, isPlaying, speed, selected event/bus
    ├── hooks/                    useCorridors, useNetwork, useReplay, useEvents, useKpis, useSimulation, usePlayback
    ├── pages/                    ReplayPage, AnalysisPage, SimulatorPage
    ├── components/
    │   ├── layout/               Header, Sidebar
    │   ├── map/                  BaseMap, NetworkLayer, StopsLayer, CoverageLayer, BusLayer, BunchingHighlightLayer
    │   ├── controls/             CorridorSelector, DatePicker, TimeSlider, PlaybackControls, Legend
    │   └── panels/               KpiCards, EventTimeline, AlertList, HeatmapPanel, SimulatorPanel, BeforeAfterChart
    ├── utils/                    colors.ts (headway-ratio scale), time.ts (ms ↔ Lisbon time), geo.ts
    └── styles/
```

## Pages
| Page | Shows |
|---|---|
| ReplayPage (main demo) | map + buses moving coloured by headway status, time slider, alerts, event timeline |
| AnalysisPage | heatmap stop × hour, KPI cards, worst hotspots, causes |
| SimulatorPage | choose scenario + params → before/after KPIs + replay of simulated day |

## Rules
- Work against the backend in mock mode (`USE_MOCK=true`) from day one.
- Never fetch the whole day: request replay in time windows (e.g. 15 min) and prefetch the next one.
- If a type changes, change `backend/app/schemas` AND `src/types/contracts.ts` in the same commit.
