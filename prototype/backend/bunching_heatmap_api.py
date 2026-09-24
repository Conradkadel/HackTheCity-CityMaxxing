"""Backend-only map and time-space heatmap contracts; no frontend coupling."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from db import active_version, connect
from bunching_heatmap import load_history, build_sections, history_metadata
from traffic_diagram import DiagramRequest, reference_path

router = APIRouter(prefix='/api/bunching/heatmap')
MAX_SHAPES = 200


class HeatmapRoutesRequest(BaseModel):
    route_keys: list[str] = Field(min_length=1, max_length=50)


def read_version(conn):
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    conn.execute("SET LOCAL statement_timeout='30s'")
    version = active_version(conn)
    if version is None:
        raise HTTPException(503, 'No completed vehicle dataset is available.')
    return version


@router.post('/diagram')
def diagram_heatmap(request: DiagramRequest):
    with connect() as conn, conn.transaction():
        version = read_version(conn)
        trip, stops, shape = reference_path(conn, request)
        coverage, rows = load_history(conn, version, request.agency, request.line)
    sections, mapped = build_sections(stops, shape, request.direction, coverage, rows, True)
    return dict(**history_metadata(version, coverage, rows),
                operatorId=request.agency, line=request.line, directionId=request.direction,
                referenceTripId=trip['trip_id'], packageId=trip['package_id'],
                mappedEpisodeCount=len(mapped) if coverage['analyzedDays'] else None, sections=sections)


@router.post('/routes')
def routes_heatmap(request: HeatmapRoutesRequest):
    keys = list(dict.fromkeys(request.route_keys))
    parsed = []
    for key in keys:
        parts = key.split(':', 1)
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1] or len(parts[0]) > 18:
            raise HTTPException(422, 'Invalid route key; expected package_id:route_id.')
        parsed.append((int(parts[0]), parts[1]))
    out = []
    histories = {}
    shape_count = 0
    with connect() as conn, conn.transaction():
        version = read_version(conn)
        for key, (package_id, route_id) in zip(keys, parsed):
            meta = conn.execute('''SELECT r.line_short_name,p.event_agency_id,p.active_from
                FROM schedule_routes r JOIN plan_packages p ON p.id=r.package_id
                WHERE r.package_id=%s AND r.route_id=%s''', (package_id, route_id)).fetchone()
            if not meta:
                raise HTTPException(404, f'Route {key} not found.')
            if not meta['event_agency_id'] or not meta['active_from']:
                raise HTTPException(422, f'Route {key} has no operator or plan validity.')
            agency, line = meta['event_agency_id'], meta['line_short_name']
            if (agency, line) not in histories:
                histories[agency, line] = load_history(conn, version, agency, line)
            coverage, rows = histories[agency, line]
            # Preserve every shape/direction; choose the longest stop pattern for each.
            trips = conn.execute('''SELECT DISTINCT ON (t.shape_id,t.direction_id)
                    t.trip_id,t.shape_id,t.direction_id,count(v.stop_sequence) AS stops
                FROM schedule_trips t JOIN schedule_stop_visits v
                  ON v.package_id=t.package_id AND v.trip_id=t.trip_id
                WHERE t.package_id=%s AND t.route_id=%s
                GROUP BY t.trip_id,t.shape_id,t.direction_id
                ORDER BY t.shape_id,t.direction_id,stops DESC,t.trip_id
                LIMIT %s''', (package_id, route_id, MAX_SHAPES+1)).fetchall()
            shape_count += len(trips)
            if shape_count > MAX_SHAPES:
                raise HTTPException(413, 'Too many route shapes. Select fewer routes; no shapes were truncated.')
            shapes = []
            mapped = set()
            for trip in trips:
                _, stops, shape = reference_path(conn, DiagramRequest(
                    date=meta['active_from'], agency=agency, line=line, direction=trip['direction_id'],
                    package_id=package_id, trip_id=trip['trip_id']))
                sections, episodes = build_sections(stops, shape, trip['direction_id'], coverage, rows, False)
                mapped.update(episodes)
                shapes.append(dict(shapeId=trip['shape_id'], directionId=trip['direction_id'],
                                   referenceTripId=trip['trip_id'], sections=sections))
            out.append(dict(key=key, packageId=package_id, routeId=route_id, operatorId=agency, line=line,
                            **history_metadata(version, coverage, rows),
                            mappedEpisodeCount=len(mapped) if coverage['analyzedDays'] else None, shapes=shapes))
    return dict(datasetVersion=version, routes=out)
