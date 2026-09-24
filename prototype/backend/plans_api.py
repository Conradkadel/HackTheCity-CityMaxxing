from datetime import date
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Query
from db import connect
from analysis_config import load_config, parent_cells, preset_geohashes

router = APIRouter(prefix='/api/plans')

def preset_catalog():
    config=load_config()
    return {p['name']:{'id':p['id'],'name':p['name'],'agency_ids':p['operatorAgencyIds'],
            'lines':p['lines'],'geohashes':preset_geohashes(p),'color':p['color']} for p in config['presets']}

def matching_presets(agency,line):
    return [p for p in load_config()['presets'] if agency in p['operatorAgencyIds'] and line in p['lines']]

class BatchRoutesRequest(BaseModel):
    route_keys: list[str]

def get_routes_catalog(conn, operational_date=None):
    where = 'WHERE p.event_agency_id IS NOT NULL AND %s BETWEEN p.active_from AND p.active_until' if operational_date else ''
    params = (operational_date,) if operational_date else ()
    rows = conn.execute(f'''
        SELECT r.package_id, r.route_id, r.line_short_name, r.route_long_name, r.route_color,
               p.source_name, p.event_agency_id, p.agency->0->>'agency_name' as agency_name
        FROM schedule_routes r
        JOIN plan_packages p ON p.id = r.package_id
        {where}
        ORDER BY r.line_short_name, r.route_id
    ''', params).fetchall()

    catalog_routes = []
    for r in rows:
        line = r['line_short_name'] or ''
        matches = matching_presets(r['event_agency_id'],line)
        corridors = [p['name'] for p in matches]
        color = r['route_color'] or ''
        if color and not color.startswith('#'):
            color = f"#{color}"
        elif not color:
            color = matches[0]['color'] if matches else '#277a91'

        primary_corridor = corridors[0] if corridors else f"{r['agency_name'] or 'Carris Metropolitana'}"
        areas = []
        for p in matches:
            areas.extend(parent_cells(preset_geohashes(p)))

        catalog_routes.append({
            'key': f"{r['package_id']}:{r['route_id']}",
            'package_id': r['package_id'],
            'route_id': r['route_id'],
            'line_short_name': line,
            'route_long_name': r['route_long_name'] or line,
            'route_color': color,
            'agency_name': r['agency_name'] or 'Carris Metropolitana',
            'agency_id': r['event_agency_id'],
            'corridor': primary_corridor,
            'corridors': corridors,
            'is_challenge': bool(corridors),
            'directions': [],
            'trip_count': 0,
            'areas': sorted(set(areas))
        })

    config=load_config();catalog=preset_catalog()
    challenge_geohashes={g:z['name'] for p in config['presets'] for z in p['zones'] for g in z['geohashes']}
    payload = {
        'defaultPresetId':config['defaultPresetId'],
        'includeContextByDefault':config['includeContextByDefault'],
        'presets':config['presets'],
        'corridors': catalog,
        'challenge_geohashes': challenge_geohashes,
        'routes': catalog_routes
    }
    return payload

