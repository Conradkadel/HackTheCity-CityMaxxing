"""API for the Bunching tab: time–space diagram, predictions and timing what-if.

GET /api/bunching/model     trained model card (?mode=line|corridor)
GET /api/bunching/lines     lines + named directions with enough trips in the window
GET /api/bunching/shared    other lines/directions that share stops with a chosen route
GET /api/bunching/diagram   one line (same-line bunching) or several lines on a shared
                            route (bunching across lines): passages scored with
                            P(bunching within 5 stops), bus pairs that bunch most,
                            simulated holding times and a recommendation
"""
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

import bunching
from db import active_version, connect
from domain import selection_window

router = APIRouter(prefix='/api/bunching')
HOLD_OPTIONS = [0, 30, 60, 90, 120, 180]   # seconds tested in every what-if run
PREHISTORY = timedelta(minutes=60)          # earlier passages give leaders + trend at the window start
AFTER = timedelta(minutes=30)               # later passages show what really happened next
MIN_TRIPS = 3                               # fewer trips in the window -> no headways to predict from
MIN_SHARED_STOPS = 3                        # a line "shares the route" if it serves >= 3 of its stops
MAX_LINES = 6

PACKAGE_SQL = '''SELECT id FROM plan_packages WHERE event_agency_id=%s AND %s BETWEEN active_from AND active_until
                 ORDER BY id DESC LIMIT 1'''

LINES_SQL = '''
WITH pkg AS (
  SELECT id FROM plan_packages WHERE event_agency_id=%(agency)s
    AND %(day)s BETWEEN active_from AND active_until ORDER BY id DESC LIMIT 1
), seen AS (
  SELECT DISTINCT e.trip_id FROM vehicle_events e
  WHERE e.version_id=%(version)s AND e.agency_id=%(agency)s AND e.operational_date=%(day)s
    AND e.created_at BETWEEN %(start)s AND %(end)s AND e.stop_id<>''
)
SELECT r.line_short_name AS line, t.direction_id, count(*) AS trips,
       mode() WITHIN GROUP (ORDER BY h.data->>'trip_headsign') AS headsign,
       mode() WITHIN GROUP (ORDER BY r.route_long_name) AS route_name
FROM seen s
JOIN schedule_trips t ON t.trip_id=s.trip_id AND t.package_id=(SELECT id FROM pkg)
JOIN schedule_routes r ON r.package_id=t.package_id AND r.route_id=t.route_id
LEFT JOIN plan_records h ON h.package_id=t.package_id AND h.table_name='trips' AND h.data->>'trip_id'=t.trip_id
GROUP BY 1,2 HAVING count(*) >= %(min_trips)s
ORDER BY 1,2
'''

# The stop list of every line + direction = the stops of its longest planned trip.
ROUTE_STOPS_SQL = '''
WITH counts AS (
  SELECT trip_id, count(*) AS n FROM schedule_stop_visits WHERE package_id=%(pkg)s GROUP BY 1
), best AS (
  SELECT DISTINCT ON (r.line_short_name, t.direction_id) r.line_short_name AS line, t.direction_id, t.trip_id
  FROM counts c JOIN schedule_trips t ON t.package_id=%(pkg)s AND t.trip_id=c.trip_id
  JOIN schedule_routes r ON r.package_id=t.package_id AND r.route_id=t.route_id
  ORDER BY r.line_short_name, t.direction_id, c.n DESC, t.trip_id
)
SELECT b.line, b.direction_id, array_agg(v.stop_id ORDER BY v.stop_sequence) AS stops
FROM best b JOIN schedule_stop_visits v ON v.package_id=%(pkg)s AND v.trip_id=b.trip_id
GROUP BY 1,2
'''
_route_stops_cache = {}


def require_model(mode='line'):
    model = bunching.load_model(mode)
    if model is None:
        raise HTTPException(503, 'Bunching model not trained yet. Run backend/train_bunching_model.py (see README).')
    return model


def alert_level(model):
    """The alert level chosen during training (train_bunching_model.py); 0.25 for old model files."""
    return (model.get('alerting') or {}).get('threshold', 0.25)


def ms(value):
    return int(value.timestamp() * 1000)


def window(date_value, start, end):
    try:
        return selection_window(date_value.isoformat(), start, end)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


def open_version(conn):
    conn.execute("SET LOCAL statement_timeout='30s'")
    version = active_version(conn)
    if version is None:
        raise HTTPException(503, 'No completed vehicle dataset is available.')
    return version


def route_stops(conn, agency, day):
    """{(line, direction): [stop_id, ...]} for the plan valid on that day (cached per plan)."""
    row = conn.execute(PACKAGE_SQL, (agency, day)).fetchone()
    if row is None:
        return {}
    if row['id'] not in _route_stops_cache:
        _route_stops_cache[row['id']] = {(r['line'], r['direction_id']): r['stops']
                                         for r in conn.execute(ROUTE_STOPS_SQL, {'pkg': row['id']})}
    return _route_stops_cache[row['id']]


