"""Time-of-day congestion along the actual shape between consecutive stops."""
from collections import defaultdict
from datetime import date
from math import hypot

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from db import connect
from traffic import TrafficIndex, pieces, project, speed_ratio, parse_linestring

router = APIRouter(prefix='/api/traffic')
BUCKET_MINUTES = 30
MAX_GROUPS = 100_000


class DiagramRequest(BaseModel):
    date: date
    agency: str = Field(min_length=1, max_length=100)
    line: str = Field(min_length=1, max_length=100)
    direction: str = Field(max_length=20)
    package_id: int | None = Field(default=None, gt=0)
    trip_id: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode='after')
    def exact_trip(self):
        if (self.package_id is None) != (self.trip_id is None):
            raise ValueError('Specify both package_id and trip_id for an exact trip.')
        return self


def reference_path(conn, request):
    trip = conn.execute('''
        SELECT t.package_id, t.trip_id, t.shape_id, count(v.stop_sequence) AS stops
        FROM schedule_trips t
        JOIN schedule_routes r ON r.package_id=t.package_id AND r.route_id=t.route_id
        JOIN schedule_stop_visits v ON v.package_id=t.package_id AND v.trip_id=t.trip_id
        WHERE t.package_id = (SELECT id FROM plan_packages
            WHERE event_agency_id=%s AND %s BETWEEN active_from AND active_until
              AND (%s::bigint IS NULL OR id=%s)
            ORDER BY id DESC LIMIT 1)
          AND r.line_short_name=%s AND t.direction_id=%s
          AND (%s::text IS NULL OR t.trip_id=%s)
        GROUP BY t.package_id, t.trip_id, t.shape_id
        ORDER BY stops DESC, t.trip_id LIMIT 1
    ''', (request.agency, request.date, request.package_id, request.package_id,
          request.line, request.direction, request.trip_id, request.trip_id)).fetchone()
    if not trip:
        raise HTTPException(404, 'No date-valid planned trip for this line and direction.')
    stops = conn.execute('''
        SELECT v.stop_id, v.stop_sequence, s.data->>'stop_name' AS name,
               NULLIF(s.data->>'stop_lat','')::float AS lat,
               NULLIF(s.data->>'stop_lon','')::float AS lon
        FROM schedule_stop_visits v
        LEFT JOIN LATERAL (SELECT data FROM plan_records
            WHERE package_id=v.package_id AND table_name='stops' AND data->>'stop_id'=v.stop_id
            ORDER BY row_number LIMIT 1) s ON true
        WHERE v.package_id=%s AND v.trip_id=%s ORDER BY v.stop_sequence
    ''', (trip['package_id'], trip['trip_id'])).fetchall()
    shape = conn.execute('''
        SELECT (data->>'shape_pt_lat')::float AS lat, (data->>'shape_pt_lon')::float AS lon
        FROM plan_records WHERE package_id=%s AND table_name='shapes' AND data->>'shape_id'=%s
        ORDER BY (data->>'shape_pt_sequence')::int
    ''', (trip['package_id'], trip['shape_id'])).fetchall()
    return trip, stops, [[p['lat'], p['lon']] for p in shape]


def stop_paths(stops, shape):
    """Project stops onto an ordered shape; never replace missing shapes by chords."""
    edges = []
    offset = 0.0
    for start, end in pieces(shape):
        a, b = project(start), project(end)
        length = hypot(b[0] - a[0], b[1] - a[1])
        edges.append((offset, length, start, end, a, b))
        offset += length
    positions = []
    lower = 0.0
    for stop in stops:
        if stop['lat'] is None or stop['lon'] is None:
            positions.append(None)
            continue
        point = project((stop['lat'], stop['lon']))
        best = None
        for at, length, start, end, a, b in edges:
            if at + length < lower:
                continue
            dx, dy = b[0] - a[0], b[1] - a[1]
            t = max(0, min(1, ((point[0]-a[0])*dx + (point[1]-a[1])*dy) / length**2))
            along = at + t * length
            if along < lower:
                continue
            distance = hypot(point[0]-a[0]-t*dx, point[1]-a[1]-t*dy)
            candidate = (distance, along)
            if best is None or candidate < best:
                best = candidate
        position = best[1] if best and best[0] <= 100 else None
        positions.append(position)
        if position is not None:
            lower = position + 0.01
    out = []
    for lo, hi in zip(positions, positions[1:]):
        path = []
        if lo is not None and hi is not None and hi > lo:
            for at, length, start, end, _, _ in edges:
                left, right = max(lo, at), min(hi, at + length)
                if right <= left:
                    continue
                interpolate = lambda value: [start[j] + (end[j]-start[j]) * (value-at)/length for j in (0, 1)]
                path.append((interpolate(left), interpolate(right), right-left))
        out.append(path)
    return out