def fetch_routes_geometry(conn, route_keys: list[str]):
    if not route_keys:
        return []

    parsed_keys = []
    for k in route_keys:
        if ':' in k:
            parts = k.split(':', 1)
            try:
                parsed_keys.append((int(parts[0]), parts[1]))
            except ValueError:
                pass

    if not parsed_keys:
        return []

    pids = [k[0] for k in parsed_keys]
    rids = [k[1] for k in parsed_keys]

    # 1. Metadata
    routes_meta = conn.execute('''
        SELECT r.package_id, r.route_id, r.line_short_name, r.route_long_name, r.route_color,
               p.event_agency_id, p.agency->0->>'agency_name' as agency_name
        FROM schedule_routes r
        JOIN plan_packages p ON p.id = r.package_id
        WHERE (r.package_id, r.route_id) IN (SELECT * FROM UNNEST(%s::bigint[], %s::text[]))
    ''', (pids, rids)).fetchall()
    meta_by_key = {(r['package_id'], r['route_id']): r for r in routes_meta}

    # 2. Shapes
    shapes_info = conn.execute('''
        SELECT DISTINCT t.package_id, t.route_id, t.shape_id, t.direction_id
        FROM schedule_trips t
        WHERE (t.package_id, t.route_id) IN (SELECT * FROM UNNEST(%s::bigint[], %s::text[]))
          AND t.shape_id != ''
    ''', (pids, rids)).fetchall()

    shape_pids = [s['package_id'] for s in shapes_info]
    shape_sids = [s['shape_id'] for s in shapes_info]

    shape_points = []
    if shape_pids:
        shape_points = conn.execute('''
            SELECT package_id, data->>'shape_id' as shape_id,
                   (data->>'shape_pt_lat')::float as lat,
                   (data->>'shape_pt_lon')::float as lon
            FROM plan_records
            WHERE table_name='shapes' AND (package_id, data->>'shape_id') IN (SELECT * FROM UNNEST(%s::bigint[], %s::text[]))
            ORDER BY package_id, (data->>'shape_id'), (data->>'shape_pt_sequence')::int
        ''', (shape_pids, shape_sids)).fetchall()

    points_by_shape = {}
    for pt in shape_points:
        k = (pt['package_id'], pt['shape_id'])
        if k not in points_by_shape:
            points_by_shape[k] = []
        points_by_shape[k].append([pt['lat'], pt['lon']])

    shapes_by_route = {}
    for s in shapes_info:
        rk = (s['package_id'], s['route_id'])
        if rk not in shapes_by_route:
            shapes_by_route[rk] = []
        pts = points_by_shape.get((s['package_id'], s['shape_id']), [])
        if pts:
            # If excessive points (> 1200), downsample smoothly to reduce payload
            if len(pts) > 1200:
                pts = pts[::2]
            shapes_by_route[rk].append({
                'shape_id': s['shape_id'],
                'direction_id': s['direction_id'],
                'points': pts
            })

    # 3. Longest trip per direction for representative stops
    longest_trips = conn.execute('''
        WITH ranked AS (
            SELECT t.package_id, t.route_id, t.trip_id, t.direction_id, count(v.stop_sequence) as cnt,
                   ROW_NUMBER() OVER (PARTITION BY t.package_id, t.route_id, t.direction_id ORDER BY count(v.stop_sequence) DESC) as rn
            FROM schedule_trips t
            JOIN schedule_stop_visits v ON v.package_id=t.package_id AND v.trip_id=t.trip_id
            WHERE (t.package_id, t.route_id) IN (SELECT * FROM UNNEST(%s::bigint[], %s::text[]))
            GROUP BY t.package_id, t.route_id, t.trip_id, t.direction_id
        )
        SELECT package_id, route_id, trip_id, direction_id FROM ranked WHERE rn=1
    ''', (pids, rids)).fetchall()

    trip_pids = [t['package_id'] for t in longest_trips]
    trip_ids = [t['trip_id'] for t in longest_trips]

    stop_rows = []
    if trip_pids:
        stop_rows = conn.execute('''
            SELECT v.package_id, v.trip_id, v.stop_id, v.stop_sequence,
                   s.data->>'stop_name' as stop_name,
                   (s.data->>'stop_lat')::float as lat,
                   (s.data->>'stop_lon')::float as lon
            FROM schedule_stop_visits v
            JOIN plan_records s ON s.package_id=v.package_id AND s.table_name='stops' AND s.data->>'stop_id'=v.stop_id
            WHERE (v.package_id, v.trip_id) IN (SELECT * FROM UNNEST(%s::bigint[], %s::text[]))
            ORDER BY v.package_id, v.trip_id, v.stop_sequence
        ''', (trip_pids, trip_ids)).fetchall()

    trip_to_route = {(t['package_id'], t['trip_id']): (t['package_id'], t['route_id'], t['direction_id']) for t in longest_trips}
    stops_by_route = {}
    for st in stop_rows:
        tk = (st['package_id'], st['trip_id'])
        if tk not in trip_to_route:
            continue
        pid, rid, did = trip_to_route[tk]
        rk = (pid, rid)
        if rk not in stops_by_route:
            stops_by_route[rk] = []
        if st['lat'] is not None and st['lon'] is not None:
            stops_by_route[rk].append({
                'stop_id': st['stop_id'],
                'stop_name': st['stop_name'] or st['stop_id'],
                'stop_sequence': st['stop_sequence'],
                'direction_id': did,
                'lat': st['lat'],
                'lon': st['lon']
            })

    out = []
    for rk in parsed_keys:
        meta = meta_by_key.get(rk)
        if not meta:
            continue
        line = meta['line_short_name'] or ''
        matches=matching_presets(meta['event_agency_id'],line)
        corridors = [p['name'] for p in matches]
        color = meta['route_color'] or ''
        if color and not color.startswith('#'):
            color = f"#{color}"
        elif not color:
            color = matches[0]['color'] if matches else '#277a91'

        r_shapes = shapes_by_route.get(rk, [])
        r_stops = stops_by_route.get(rk, [])

        # If no shape is available, construct fallback path from stops
        if not r_shapes and r_stops:
            by_dir = {}
            for st in r_stops:
                by_dir.setdefault(st['direction_id'], []).append([st['lat'], st['lon']])
            for did, pts in by_dir.items():
                if len(pts) >= 2:
                    r_shapes.append({
                        'shape_id': f"stops-{did}",
                        'direction_id': did,
                        'points': pts
                    })

        all_points = [pt for s in r_shapes for pt in s['points']] or [[s['lat'], s['lon']] for s in r_stops]
        bounds = None
        if all_points:
            lats = [p[0] for p in all_points]
            lons = [p[1] for p in all_points]
            bounds = [[min(lats), min(lons)], [max(lats), max(lons)]]

        out.append({
            'key': f"{rk[0]}:{rk[1]}",
            'package_id': rk[0],
            'route_id': rk[1],
            'line_short_name': line,
            'route_long_name': meta['route_long_name'] or line,
            'route_color': color,
            'agency_name': meta['agency_name'] or 'Carris Metropolitana',
            'corridor': corridors[0] if corridors else meta['agency_name'],
            'corridors': corridors,
            'is_challenge': bool(corridors),
            'shapes': r_shapes,
            'stops': r_stops,
            'bounds': bounds
        })

    return out

