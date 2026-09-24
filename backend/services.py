"""
Data access + logic. NO FastAPI imports here – routes in main.py call these functions.

Layer rule:  route (main.py) -> service (this file) -> Postgres (team DB, see schema.sql)

Tables used:
    tb_gps_filtrado      GPS pings on the corridors  -> replay, coverage, dates, live model
    tb_bunching_events   ping-level bunching rows    -> events, alerts, KPIs, heatmap, hotspots
    gtfs_routes/trips/shapes/stops/stop_times        -> map (lines + stops)

Conventions in the API (converted here, the DB keeps its own types):
    ts         unix ms UTC           (DB: timestamp_criado = TIMESTAMP in UTC, no zone)
    date       'YYYY-MM-DD'          (DB: operational_date = BIGINT 20260901)
    ids        strings               (DB: vehicle_id = BIGINT)
    line_id    COALESCE(route_short_name, route_id)  (= "linha" in tb_bunching_events)
"""
import os
import pickle
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

load_dotenv()  # reads backend/.env (or .env in a parent folder) if present

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/bunching")
MAX_REPLAY_MINUTES = int(os.getenv("MAX_REPLAY_MINUTES", "30"))
MODEL_PATH = os.getenv("MODEL_PATH", "modelo_bunching.pkl")   # written by analysis/treinar_modelo_bunching.py
LISBON = ZoneInfo("Europe/Lisbon")
HOURS = list(range(5, 29))  # operational hours: 05:00 ... 04:59 next day = 5..28

# Same thresholds as tb_bunching_events (processar_filtros_backend.py)
THRESHOLDS = {"critical_s": 90, "moderate_s": 180, "max_s": 300}
# nivel_bunching (DB, Portuguese) -> severity (API, English)
SEVERITY = {"CRÍTICO": "critical", "MODERADO": "moderate", "NORMAL": "normal"}
SEVERITY_DB = {v: k for k, v in SEVERITY.items()}
# severity -> headway_status used to colour buses on the map
STATUS = {"critical": "bunched", "moderate": "at_risk", "normal": "ok"}

# Corridors (lines + geohash squares from config.yaml – keep in sync).
# A corridor with no lines (sesimbra) is filtered by its geohash squares only.
CORRIDORS = {
    "mira_sintra": {"name": "Mira-Sintra / Agualva-Cacém", "lines": ["1218", "1219", "1715"],
                    "zones": ["eycks", "eyckk", "eyckt"]},
    "canecas": {"name": "Caneças", "lines": ["1709", "1710", "1711"], "zones": ["eyckw"]},
    "en10": {"name": "EN10", "lines": ["3103", "3512", "3116", "3118", "3505", "3508", "3527", "3535", "3536", "3605"],
             "zones": ["eyce8", "eyceb", "eyc7z"]},
    "sesimbra": {"name": "Sesimbra", "lines": [], "zones": ["eycdb", "eycd8"]},
    "cascais": {"name": "Cascais", "lines": ["M02", "M13", "M14", "M16", "M22", "M27", "M30", "M31", "M32", "M35"],
                "zones": ["eyck1", "eyck3", "eyck4", "eyck6"]},
}

# ---- reusable SQL snippets ------------------------------------------------
LINE = "COALESCE(route_short_name, route_id)"
LOCAL = "(timestamp_criado AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/Lisbon')"      # Lisbon wall-clock time
OPS = f"({LOCAL} - INTERVAL '5 hours')"                                           # shifts to the operational day
OPS_HOUR = f"(MOD(EXTRACT(HOUR FROM {LOCAL})::int + 19, 24) + 5)"                 # 5..28 (00h -> 24, 04h -> 28)
TS_MS = "(EXTRACT(EPOCH FROM timestamp_criado) * 1000)::bigint"                   # TIMESTAMP (UTC) -> unix ms


class ApiError(Exception):
    """Raised by services, turned into {"error": {...}} by main.py."""

    def __init__(self, status: int, code: str, message: str, details: dict | None = None):
        self.status, self.code, self.message, self.details = status, code, message, details or {}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def query(sql: str, params: dict | None = None) -> list[dict]:
    """Run a SELECT and return rows as a list of dicts.
    A new connection per call keeps it simple; fine for a hackathon demo."""
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        return conn.execute(sql, params or {}).fetchall()


