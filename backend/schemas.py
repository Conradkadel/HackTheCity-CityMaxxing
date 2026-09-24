"""
Pydantic models = the contract with the frontend.

Do NOT hand-write frontend/src/types.ts – generate it from this file via OpenAPI:
    npx openapi-typescript http://localhost:8000/openapi.json -o src/types.ts

Rules:
  * snake_case, English names (DB Portuguese names are translated in services.py)
  * ts = unix ms UTC, date = operational date 'YYYY-MM-DD'
  * all ids (stop_id, vehicle_id, trip_id) are strings; line_id may be null
"""
from typing import Any, Generic, Literal, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")

# Small reusable "enums" (Literal = the frontend gets a union type).
Severity = Literal["critical", "moderate", "normal"]          # DB: CRÍTICO / MODERADO / NORMAL
HeadwayStatus = Literal["ok", "at_risk", "bunched"]           # map colour of a bus
VehicleStatus = Literal["moving", "layover"]                  # layover = stop_id is NULL


# ---------- generic -------------------------------------------------------
class ErrorBody(BaseModel):
    code: Literal["not_found", "invalid_param", "no_data", "unavailable"]
    message: str
    details: dict[str, Any] = {}


class ErrorResponse(BaseModel):
    error: ErrorBody


class Page(BaseModel, Generic[T]):
    """Every paged list looks like this."""
    items: list[T]
    total: int
    limit: int
    offset: int


# ---------- system --------------------------------------------------------
class Health(BaseModel):
    status: Literal["ok"]


class Thresholds(BaseModel):
    critical_s: int = 90      # headway <= 90 s  -> critical (CRÍTICO)
    moderate_s: int = 180     # headway <= 180 s -> moderate (MODERADO)
    max_s: int = 300          # rows only exist for headways <= 300 s


class Meta(BaseModel):
    dates: list[str]          # operational dates with GPS data
    thresholds: Thresholds


# ---------- network & coverage -------------------------------------------
class KpiRow(BaseModel):
    group: Optional[str]      # value of the group_by column (None when group_by=none)
    n_events: int
    n_critical: int
    n_moderate: int
    mean_headway_s: Optional[float]
    min_headway_s: Optional[float]


class Corridor(BaseModel):
    corridor_id: str
    name: str
    lines: list[str]
    zones: list[str]          # geohash squares the data is clipped to
    bbox: list[float] = Field(description="[min_lon, min_lat, max_lon, max_lat]")
    dates_available: list[str]


class CorridorDetail(Corridor):
    summary: KpiRow           # whole week


class GeoFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: dict[str, Any]
    properties: dict[str, Any]   # always has kind: line | stop | zone


class FeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[GeoFeature]


class ZoneCoverage(BaseModel):
    geohash: str
    covered: bool
    hours_covered: list[int]  # operational hours 5..28 with at least one ping


# ---------- events (tb_bunching_events) ----------------------------------
class BunchingEvent(BaseModel):
    """One row of tb_bunching_events: a bus reached a stop <= 300 s after another bus of the same line."""
    event_id: str             # follower vehicle + ts (the table has no id)
    ts: int
    agency_id: Optional[str]
    line_id: Optional[str]    # "linha"
    stop_id: Optional[str]
    follower_vehicle: str     # vehicle_id
    leader_vehicle: Optional[str]   # vehicle_id_anterior
    headway_s: Optional[float]      # headway_segundos
    severity: Severity              # nivel_bunching
    lat: Optional[float]
    lon: Optional[float]


# ---------- replay --------------------------------------------------------
class Coverage(BaseModel):
    missing_zones: list[str]  # squares with no ping at all in the window


class ReplayVehicle(BaseModel):
    """One vehicle in deck.gl TripsLayer shape: parallel arrays, one entry per GPS ping."""
    vehicle_id: str
    line_id: Optional[str]
    trip_id: Optional[str]
    path: list[list[float]]   # [[lon, lat], ...]
    timestamps: list[int]
    headway_status: list[Optional[HeadwayStatus]]
    status: list[VehicleStatus]


class ReplayFrame(BaseModel):
    """One GPS ping (format=frames)."""
    ts: int
    vehicle_id: str
    agency_id: Optional[str]
    trip_id: Optional[str]
    line_id: Optional[str]
    lat: float
    lon: float
    next_stop_id: Optional[str]
    status: VehicleStatus
    headway_s: Optional[float]           # from the latest bunching row at this stop (else None)
    headway_status: Optional[HeadwayStatus]
    leader_vehicle_id: Optional[str]


class ReplayResponse(BaseModel):
    corridor: str
    from_ts: int
    to_ts: int
    vehicles: list[ReplayVehicle] = []   # format=trips
    frames: list[ReplayFrame] = []       # format=frames
    coverage: Coverage


class VehicleTrack(BaseModel):
    vehicle_id: str
    frames: list[ReplayFrame]
    events: list[BunchingEvent]          # rows where this bus is follower or leader


class HoldAction(BaseModel):
    type: Literal["hold"] = "hold"
    vehicle_id: str
    stop_id: Optional[str]
    seconds: int


class Alert(BunchingEvent):
    alert_id: str
    action: HoldAction


# ---------- analysis ------------------------------------------------------
class HeatmapStop(BaseModel):
    stop_id: str
    name: Optional[str]


class Heatmap(BaseModel):
    metric: str
    stops: list[HeatmapStop]
    hours: list[int]
    values: list[list[Optional[float]]]  # stops x hours, None = no bunching row in that cell


class Hotspot(BaseModel):
    rank: int
    stop_id: Optional[str]
    name: Optional[str]
    lat: Optional[float]
    lon: Optional[float]
    n_events: int
    n_critical: int
    n_moderate: int
    mean_headway_s: Optional[float]
    min_headway_s: Optional[float]


# ---------- live model (ported from analysis/api_server.py, same output) ---
class Prediction(BaseModel):
    are_we_close_to_bunching: Literal["YES", "MODERATE", "NO"]
    risk_level: Literal["high_probability", "medium_probability", "no_probability"]
    bunching_probability: float


class LiveBus(BaseModel):
    vehicle_id: str
    linha: str
    agency_id: str
    latitude: float
    longitude: float
    last_ping: str
    prediction: Prediction


class LiveBusesResponse(BaseModel):
    status: Literal["success"]
    count: int
    data: list[LiveBus]
    message: Optional[str] = None