def available_lines(conn, version, agency, day, window_start, window_end):
    rows = conn.execute(LINES_SQL, {'agency': agency, 'day': day, 'version': version, 'start': window_start,
                                    'end': window_end, 'min_trips': MIN_TRIPS}).fetchall()
    out = {}
    for r in rows:
        item = out.setdefault(r['line'], {'line': r['line'], 'name': r['route_name'], 'directions': []})
        item['directions'].append({'id': r['direction_id'], 'trips': r['trips'],
                                   'name': f"towards {r['headsign']}" if r['headsign'] else f"direction {r['direction_id']}"})
    return sorted(out.values(), key=lambda x: (len(x['line']), x['line']))


@router.get('/model')
def model_card(mode: str = Query('line', pattern='^(line|corridor)$')):
    model = require_model(mode)
    return {key: model.get(key) for key in ('model', 'mode', 'trained_at', 'agency', 'target', 'features', 'coef',
                                            'train_days', 'test_days', 'metrics', 'alerting')}


@router.get('/lines')
def lines(date_value: date = Query(..., alias='date'), start: str = '07:00', end: str = '10:00',
          agency: str = 'IA9T6'):
    """Only lines/directions the model can work with: observed in the window with >= 3 trips.
    Directions are named after their most common destination (trip_headsign)."""
    window_start, window_end = window(date_value, start, end)
    with connect() as conn:
        with conn.transaction():
            version = open_version(conn)
            result = available_lines(conn, version, agency, date_value, window_start, window_end)
    return {'date': date_value.isoformat(), 'minTrips': MIN_TRIPS, 'lines': result}


@router.get('/shared')
def shared(date_value: date = Query(..., alias='date'), line: str = Query(..., max_length=10),
           direction: str = Query(..., max_length=5), start: str = '07:00', end: str = '10:00',
           agency: str = 'IA9T6'):
    """Lines/directions (with data in the window) that serve at least 3 stops of the chosen route."""
    window_start, window_end = window(date_value, start, end)
    with connect() as conn:
        with conn.transaction():
            version = open_version(conn)
            candidates = available_lines(conn, version, agency, date_value, window_start, window_end)
            stops = route_stops(conn, agency, date_value)
    primary = stops.get((line, direction))
    if not primary:
        raise HTTPException(404, f'No planned route for line {line} in this direction.')
    primary_set = set(primary)
    out = []
    for item in candidates:
        for d in item['directions']:
            if (item['line'], d['id']) == (line, direction):
                continue
            theirs = stops.get((item['line'], d['id'])) or []
            common = [s for s in primary if s in set(theirs)]
            if len(common) >= MIN_SHARED_STOPS:
                out.append({'line': item['line'], 'name': item['name'], 'direction': d['id'],
                            'directionName': d['name'], 'trips': d['trips'], 'sharedStops': len(common),
                            'routeStops': len(primary)})
    out.sort(key=lambda x: (-x['sharedStops'], x['line']))
    return {'line': line, 'direction': direction, 'routeStops': len(primary_set), 'shared': out}