@router.get('/routes-catalog')
def routes_catalog(date_value: Optional[date] = Query(None, alias='date')):
    with connect() as conn:
        return get_routes_catalog(conn, date_value)

@router.get('/catalog')
def catalog_alias(date_value: Optional[date] = Query(None, alias='date')):
    with connect() as conn:
        return get_routes_catalog(conn, date_value)

@router.post('/routes-geometry')
def post_routes_geometry(req: BatchRoutesRequest):
    with connect() as conn:
        return fetch_routes_geometry(conn, req.route_keys)

@router.get('/routes-geometry')
def get_routes_geometry(keys: str = Query('')):
    route_keys = [k.strip() for k in keys.split(',') if k.strip()]
    with connect() as conn:
        return fetch_routes_geometry(conn, route_keys)

# --- Backward-compatible endpoints ---

def package(conn, pid):
    p = conn.execute('SELECT id,source_name,agency,feed,counts FROM plan_packages WHERE id=%s', (pid,)).fetchone()
    if not p:
        raise HTTPException(404, 'Plan package not found. Refresh packages.')
    return p

@router.get('/packages')
def packages():
    with connect() as c:
        return c.execute('SELECT id,source_name,agency,feed,counts FROM plan_packages ORDER BY source_name,id DESC').fetchall()

@router.get('/{pid}/routes')
def routes(pid: int):
    with connect() as c:
        package(c, pid)
        return [r['data'] for r in c.execute("SELECT data FROM plan_records WHERE package_id=%s AND table_name='routes' ORDER BY data->>'line_id',data->>'route_id'", (pid,))]

@router.get('/{pid}/trips')
def trips(pid: int, route_id: str):
    with connect() as c:
        package(c, pid)
        return [r['data'] for r in c.execute("SELECT data FROM plan_records WHERE package_id=%s AND table_name='trips' AND data->>'route_id'=%s ORDER BY data->>'direction_id',data->>'trip_id'", (pid, route_id))]

@router.get('/{pid}/trip')
def trip(pid: int, trip_id: str):
    with connect() as c:
        p = package(c, pid)
        matches = c.execute("SELECT data FROM plan_records WHERE package_id=%s AND table_name='trips' AND data->>'trip_id'=%s", (pid, trip_id)).fetchall()
        if not matches:
            raise HTTPException(404, 'Planned trip not found.')
        if len(matches) != 1:
            raise HTTPException(409, 'Ambiguous trip ID in source package.')
        t = matches[0]['data']
        shape = [r['data'] for r in c.execute("SELECT data FROM plan_records WHERE package_id=%s AND table_name='shapes' AND data->>'shape_id'=%s ORDER BY (data->>'shape_pt_sequence')::int,row_number", (pid, t.get('shape_id', '')))]
        stops = c.execute("""SELECT st.data AS visit,s.data AS stop FROM plan_records st
         LEFT JOIN plan_records s ON s.package_id=st.package_id AND s.table_name='stops' AND s.data->>'stop_id'=st.data->>'stop_id'
         WHERE st.package_id=%s AND st.table_name='stop_times' AND st.data->>'trip_id'=%s
         ORDER BY (st.data->>'stop_sequence')::int,st.row_number,s.row_number""", (pid, trip_id)).fetchall()
    return {'package': p, 'trip': t, 'shape': [[float(r['shape_pt_lat']), float(r['shape_pt_lon'])] for r in shape], 'stops': stops, 'warning': 'Planned service, not observed movement. These plan dates are not verified for the 2026 vehicle observations.'}
