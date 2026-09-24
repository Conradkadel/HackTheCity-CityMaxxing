"""
FastAPI app – all endpoints under /api/v1 (see BACKEND.md).

Routes are THIN: validate params -> call services.py -> return a schemas.py model.

Run (from the code/ folder):
    uvicorn backend.main:app --reload --port 8000
    docs: http://localhost:8000/docs      contract: http://localhost:8000/openapi.json
"""
import os
from typing import Literal, Optional

from fastapi import APIRouter, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from backend import schemas as s
from backend import services
from backend.services import ApiError

app = FastAPI(title="Bus Bunching Early-Warning API", version="2.0.0")

# ---------------------------------------------------------------------------
# Middleware: CORS (React dev server), GZip (replay responses are big)
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)


# ---------------------------------------------------------------------------
# Errors -> always {"error": {"code", "message", "details"}}
# ---------------------------------------------------------------------------
@app.exception_handler(ApiError)
async def api_error_handler(_: Request, e: ApiError):
    return JSONResponse(status_code=e.status,
                        content={"error": {"code": e.code, "message": e.message, "details": e.details}})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, e: RequestValidationError):
    return JSONResponse(status_code=422, content={"error": {
        "code": "invalid_param", "message": "Invalid request parameters",
        "details": {"errors": [{"loc": list(err["loc"]), "msg": err["msg"]} for err in e.errors()]}}})


ERRORS = {404: {"model": s.ErrorResponse}, 422: {"model": s.ErrorResponse}}
api = APIRouter(prefix="/api/v1", responses=ERRORS)

SeverityQ = Literal["critical", "moderate", "normal"]


def csv(value: Optional[str]) -> Optional[list[str]]:
    """'a,b' -> ['a', 'b']  (None stays None)."""
    return [x.strip() for x in value.split(",") if x.strip()] if value else None


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------
@api.get("/health", response_model=s.Health, tags=["system"])
def health():
    return services.get_health()


@api.get("/meta", response_model=s.Meta, tags=["system"])
def meta():
    """Dates with data + bunching thresholds – the frontend loads this once on start."""
    return services.get_meta()


# ---------------------------------------------------------------------------
# Network & coverage
# ---------------------------------------------------------------------------
@api.get("/corridors", response_model=list[s.Corridor], tags=["network"])
def corridors():
    return services.list_corridors()


@api.get("/corridors/{corridor_id}", response_model=s.CorridorDetail, tags=["network"])
def corridor(corridor_id: str):
    return services.get_corridor(corridor_id)


@api.get("/network/{corridor_id}", response_model=s.FeatureCollection, tags=["network"])
def network(corridor_id: str,
            include: str = Query("lines,stops,zones", description="csv of lines,stops,zones"),
            line_id: Optional[str] = None):
    """GTFS shapes + stops of the corridor lines, and the geohash squares."""
    return services.get_network(corridor_id, tuple(sorted(csv(include) or [])), line_id)


@api.get("/coverage/{corridor_id}", response_model=list[s.ZoneCoverage], tags=["network"])
def coverage(corridor_id: str, date: str):
    return services.get_coverage(corridor_id, date)


# ---------------------------------------------------------------------------
# Replay (main demo)
# ---------------------------------------------------------------------------
@api.get("/replay", response_model=s.ReplayResponse, tags=["replay"])
def replay(corridor: str, date: str, from_ts: int, to_ts: int,
           line_id: Optional[str] = Query(None, description="csv of line ids"),
           format: Literal["trips", "frames"] = "trips"):
    """GPS pings in a time window (max MAX_REPLAY_MINUTES). Frontend prefetches the next window."""
    return services.get_replay(corridor, date, from_ts, to_ts, csv(line_id), format)


@api.get("/vehicles/{vehicle_id}/track", response_model=s.VehicleTrack, tags=["replay"])
def vehicle_track(vehicle_id: str, date: str, from_ts: Optional[int] = None, to_ts: Optional[int] = None):
    return services.get_vehicle_track(vehicle_id, date, from_ts, to_ts)


@api.get("/alerts", response_model=list[s.Alert], tags=["replay"])
def alerts(corridor: str, date: str, ts: int,
           window_s: int = Query(60, ge=1, le=3600),
           min_severity: Literal["critical", "moderate"] = "moderate"):
    """Bunching rows in [ts - window_s, ts] + a suggested holding action."""
    return services.get_alerts(corridor, date, ts, window_s, min_severity)


# ---------------------------------------------------------------------------
# Analysis (tb_bunching_events)
# ---------------------------------------------------------------------------
@api.get("/events", response_model=s.Page[s.BunchingEvent], tags=["analysis"])
def events(corridor: str, date: Optional[str] = None, line_id: Optional[str] = None,
           severity: Optional[SeverityQ] = None, stop_id: Optional[str] = None,
           from_ts: Optional[int] = None, to_ts: Optional[int] = None,
           limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
    return services.list_events(corridor, date, line_id, severity, stop_id, from_ts, to_ts, limit, offset)


@api.get("/kpis", response_model=list[s.KpiRow], tags=["analysis"])
def kpis(corridor: str, date: Optional[str] = Query(None, description="omit = whole week"),
         line_id: Optional[str] = None,
         group_by: Literal["none", "hour", "line", "stop", "date", "day_type"] = "none"):
    return services.get_kpis(corridor, date, line_id, group_by)


@api.get("/heatmap", response_model=s.Heatmap, tags=["analysis"])
def heatmap(corridor: str,
            metric: Literal["n_events", "n_critical", "n_moderate", "mean_headway_s"] = "n_critical",
            date: Optional[str] = None, line_id: Optional[str] = None,
            top_stops: int = Query(30, ge=1, le=200)):
    return services.get_heatmap(corridor, metric, date, line_id, top_stops)


@api.get("/hotspots", response_model=list[s.Hotspot], tags=["analysis"])
def hotspots(corridor: str, date: Optional[str] = None, top: int = Query(10, ge=1, le=100)):
    return services.get_hotspots(corridor, date, top)


# ---------------------------------------------------------------------------
# Live model (ported from analysis/api_server.py – same path and output)
# ---------------------------------------------------------------------------
@api.get("/buses/live", response_model=s.LiveBusesResponse, tags=["model"])
def get_live_buses(linha: str = Query(..., description="Exemplo: 750, 1715, M22")):
    """Last position of every bus of a line + bunching probability from modelo_bunching.pkl."""
    return services.get_live_buses(linha)


app.include_router(api)