@router.get('/diagram')
def diagram(date_value: date = Query(..., alias='date'), line: str = Query(..., min_length=1, max_length=10),
            direction: str = Query('0', max_length=5),
            with_lines: Optional[list[str]] = Query(None, alias='with', description='extra lines as line:direction'),
            start: str = '07:00', end: str = '10:00', hold: int = Query(60, ge=0, le=600),
            threshold: Optional[float] = Query(None, gt=0, lt=1), agency: str = 'IA9T6'):
    extra = []
    for value in with_lines or []:
        if ':' not in value:
            raise HTTPException(422, 'Use with=LINE:DIRECTION for extra lines.')
        extra.append(tuple(value.split(':', 1)))
    pairs = list(dict.fromkeys([(line, direction), *extra]))
    if len(pairs) > MAX_LINES:
        raise HTTPException(422, f'Select at most {MAX_LINES} lines.')
    mode = 'corridor' if len(pairs) > 1 else 'line'
    model = require_model(mode)
    threshold = threshold or alert_level(model)
    window_start, window_end = window(date_value, start, end)
    with connect() as conn:
        with conn.transaction():
            version = open_version(conn)
            # both directions of every line: a bus's previous trip gives the model its carried-over delay
            both = list(dict.fromkeys((l, d) for l, _ in pairs for d in ('0', '1')))
            rows = bunching.fetch_passages(conn, version, date_value, agency, both,
                                           window_start - PREHISTORY, window_end + AFTER)
            trip_stops = bunching.fetch_trip_stops(conn, date_value, agency, {r['trip_id'] for r in rows})
            fix = bunching.fetch_schedule_fix(conn, date_value, agency)
            route = route_stops(conn, agency, date_value).get((line, direction)) or []
            names = {r['stop_id']: r['stop_name'] for r in conn.execute(
                """SELECT DISTINCT ON (data->>'stop_id') data->>'stop_id' AS stop_id, data->>'stop_name' AS stop_name
                   FROM plan_records WHERE table_name='stops' AND data->>'stop_id'=ANY(%s)
                   AND package_id IN (SELECT id FROM plan_packages WHERE event_agency_id=%s
                     AND %s BETWEEN active_from AND active_until)""",
                (route, agency, date_value))} if route else {}
            directions = {(r['line'], r['direction_id']): r['headsign'] for r in conn.execute(
                """SELECT r.line_short_name AS line, t.direction_id,
                          mode() WITHIN GROUP (ORDER BY h.data->>'trip_headsign') AS headsign
                   FROM schedule_trips t JOIN schedule_routes r ON r.package_id=t.package_id AND r.route_id=t.route_id
                   JOIN plan_records h ON h.package_id=t.package_id AND h.table_name='trips' AND h.data->>'trip_id'=t.trip_id
                   WHERE t.trip_id=ANY(%s) GROUP BY 1,2""", (sorted({r['trip_id'] for r in rows}),))}

    if not rows:
        raise HTTPException(404, 'No recorded trips of these lines in this direction and time window.')
    items = bunching.score(bunching.build_features(rows, date_value, mode, trip_stops, fix, keep=set(pairs)),
                           model, mode)
    shown = [p for p in items if window_start <= p['t'] <= window_end]

    # y axis = the stops of the FIRST line's route; other lines appear where they share its stops
    y_of = {stop: i for i, stop in enumerate(dict.fromkeys(route))}
    shown_trips = {(p['trip_id'], p['vehicle_id']) for p in shown}
    trips = []
    for (trip_id, vehicle), passages in bunching.trips_of(items).items():
        if (trip_id, vehicle) not in shown_trips:
            continue
        points = [{
            't': ms(p['t']), 'y': y_of[p['stop_id']], 'seq': p['seq'], 'stop_id': p['stop_id'],
            'headway_s': p['hw'], 'sched_headway_s': p['sched_hw'],
            'ratio': round(p['ratio'], 3) if p['ratio'] is not None else None,
            'delay_s': p['delay'], 'leader_vehicle': p['leader_vehicle'], 'leader_line': p['leader_line'],
            'bunched': bool(p['bunched']),
            'prob': round(p['prob'], 4) if p.get('prob') is not None else None,
            'bunched_within_5': p['label'],
        } for p in passages if p['stop_id'] in y_of]
        if points:
            trips.append({'trip_id': trip_id, 'vehicle_id': vehicle, 'line': passages[0]['line'],
                          'direction': passages[0]['direction_id'], 'points': points})

    runs = [bunching.simulate(items, model, mode, h, threshold, (window_start, window_end), trip_stops)
            for h in HOLD_OPTIONS]
    selected = next((r for r in runs if r['hold_s'] == hold), None) or bunching.simulate(
        items, model, mode, hold, threshold, (window_start, window_end), trip_stops)
    recommended = bunching.recommend(runs)

    scored = [p for p in shown if p.get('prob') is not None]
    alerts = [p for p in scored if p['prob'] >= threshold]
    checked = [p for p in alerts if p['label'] is not None]
    strip = lambda run: {k: v for k, v in run.items() if k != 'holds'}  # noqa: E731
    return {
        'date': date_value.isoformat(), 'mode': mode, 'threshold': threshold,
        'line': line, 'direction': direction,
        'lines': [{'line': l, 'direction': d, 'directionName': f'towards {directions[(l, d)]}'
                   if directions.get((l, d)) else f'direction {d}'} for l, d in pairs],
        'directionName': f'towards {directions[(line, direction)]}' if directions.get((line, direction))
        else f'direction {direction}',
        'startTimestamp': ms(window_start), 'endTimestamp': ms(window_end),
        'stops': [{'y': i, 'stop_id': s, 'name': names.get(s, s)} for s, i in y_of.items()],
        'trips': trips,
        'pairs': [{**p, 'first': ms(p['first']), 'last': ms(p['last'])} for p in bunching.top_pairs(shown)],
        'summary': {
            'trips': len(shown_trips), 'passages': len(shown),
            'bunchedPassages': sum(bool(p['bunched']) for p in shown),
            'crossLineBunched': sum(bool(p['bunched']) and not p['same_line'] for p in shown),
            'scoredPassages': len(scored), 'alerts': len(alerts),
            'alertsThatBunched': sum(bool(p['label']) for p in checked), 'alertsChecked': len(checked),
        },
        'scenarios': [strip(r) for r in runs],
        'selected': {**strip(selected), 'holds': [{**h, 't': ms(h['t'])} for h in selected['holds']]},
        'recommendation': strip(recommended) if recommended else None,
        'model': {'mode': mode, 'metrics': model['metrics'], 'target': model['target'],
                  'horizon': model.get('horizon_stops', bunching.HORIZON_BY_MODE[mode]),
                  'trained_at': model['trained_at'],
                  'alerting': {k: v for k, v in (model.get('alerting') or {}).items()
                               if k not in ('table', 'baseline_table')}},
    }
