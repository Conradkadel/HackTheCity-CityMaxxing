"""Typical reported congestion across all imported dates and hours."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from db import connect
from plans_api import fetch_routes_geometry
from traffic import MATCH_METERS, TrafficIndex

router = APIRouter(prefix='/api/traffic')
MAX_GROUPS = 100_000


class TrafficRequest(BaseModel):
    route_keys: list[str] = Field(min_length=1, max_length=100)


@router.post('/routes')
def route_traffic(request: TrafficRequest):
    keys = list(dict.fromkeys(request.route_keys))
    if any(':' not in key or not key.split(':', 1)[0].isdigit()
           or not key.split(':', 1)[1] for key in keys):
        raise HTTPException(422, 'Invalid route key.')
    with connect() as conn, conn.transaction():
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        conn.execute("SET LOCAL statement_timeout='30s'")
        routes = fetch_routes_geometry(conn, keys)
        if len(routes) != len(keys):
            raise HTTPException(404, 'A selected route is no longer available. Refresh the route selection.')
        coverage = conn.execute('''
            SELECT min(operational_date) AS first_date, max(operational_date) AS last_date,
                   count(DISTINCT operational_date) AS days, count(*) AS reports
            FROM waze_jams
        ''').fetchone()
        rows = conn.execute('''
            SELECT geometry_wkt, operational_date, intensity, count(*) AS reports,
                   avg(speed_kmh) FILTER (WHERE speed_kmh >= 0 AND speed_kmh < 'Infinity'::float) AS speed_kmh,
                   count(speed_kmh) FILTER (WHERE speed_kmh >= 0 AND speed_kmh < 'Infinity'::float) AS speed_reports
            FROM waze_jams
            GROUP BY geometry_wkt, operational_date, intensity
            ORDER BY geometry_wkt, operational_date, intensity
            LIMIT %s
        ''', (MAX_GROUPS + 1,)).fetchall()
    if len(rows) > MAX_GROUPS:
        raise HTTPException(413, 'Traffic history is too large for on-demand matching. Precompute traffic summaries first.')
    index = TrafficIndex(rows)
    return {
        'period': {'start': coverage['first_date'], 'end': coverage['last_date'],
                   'days': coverage['days'], 'reports': coverage['reports']},
        'method': 'daily-mean-reported-speed-band-v1',
        'matchRadiusMeters': MATCH_METERS,
        'ignoredReports': index.ignored_reports,
        'routes': [index.route(route) for route in routes],
    }
