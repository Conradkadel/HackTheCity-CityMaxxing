"""
Fill a LOCAL Postgres with FAKE data in exactly the team-DB tables (schema.sql),
so the API and frontend can be tested without the real database.

    python -m backend.mock_data        (run from the code/ folder)

What you get (corridor mira_sintra, 18:00–19:00 Lisbon, Tue 2026-09-01):
  * lines 1715 and 1218 (every 10 min each) on the same 10 stops, GPS ping every 10 s
  * GTFS: routes, trips, shapes, stops, stop_times for those lines
  * tb_bunching_events built with the SAME SQL as the real one (bunching_events.sql)
  * two injected same-line bunching episodes:
      1. 1715 leaves 7 min late and runs slow  -> the next 1715 catches up
      2. 1218 leaves 5.5 min late              -> the next 1218 is only ~4.5 min behind

SAFETY: refuses to run if tb_gps_filtrado contains non-mock rows (= the real DB).
Running it again wipes the mock tables and re-creates them (deterministic, seed 42).
"""
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg

from backend.services import DATABASE_URL, LISBON, geohash_bbox

random.seed(42)

DATE = "2026-09-01"
OP_DATE = 20260901
T0 = datetime(2026, 9, 1, 18, 0, tzinfo=LISBON)                 # 18:00 Lisbon
T0_MS = int(T0.timestamp() * 1000)
PING_S = 10
SEG_S = 150                                                       # scheduled time between two stops
LINE_HEADWAY_S = 600
LINES = {"1715": {"offset_s": 0, "color": "E4572E", "first_vehicle": 41501},
         "1218": {"offset_s": 300, "color": "29335C", "first_vehicle": 41801}}
ZONES = ["eyckk", "eycks", "eyckt"]                               # mira_sintra squares (see services.CORRIDORS)
# (line, trip number) -> injected disruption
DISRUPTIONS = {("1715", 2): {"start_delay_s": 420, "extra_per_seg_s": 15},
               ("1218", 1): {"start_delay_s": 330, "extra_per_seg_s": 0}}
TABLES = ["tb_gps_filtrado", "tb_bunching_events", "gtfs_routes", "gtfs_trips",
          "gtfs_shapes", "gtfs_stops", "gtfs_stop_times"]


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------
def geohash_encode(lat: float, lon: float, precision: int = 5) -> str:
    base32 = "0123456789bcdefghjkmnpqrstuvwxyz"
    lat_r, lon_r, even, bit, ch, out = [-90.0, 90.0], [-180.0, 180.0], True, 0, 0, ""
    while len(out) < precision:
        rng, val = (lon_r, lon) if even else (lat_r, lat)
        mid = (rng[0] + rng[1]) / 2
        if val >= mid:
            ch, rng[0] = ch * 2 + 1, mid
        else:
            ch, rng[1] = ch * 2, mid
        even, bit = not even, bit + 1
        if bit == 5:
            out, bit, ch = out + base32[ch], 0, 0
    return out


def center(gh: str) -> tuple[float, float]:
    x0, y0, x1, y1 = geohash_bbox(gh)
    return (y0 + y1) / 2, (x0 + x1) / 2                           # lat, lon


# Stops: evenly spaced on a path through the centres of the corridor squares.
path = [center(z) for z in ZONES]
STOP_NAMES = ["Terminal Mira-Sintra", "Escola", "Mercado", "Largo da Igreja", "Centro de Saúde",
              "Estação Agualva-Cacém", "Rua Principal", "Bairro Novo", "Rotunda", "Terminal Cacém"]
N = len(STOP_NAMES)
stops = []
for i, name in enumerate(STOP_NAMES):
    f = i / (N - 1) * (len(path) - 1)                               # position along the path
    a, b = path[min(int(f), len(path) - 2)], path[min(int(f), len(path) - 2) + 1]
    w = f - min(int(f), len(path) - 2)
    stops.append({"stop_id": f"0{17100 + i}", "stop_name": name,   # leading zero on purpose
                  "lat": a[0] + w * (b[0] - a[0]), "lon": a[1] + w * (b[1] - a[1])})


# ---------------------------------------------------------------------------
# Trips (actual time at each stop) + vehicle assignment
# ---------------------------------------------------------------------------
def build_trips() -> list[dict]:
    trips = []
    for line, cfg in LINES.items():
        free_at: dict[int, datetime] = {}                          # vehicle -> time it is free again
        for k in range(6):
            sched_dep = T0 + timedelta(seconds=cfg["offset_s"] + k * LINE_HEADWAY_S)
            d = DISRUPTIONS.get((line, k), {})
            t = sched_dep + timedelta(seconds=d.get("start_delay_s", 0))
            times = []
            for i in range(N):
                if i > 0:
                    t += timedelta(seconds=SEG_S + random.gauss(0, 5) + d.get("extra_per_seg_s", 0))
                times.append(t)
            # first bus of this line that is back at the terminal 3 min before departure
            v = next((v for v, free in sorted(free_at.items()) if free + timedelta(minutes=3) <= times[0]),
                     cfg["first_vehicle"] + len(free_at))
            free_at[v] = times[-1]
            trips.append({"trip_id": f"{line}_0_1_{k}", "line": line, "vehicle_id": v,
                          "sched_dep": sched_dep, "times": times})
    return trips


