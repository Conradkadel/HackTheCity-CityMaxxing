"""
FastAPI app with all endpoints (prefix /api/v1).

Owner:  C
Input:  services.py
Output: HTTP API

TODO
  [ ] CORS for http://localhost:5173
  [ ] GET /health, /corridors, /network/{corridor}
  [ ] GET /replay?corridor&date&from_ts&to_ts, GET /alerts
  [ ] GET /events, /kpis, /heatmap
  [ ] GET /scenarios, POST /simulate
  [ ] run: uvicorn backend.main:app --reload
"""