def ms_to_db(ts_ms: int) -> datetime:
    """unix ms -> naive UTC datetime (same format as timestamp_criado)."""
    return datetime.fromtimestamp(ts_ms / 1000, timezone.utc).replace(tzinfo=None)


def day_bounds(date: str) -> tuple[datetime, datetime]:
    """Operational day 'YYYY-MM-DD' -> [05:00 Lisbon, next day 05:00 Lisbon) as naive UTC."""
    start = datetime.fromisoformat(date).replace(hour=5, tzinfo=LISBON)
    to_utc = lambda d: d.astimezone(timezone.utc).replace(tzinfo=None)  # noqa: E731
    return to_utc(start), to_utc(start + timedelta(days=1))


def date_to_db(date: str) -> int:
    return int(date.replace("-", ""))          # '2026-09-01' -> 20260901


def db_to_date(d: int) -> str:
    s = str(d)
    return f"{s[:4]}-{s[4:6]}-{s[6:]}"         # 20260901 -> '2026-09-01'


def geohash_bbox(gh: str) -> list[float]:
    """Decode a geohash to [min_lon, min_lat, max_lon, max_lat]."""
    base32 = "0123456789bcdefghjkmnpqrstuvwxyz"
    lon, lat, even = [-180.0, 180.0], [-90.0, 90.0], True
    for ch in gh:
        bits = base32.index(ch)
        for i in range(4, -1, -1):
            rng = lon if even else lat
            mid = (rng[0] + rng[1]) / 2
            rng[0 if bits >> i & 1 else 1] = mid
            even = not even
    return [lon[0], lat[0], lon[1], lat[1]]


def corridor_bbox(c: dict) -> list[float]:
    boxes = [geohash_bbox(z) for z in c["zones"]]
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def check_corridor(corridor_id: str) -> dict:
    c = CORRIDORS.get(corridor_id)
    if c is None:
        raise ApiError(404, "not_found", f"Unknown corridor '{corridor_id}'", {"known": list(CORRIDORS)})
    return {"corridor_id": corridor_id, **c}


def check_date(date: str | None) -> None:
    if date is not None and date not in get_meta()["dates"]:
        raise ApiError(422, "invalid_param", f"No data for {date}", {"dates": get_meta()["dates"]})


def corridor_params(c: dict) -> dict:
    """SQL params used by the corridor filters below."""
    b = corridor_bbox(c)
    return {"zones": c["zones"], "lines": c["lines"], "x0": b[0], "y0": b[1], "x1": b[2], "y1": b[3]}


# pings: inside the corridor squares AND on a corridor line (if the corridor has lines)
PING_IN_CORRIDOR = f"""left(geohash_5, 5) = ANY(%(zones)s)
    AND (cardinality(%(lines)s::text[]) = 0 OR {LINE} = ANY(%(lines)s))"""
# events have no geohash -> use the corridor bounding box + line
EVENT_IN_CORRIDOR = """latitude BETWEEN %(y0)s AND %(y1)s AND longitude BETWEEN %(x0)s AND %(x1)s
    AND (cardinality(%(lines)s::text[]) = 0 OR linha = ANY(%(lines)s))"""


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------
def get_health() -> dict:
    query("SELECT 1")
    return {"status": "ok"}


@lru_cache
def get_meta() -> dict:
    """Dates with data + thresholds. Cached: restart the API after reloading the DB."""
    rows = query("SELECT DISTINCT operational_date AS d FROM tb_gps_filtrado ORDER BY 1")
    return {"dates": [db_to_date(r["d"]) for r in rows if r["d"]], "thresholds": THRESHOLDS}


# ---------------------------------------------------------------------------
# Network & coverage
# ---------------------------------------------------------------------------
def list_corridors() -> list[dict]:
    return [{"corridor_id": cid, "name": c["name"], "lines": c["lines"], "zones": c["zones"],
             "bbox": corridor_bbox(c), "dates_available": get_meta()["dates"]} for cid, c in CORRIDORS.items()]