def pings_for(trip: dict) -> list[dict]:
    """GPS pings every 10 s: 3 min layover at the first stop (stop_id NULL), then driving.
    stop_id = the NEXT stop (same meaning as the real data)."""
    out = []
    times = trip["times"]
    t = times[0] - timedelta(minutes=3)
    while t <= times[-1]:
        if t < times[0]:                                            # layover
            lat, lon, next_stop = stops[0]["lat"], stops[0]["lon"], None
        else:
            i = max(j for j in range(N) if times[j] <= t)          # last stop passed
            j = min(i + 1, N - 1)
            span = (times[j] - times[i]).total_seconds()
            f = 0 if span == 0 else (t - times[i]).total_seconds() / span
            lat = stops[i]["lat"] + f * (stops[j]["lat"] - stops[i]["lat"]) + random.gauss(0, 0.00003)
            lon = stops[i]["lon"] + f * (stops[j]["lon"] - stops[i]["lon"]) + random.gauss(0, 0.00003)
            next_stop = stops[j]["stop_id"]
        out.append({"agency_id": "LA77N", "vehicle_id": trip["vehicle_id"], "trip_id": trip["trip_id"],
                    "stop_id": next_stop, "latitude": lat, "longitude": lon, "operational_date": OP_DATE,
                    "timestamp_criado": t.astimezone(timezone.utc).replace(tzinfo=None),   # naive UTC like the DB
                    "geohash_5": geohash_encode(lat, lon), "route_id": f"{trip['line']}_0",
                    "route_short_name": trip["line"]})
        t += timedelta(seconds=PING_S)
    return out


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------
def insert(cur, table: str, rows: list[dict]) -> None:
    cols = list(rows[0])
    cur.executemany(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                    [tuple(r[c] for c in cols) for r in rows])


def main():
    trips = build_trips()
    pings = [p for t in trips for p in pings_for(t)]
    for n, p in enumerate(pings):
        p["_id"] = f"mock-{n}"

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        # --- safety: never overwrite the real database
        exists = cur.execute("SELECT to_regclass('tb_gps_filtrado') IS NOT NULL").fetchone()[0]
        if exists and cur.execute("SELECT 1 FROM tb_gps_filtrado WHERE _id NOT LIKE 'mock-%' LIMIT 1").fetchone():
            raise SystemExit("tb_gps_filtrado has REAL data – refusing to overwrite. Point DATABASE_URL to a local DB.")

        cur.execute("DROP TABLE IF EXISTS " + ", ".join(TABLES))
        cur.execute((Path(__file__).parent / "schema.sql").read_text())

        insert(cur, "tb_gps_filtrado", pings)
        insert(cur, "gtfs_routes", [{"route_id": f"{l}_0", "route_short_name": l,
                                     "route_long_name": "Mira-Sintra - Cacém (mock)", "route_color": c["color"]}
                                    for l, c in LINES.items()])
        insert(cur, "gtfs_trips", [{"route_id": f"{t['line']}_0", "service_id": "mock", "trip_id": t["trip_id"],
                                    "direction_id": "0", "shape_id": f"{t['line']}_0_shp"} for t in trips])
        insert(cur, "gtfs_shapes", [{"shape_id": f"{l}_0_shp", "shape_pt_lat": str(s["lat"]),
                                     "shape_pt_lon": str(s["lon"]), "shape_pt_sequence": str(i + 1)}
                                    for l in LINES for i, s in enumerate(stops)])
        insert(cur, "gtfs_stops", [{"stop_id": s["stop_id"], "stop_name": s["stop_name"],
                                    "stop_lat": str(s["lat"]), "stop_lon": str(s["lon"])} for s in stops])
        insert(cur, "gtfs_stop_times", [
            {"trip_id": t["trip_id"], "stop_id": s["stop_id"], "stop_sequence": str(i + 1),
             "arrival_time": (t["sched_dep"] + timedelta(seconds=i * SEG_S)).strftime("%H:%M:%S"),
             "departure_time": (t["sched_dep"] + timedelta(seconds=i * SEG_S)).strftime("%H:%M:%S")}
            for t in trips for i, s in enumerate(stops)])

        # same logic as the real tb_bunching_events
        cur.execute((Path(__file__).parent / "bunching_events.sql").read_text())
        n_ev = cur.execute("SELECT nivel_bunching, count(*) FROM tb_bunching_events GROUP BY 1 ORDER BY 1").fetchall()

    print(f"mock data written: {len(stops)} stops, {len(trips)} trips, {len(pings)} pings, "
          f"bunching rows {dict(n_ev)}")


if __name__ == "__main__":
    main()