def diagram_sections(stops, shape, rows):
    index = TrafficIndex(rows)
    records = defaultdict(list)
    for i, row in enumerate(rows):
        ratio = speed_ratio(row['intensity'])
        if ratio is not None and parse_linestring(row['geometry_wkt']):
            records[row['geometry_wkt']].append((i, row['minute'], row['operational_date'], ratio, row['reports']))
    sections = []
    for position, path in enumerate(stop_paths(stops, shape)):
        total = sum(p[2] for p in path)
        days = defaultdict(lambda: [0.0, 0.0])
        coverage = defaultdict(float)
        evidence = defaultdict(set)
        for start, end, length in path:
            piece_days = defaultdict(lambda: [0.0, 0])
            piece_minutes = set()
            for key in index.matching_keys(start, end):
                for record_id, minute, day, ratio, reports in records[key]:
                    piece_days[minute, day][0] += ratio * reports
                    piece_days[minute, day][1] += reports
                    piece_minutes.add(minute)
                    evidence[minute].add(record_id)
            for (minute, day), (ratio_sum, count) in piece_days.items():
                days[minute, day][0] += ratio_sum / count * length
                days[minute, day][1] += length
            for minute in piece_minutes:
                coverage[minute] += length
        cells = []
        for minute in sorted(evidence):
            daily = [value[0]/value[1] for (bucket, _), value in days.items() if bucket == minute]
            cells.append(dict(minute=minute, speedRatio=round(sum(daily)/len(daily), 1),
                              days=len(daily), reports=sum(rows[i]['reports'] for i in evidence[minute]),
                              coverage=round(coverage[minute]/total, 3)))
        sections.append(dict(fromStopId=stops[position]['stop_id'], toStopId=stops[position+1]['stop_id'],
                             fromSequence=stops[position]['stop_sequence'], toSequence=stops[position+1]['stop_sequence'],
                             fromName=stops[position]['name'] or stops[position]['stop_id'],
                             toName=stops[position+1]['name'] or stops[position+1]['stop_id'],
                             geometryAvailable=bool(path), lengthMeters=round(total), cells=cells))
    return sections, index.ignored_reports


@router.post('/diagram')
def diagram_traffic(request: DiagramRequest):
    with connect() as conn, conn.transaction():
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        conn.execute("SET LOCAL statement_timeout='30s'")
        trip, stops, shape = reference_path(conn, request)
        period = conn.execute('''SELECT min(operational_date) AS start, max(operational_date) AS end,
            count(DISTINCT operational_date) AS days, count(*) AS reports FROM waze_jams''').fetchone()
        rows = conn.execute('''
            SELECT geometry_wkt, (observed_at AT TIME ZONE 'Europe/Lisbon')::date AS operational_date,
                (extract(hour FROM observed_at AT TIME ZONE 'Europe/Lisbon')::int * 60
                 + floor(extract(minute FROM observed_at AT TIME ZONE 'Europe/Lisbon') / 30)::int * 30) AS minute,
                intensity, count(*) AS reports, NULL::float AS speed_kmh
            FROM waze_jams GROUP BY 1,2,3,4 ORDER BY 1,2,3,4 LIMIT %s
        ''', (MAX_GROUPS+1,)).fetchall()
    if len(rows) > MAX_GROUPS:
        raise HTTPException(413, 'Traffic history is too large. Precompute traffic summaries first.')
    sections, ignored = diagram_sections(stops, shape, rows)
    return dict(period=period, bucketMinutes=BUCKET_MINUTES, timezone='Europe/Lisbon',
                referenceTripId=trip['trip_id'], packageId=trip['package_id'],
                method='daily-mean-stop-section-time-band-v1', sections=sections, ignoredReports=ignored)