def get_corridor(corridor_id: str) -> dict:
    check_corridor(corridor_id)
    summary = get_kpis(corridor_id)          # whole week, no grouping
    return {**[x for x in list_corridors() if x["corridor_id"] == corridor_id][0], "summary": summary[0]}


@lru_cache(maxsize=64)
def get_network(corridor_id: str, include: tuple[str, ...], line_id: str | None) -> dict:
    """GeoJSON: GTFS shapes of the corridor lines, their stops, and the geohash squares.
    Cached because stop_times is big and the network never changes."""
    c = check_corridor(corridor_id)
    lines = [line_id] if line_id else c["lines"]
    features = []

    if "lines" in include and lines:
        shapes = query("""
            SELECT DISTINCT r.route_short_name AS line_id, t.direction_id, t.shape_id, r.route_color
            FROM gtfs_trips t JOIN gtfs_routes r ON r.route_id = t.route_id
            WHERE r.route_short_name = ANY(%(lines)s) AND t.shape_id IS NOT NULL""", {"lines": lines})
        points = query("""
            SELECT DISTINCT ON (shape_id, shape_pt_sequence::int)
                   shape_id, shape_pt_lon::float AS lon, shape_pt_lat::float AS lat
            FROM gtfs_shapes WHERE shape_id = ANY(%(ids)s)
            ORDER BY shape_id, shape_pt_sequence::int""", {"ids": list({s["shape_id"] for s in shapes})})
        coords: dict[str, list] = {}
        for p in points:
            coords.setdefault(p["shape_id"], []).append([p["lon"], p["lat"]])
        seen = set()
        for s in shapes:
            if s["shape_id"] in seen:     # same shape listed by several trips/plans
                continue
            seen.add(s["shape_id"])
            features.append({"type": "Feature",
                             "geometry": {"type": "LineString", "coordinates": coords.get(s["shape_id"], [])},
                             "properties": {"kind": "line", "line_id": s["line_id"], "shape_id": s["shape_id"],
                                            "direction": s["direction_id"],
                                            "color": f"#{s['route_color']}" if s["route_color"] else None}})

    if "stops" in include:
        if lines:   # stops served by the corridor lines
            where, p = """stop_id IN (SELECT st.stop_id FROM gtfs_stop_times st
                          JOIN gtfs_trips t ON t.trip_id = st.trip_id
                          JOIN gtfs_routes r ON r.route_id = t.route_id
                          WHERE r.route_short_name = ANY(%(lines)s))""", {"lines": lines}
        else:       # no lines -> every stop inside the corridor box
            b = corridor_bbox(c)
            where = "stop_lat::float BETWEEN %(y0)s AND %(y1)s AND stop_lon::float BETWEEN %(x0)s AND %(x1)s"
            p = {"x0": b[0], "y0": b[1], "x1": b[2], "y1": b[3]}
        for s in query(f"""SELECT DISTINCT ON (stop_id) stop_id, stop_name,
                                  stop_lat::float AS lat, stop_lon::float AS lon
                           FROM gtfs_stops WHERE {where} ORDER BY stop_id""", p):
            features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [s["lon"], s["lat"]]},
                             "properties": {"kind": "stop", "stop_id": s["stop_id"], "name": s["stop_name"]}})

    if "zones" in include:
        for z in c["zones"]:
            x0, y0, x1, y1 = geohash_bbox(z)
            features.append({"type": "Feature",
                             "geometry": {"type": "Polygon",
                                          "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]},
                             "properties": {"kind": "zone", "geohash": z}})
    return {"type": "FeatureCollection", "features": features}


def get_coverage(corridor_id: str, date: str) -> list[dict]:
    """Per geohash square: which operational hours have ANY ping that day.
    Used to grey out the map – 'no data' must never look like 'no bunching'."""
    c = check_corridor(corridor_id)
    check_date(date)
    rows = query(f"""
        SELECT left(geohash_5, 5) AS geohash, array_agg(DISTINCT {OPS_HOUR} ORDER BY {OPS_HOUR}) AS hours
        FROM tb_gps_filtrado
        WHERE operational_date = %(d)s AND left(geohash_5, 5) = ANY(%(zones)s)
        GROUP BY 1""", {"d": date_to_db(date), "zones": c["zones"]})
    hours = {r["geohash"]: r["hours"] for r in rows}
    return [{"geohash": z, "covered": z in hours, "hours_covered": hours.get(z, [])} for z in c["zones"]]


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------
# Every ping + the latest bunching row of that bus at its current stop (<= 10 min old).
REPLAY_SQL = f"""
    SELECT {TS_MS} AS ts, p.vehicle_id::text AS vehicle_id, p.agency_id, p.trip_id,
           {LINE} AS line_id, p.latitude AS lat, p.longitude AS lon, p.stop_id AS next_stop_id,
           left(p.geohash_5, 5) AS geohash,
           e.headway_segundos AS headway_s, e.nivel_bunching, e.vehicle_id_anterior::text AS leader_vehicle_id
    FROM tb_gps_filtrado p
    LEFT JOIN LATERAL (
        SELECT headway_segundos, nivel_bunching, vehicle_id_anterior
        FROM tb_bunching_events e
        WHERE e.vehicle_id = p.vehicle_id AND e.stop_id = p.stop_id
          AND e.timestamp_criado BETWEEN p.timestamp_criado - INTERVAL '10 minutes' AND p.timestamp_criado
        ORDER BY e.timestamp_criado DESC LIMIT 1
    ) e ON TRUE
"""


def _frame(r: dict) -> dict:
    """DB row -> ReplayFrame dict (adds status + headway_status)."""
    sev = SEVERITY.get(r.pop("nivel_bunching", None))
    layover = r["next_stop_id"] is None
    return {**r, "status": "layover" if layover else "moving",
            "headway_status": None if layover else STATUS.get(sev, "ok")}


def get_replay(corridor_id: str, date: str, from_ts: int, to_ts: int, lines: list[str] | None, fmt: str) -> dict:
    c = check_corridor(corridor_id)
    check_date(date)
    if to_ts <= from_ts:
        raise ApiError(422, "invalid_param", "to_ts must be after from_ts")
    if to_ts - from_ts > MAX_REPLAY_MINUTES * 60_000:
        raise ApiError(422, "invalid_param", f"Window too large (max {MAX_REPLAY_MINUTES} min)",
                       {"max_minutes": MAX_REPLAY_MINUTES})

    rows = query(REPLAY_SQL + f"""
        WHERE p.timestamp_criado BETWEEN %(f)s AND %(t)s AND {PING_IN_CORRIDOR}
          AND (%(only)s::text[] IS NULL OR {LINE} = ANY(%(only)s))
        ORDER BY p.vehicle_id, p.timestamp_criado""",
        {**corridor_params(c), "f": ms_to_db(from_ts), "t": ms_to_db(to_ts), "only": lines})
    frames = [_frame(r) for r in rows]

    # zones with no ping at all in the window = no data there (not "no buses")
    seen = {f.pop("geohash") for f in frames}
    out = {"corridor": corridor_id, "from_ts": from_ts, "to_ts": to_ts, "vehicles": [], "frames": [],
           "coverage": {"missing_zones": [z for z in c["zones"] if z not in seen]}}
    if fmt == "frames":
        out["frames"] = frames
        return out

    # format=trips -> one entry per vehicle with parallel arrays (deck.gl TripsLayer shape)
    vehicles: dict[str, dict] = {}
    for f in frames:
        v = vehicles.setdefault(f["vehicle_id"], {"vehicle_id": f["vehicle_id"], "path": [], "timestamps": [],
                                                  "headway_status": [], "status": []})
        v.update(line_id=f["line_id"], trip_id=f["trip_id"])      # latest values in the window
        v["path"].append([f["lon"], f["lat"]])
        v["timestamps"].append(f["ts"])
        v["headway_status"].append(f["headway_status"])
        v["status"].append(f["status"])
    out["vehicles"] = list(vehicles.values())
    return out


def get_vehicle_track(vehicle_id: str, date: str, from_ts: int | None, to_ts: int | None) -> dict:
    """One bus: its pings that day + the bunching rows where it is follower or leader."""
    if not vehicle_id.isdigit():
        raise ApiError(422, "invalid_param", "vehicle_id must be numeric")
    check_date(date)
    start, end = day_bounds(date)
    f = ms_to_db(from_ts) if from_ts else start
    t = ms_to_db(to_ts) if to_ts else end
    p = {"v": int(vehicle_id), "f": f, "t": t}
    frames = [_frame(r) for r in query(REPLAY_SQL + """
        WHERE p.vehicle_id = %(v)s AND p.timestamp_criado BETWEEN %(f)s AND %(t)s
        ORDER BY p.timestamp_criado""", p)]
    for fr in frames:
        fr.pop("geohash")
    if not frames:
        raise ApiError(404, "not_found", f"No pings for vehicle '{vehicle_id}' on {date}")
    events = query(EVENTS_SQL + """
        WHERE (vehicle_id = %(v)s OR vehicle_id_anterior = %(v)s) AND timestamp_criado BETWEEN %(f)s AND %(t)s
        ORDER BY timestamp_criado""", p)
    return {"vehicle_id": vehicle_id, "frames": frames, "events": [_event(e) for e in events]}


def get_alerts(corridor_id: str, date: str, ts: int, window_s: int, min_severity: str) -> list[dict]:
    """Bunching rows in [ts - window, ts] that are at least `min_severity`.
    Suggested action: hold the follower at the stop until the gap is back to the
    'moderate' threshold (180 s), max 120 s."""
    c = check_corridor(corridor_id)
    check_date(date)
    levels = ["CRÍTICO"] if min_severity == "critical" else ["CRÍTICO", "MODERADO"]
    rows = query(EVENTS_SQL + f"""
        WHERE timestamp_criado BETWEEN %(f)s AND %(t)s AND nivel_bunching = ANY(%(lv)s) AND {EVENT_IN_CORRIDOR}
        ORDER BY timestamp_criado DESC""",
        {**corridor_params(c), "f": ms_to_db(ts - window_s * 1000), "t": ms_to_db(ts), "lv": levels})
    alerts = []
    for r in rows:
        e = _event(r)
        hold = int(min(120, max(0, THRESHOLDS["moderate_s"] - (e["headway_s"] or 0))))
        alerts.append({**e, "alert_id": e["event_id"],
                       "action": {"type": "hold", "vehicle_id": e["follower_vehicle"],
                                  "stop_id": e["stop_id"], "seconds": hold}})
    return alerts


# ---------------------------------------------------------------------------
# Analysis (all from tb_bunching_events)
# ---------------------------------------------------------------------------
EVENTS_SQL = f"""
    SELECT {TS_MS} AS ts, agency_id, linha, stop_id, vehicle_id::text AS vehicle_id,
           vehicle_id_anterior::text AS vehicle_id_anterior, headway_segundos, nivel_bunching, latitude, longitude
    FROM tb_bunching_events
"""


def _event(r: dict) -> dict:
    """DB row -> BunchingEvent dict (English names, id = follower + time)."""
    return {"event_id": f"{r['vehicle_id']}_{r['ts']}", "ts": r["ts"], "agency_id": r["agency_id"],
            "line_id": r["linha"], "stop_id": r["stop_id"],
            "follower_vehicle": r["vehicle_id"], "leader_vehicle": r["vehicle_id_anterior"],
            "headway_s": r["headway_segundos"], "severity": SEVERITY.get(r["nivel_bunching"], "normal"),
            "lat": r["latitude"], "lon": r["longitude"]}


def _event_filters(c: dict, date: str | None, line_id: str | None, severity: str | None,
                   stop_id: str | None = None, from_ts: int | None = None, to_ts: int | None = None) -> tuple[str, dict]:
    """WHERE clause + params shared by events / KPIs / heatmap / hotspots."""
    f, t = day_bounds(date) if date else (None, None)
    if from_ts:
        f = ms_to_db(from_ts)
    if to_ts:
        t = ms_to_db(to_ts)
    where = f"""WHERE {EVENT_IN_CORRIDOR}
          AND (%(f)s::timestamp IS NULL OR timestamp_criado >= %(f)s)
          AND (%(t)s::timestamp IS NULL OR timestamp_criado <  %(t)s)
          AND (%(line)s::text IS NULL OR linha = %(line)s)
          AND (%(stop)s::text IS NULL OR stop_id = %(stop)s)
          AND (%(sev)s::text IS NULL OR nivel_bunching = %(sev)s)"""
    return where, {**corridor_params(c), "f": f, "t": t, "line": line_id, "stop": stop_id,
                   "sev": SEVERITY_DB.get(severity) if severity else None}


def list_events(corridor_id: str, date: str | None, line_id: str | None, severity: str | None,
                stop_id: str | None, from_ts: int | None, to_ts: int | None, limit: int, offset: int) -> dict:
    c = check_corridor(corridor_id)
    check_date(date)
    where, p = _event_filters(c, date, line_id, severity, stop_id, from_ts, to_ts)
    total = query("SELECT count(*) AS n FROM tb_bunching_events " + where, p)[0]["n"]
    rows = query(EVENTS_SQL + where + " ORDER BY timestamp_criado LIMIT %(lim)s OFFSET %(off)s",
                 {**p, "lim": limit, "off": offset})
    return {"items": [_event(r) for r in rows], "total": total, "limit": limit, "offset": offset}


# group_by value -> SQL expression used as "group"
GROUP_EXPR = {
    "none": "NULL::text",
    "hour": f"{OPS_HOUR}::text",
    "line": "linha",
    "stop": "stop_id",
    "date": f"to_char({OPS}, 'YYYY-MM-DD')",
    "day_type": f"CASE EXTRACT(ISODOW FROM {OPS}) WHEN 6 THEN 'saturday' WHEN 7 THEN 'sunday' ELSE 'weekday' END",
}
# the numbers every KPI row has
KPI_COLS = """count(*)::int AS n_events,
       count(*) FILTER (WHERE nivel_bunching = 'CRÍTICO')::int  AS n_critical,
       count(*) FILTER (WHERE nivel_bunching = 'MODERADO')::int AS n_moderate,
       avg(headway_segundos)::float AS mean_headway_s,
       min(headway_segundos)::float AS min_headway_s"""


def get_kpis(corridor_id: str, date: str | None = None, line_id: str | None = None, group_by: str = "none") -> list[dict]:
    """Counts of bunching rows (<= 300 s) by group. NOTE: these are ping-level rows, so one
    real episode counts several times – compare groups with each other, not as absolute numbers."""
    c = check_corridor(corridor_id)
    check_date(date)
    where, p = _event_filters(c, date, line_id, None)
    rows = query(f"SELECT {GROUP_EXPR[group_by]} AS \"group\", {KPI_COLS} FROM tb_bunching_events {where} "
                 "GROUP BY 1 ORDER BY 1", p)
    if not rows and group_by == "none":   # keep the shape: one row with zeros
        rows = [{"group": None, "n_events": 0, "n_critical": 0, "n_moderate": 0,
                 "mean_headway_s": None, "min_headway_s": None}]
    return rows


def get_heatmap(corridor_id: str, metric: str, date: str | None, line_id: str | None, top_stops: int) -> dict:
    """Stops x hours matrix. Rows = the `top_stops` stops with most bunching rows.
    Cells with no rows stay None (no bunching row – or no data, check /coverage)."""
    c = check_corridor(corridor_id)
    check_date(date)
    where, p = _event_filters(c, date, line_id, None)
    cells = query(f"SELECT stop_id, {OPS_HOUR} AS hour, {KPI_COLS} FROM tb_bunching_events {where} GROUP BY 1, 2", p)
    totals: dict[str, int] = {}
    for x in cells:
        totals[x["stop_id"]] = totals.get(x["stop_id"], 0) + x["n_events"]
    stop_ids = sorted(totals, key=lambda s: -totals[s])[:top_stops]
    names = _stop_names(stop_ids)
    lookup = {(x["stop_id"], x["hour"]): x[metric] for x in cells}
    return {"metric": metric, "hours": HOURS,
            "stops": [{"stop_id": s, "name": names.get(s)} for s in stop_ids],
            "values": [[lookup.get((s, h)) for h in HOURS] for s in stop_ids]}


def get_hotspots(corridor_id: str, date: str | None, top: int) -> list[dict]:
    """Stops ranked by number of CRITICAL bunching rows."""
    c = check_corridor(corridor_id)
    check_date(date)
    where, p = _event_filters(c, date, None, None)
    rows = query(f"""SELECT stop_id, avg(latitude)::float AS lat, avg(longitude)::float AS lon, {KPI_COLS}
                     FROM tb_bunching_events {where}
                     GROUP BY stop_id ORDER BY n_critical DESC, n_events DESC LIMIT %(n)s""", {**p, "n": top})
    names = _stop_names([r["stop_id"] for r in rows])
    return [{"rank": i + 1, "name": names.get(r["stop_id"]), **r} for i, r in enumerate(rows)]


def _stop_names(stop_ids: list[str]) -> dict[str, str]:
    if not stop_ids:
        return {}
    rows = query("SELECT DISTINCT ON (stop_id) stop_id, stop_name FROM gtfs_stops WHERE stop_id = ANY(%(s)s)",
                 {"s": stop_ids})
    return {r["stop_id"]: r["stop_name"] for r in rows}


# ---------------------------------------------------------------------------
# Live model  (COPIED from analysis/api_server.py – same query, features and output)
# ---------------------------------------------------------------------------
@lru_cache
def _load_model():
    try:
        with open(MODEL_PATH, "rb") as f:
            return pickle.load(f)
    except FileNotFoundError:
        raise ApiError(503, "unavailable", f"Model file '{MODEL_PATH}' not found – run "
                       "analysis/treinar_modelo_bunching.py or set MODEL_PATH")


def get_live_buses(linha: str) -> dict:
    """Last known position of every bus of a line + the model's bunching probability.
    NOTE (DATASET_DESIGN.md §5): the model's label is ping-level, so treat the output as a demo."""
    import pandas as pd   # only needed here

    model = _load_model()
    rows = query(f"""
        WITH ultimos_pings AS (
            SELECT vehicle_id, latitude, longitude, timestamp_criado, stop_id, agency_id,
                   {LINE} AS linha,
                   ROW_NUMBER() OVER (PARTITION BY vehicle_id ORDER BY timestamp_criado DESC) AS rn
            FROM tb_gps_filtrado
            WHERE {LINE} = %(linha)s
        )
        SELECT vehicle_id, latitude, longitude, timestamp_criado, stop_id, agency_id, linha
        FROM ultimos_pings WHERE rn = 1""", {"linha": linha})

    if not rows:
        return {"status": "success", "count": 0, "data": [],
                "message": "Nenhum autocarro ativo encontrado para esta linha."}

    # Same features as analysis/treinar_modelo_bunching.py
    df = pd.DataFrame(rows)
    df["timestamp_criado"] = pd.to_datetime(df["timestamp_criado"])
    df["hora_dia"] = df["timestamp_criado"].dt.hour
    # training used DuckDB DOW (Sunday = 0); pandas dayofweek has Monday = 0 -> shift to match
    df["dia_semana"] = (df["timestamp_criado"].dt.dayofweek + 1) % 7
    df["delta_tempo_veiculo"] = 30          # assumed update interval (s), as in api_server.py
    df["deslocamento_espacial"] = 0.002     # average displacement, as in api_server.py
    df["linha"] = df["linha"].astype("category")
    df["agency_id"] = df["agency_id"].astype("category")
    features = df[["latitude", "longitude", "hora_dia", "dia_semana", "delta_tempo_veiculo",
                   "deslocamento_espacial", "linha", "agency_id"]]
    probas = model.predict_proba(features)[:, 1]

    results = []
    for idx, row in df.iterrows():
        prob = float(probas[idx])
        if prob >= 0.65:
            risk, close = "high_probability", "YES"
        elif prob >= 0.40:
            risk, close = "medium_probability", "MODERATE"
        else:
            risk, close = "no_probability", "NO"
        results.append({
            "vehicle_id": str(row["vehicle_id"]), "linha": str(row["linha"]), "agency_id": str(row["agency_id"]),
            "latitude": float(row["latitude"]), "longitude": float(row["longitude"]),
            "last_ping": row["timestamp_criado"].strftime("%Y-%m-%d %H:%M:%S"),
            "prediction": {"are_we_close_to_bunching": close, "risk_level": risk,
                           "bunching_probability": round(prob, 2)},
        })
    return {"status": "success", "count": len(results), "data": results}
