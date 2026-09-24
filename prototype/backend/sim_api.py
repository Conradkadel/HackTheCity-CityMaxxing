"""API for the Simulate tab: timing changes (dispatch, turnaround, holding) replayed on a real day.

GET /api/sim/scenarios    the scenarios, the plan's scope lines and the fitted k
GET /api/sim/validation   the validation gate and the held-out results (validate_simulator.py)
GET /api/sim/run          one line + direction + day + window: KPIs of every scenario
                          (seed ranges) and the time-space diagram of one scenario vs as run
"""
import statistics
from datetime import date, timedelta
from functools import lru_cache

from fastapi import APIRouter, HTTPException, Query

import bunching
import simulator as S
from bunching_api import ms, open_version, route_stops, window
from db import connect

router = APIRouter(prefix='/api/sim')
BEFORE = timedelta(hours=2)        # trips up to 2 h before the window are simulated too (buses in front)
MAX_SEEDS = 30
KPI_KEYS = ('bunched_pct', 'ewt_s', 'headway_cv', 'hold_s_per_trip', 'terminal_wait_s_per_trip', 'trip_time_min')


def params():
    return S.load_params()


@router.get('/scenarios')
def scenarios():
    p = params()
    return {'scenarios': [{'code': s.code, 'name': s.name, 'lever': s.lever, 'package': s.package}
                          for s in S.SCENARIOS],
            'scopeLines': p.get('lines', []), 'k': p.get('k', S.DEFAULT_K), 'status': p.get('status')}


@router.get('/validation')
def validation():
    p = params()
    if not p:
        raise HTTPException(503, 'Simulator not validated yet. Run backend/validate_simulator.py (see README).')
    return p


@lru_cache(maxsize=16)
def _day(date_value, line, agency):
    """Passages of both directions of a line for the whole day (both are needed for vehicle chains)."""
    with connect() as conn:
        with conn.transaction():
            version = open_version(conn)
            rows = bunching.fetch_passages(conn, version, date_value, agency, [(line, '0'), (line, '1')])
            trip_stops = bunching.fetch_trip_stops(conn, date_value, agency, {r['trip_id'] for r in rows})
            fix = bunching.fetch_schedule_fix(conn, date_value, agency)
            routes = route_stops(conn, agency, date_value)
            stops = {(line, d): routes.get((line, d)) or [] for d in '01'}
            all_stops = sorted({s for v in stops.values() for s in v})
            names = {r['stop_id']: r['stop_name'] for r in conn.execute(
                """SELECT DISTINCT ON (data->>'stop_id') data->>'stop_id' AS stop_id, data->>'stop_name' AS stop_name
                   FROM plan_records WHERE table_name='stops' AND data->>'stop_id'=ANY(%s)
                   AND package_id IN (SELECT id FROM plan_packages WHERE event_agency_id=%s
                     AND %s BETWEEN active_from AND active_until)""", (all_stops, agency, date_value))}
            heads = {r['direction_id']: r['headsign'] for r in conn.execute(
                """SELECT t.direction_id, mode() WITHIN GROUP (ORDER BY h.data->>'trip_headsign') AS headsign
                   FROM schedule_trips t JOIN plan_records h ON h.package_id=t.package_id
                     AND h.table_name='trips' AND h.data->>'trip_id'=t.trip_id
                   WHERE t.trip_id=ANY(%s) GROUP BY 1""", (sorted({r['trip_id'] for r in rows}),))}
    items = bunching.build_features(rows, date_value, 'line', trip_stops, fix)
    return items, trip_stops, stops, names, heads


@lru_cache(maxsize=32)
def _grid(date_value, line, direction, start, end, seeds, agency):
    """KPIs of every scenario over the seeds (the expensive part, cached)."""
    window_start, window_end = window(date_value, start, end)
    items, trip_stops, *_ = _day(date_value, line, agency)
    lo, hi = window_start.timestamp(), window_end.timestamp()
    trips = S.build_trips(items, trip_stops, {(line, '0'), (line, '1')}, since=lo - BEFORE.total_seconds(), until=hi)
    bank = S.build_bank(items)
    pairs = {(line, direction)}
    if not S.in_window(trips, (lo, hi), pairs):
        raise HTTPException(404, 'No recorded trips of this line in this direction and time window.')
    k = params().get('k', S.DEFAULT_K)
    model = bunching.load_model('line')
    threshold = (model.get('alerting') or {}).get('threshold', 0.25) if model else None
    base = S.kpis(trips, S.observed(trips), (lo, hi), pairs)
    rows = []
    for sc in S.SCENARIOS:
        runs = [S.kpis(trips, S.run(trips, bank, sc, seed, k, model, threshold), (lo, hi), pairs)
                for seed in range(seeds if sc.code != 'AS' else 1)]
        stats = {}
        for key in KPI_KEYS:
            values = [r[key] for r in runs if r[key] is not None]
            if values:
                stats[key] = {'mean': round(statistics.mean(values), 2), 'min': min(values), 'max': max(values)}
        saved = sorted(base['ewt_s'] - r['ewt_s'] for r in runs if r['ewt_s'] is not None and base['ewt_s'] is not None)
        rows.append({'code': sc.code, 'name': sc.name, 'lever': sc.lever, 'package': sc.package, 'kpis': stats,
                     'holds': round(statistics.mean(r['holds'] for r in runs), 1),
                     'extraVehicles': S.extra_vehicles(trips, sc, {(line, '0'), (line, '1')}),
                     'ewtSaved': round(statistics.mean(saved), 1) if saved else None,
                     'ewtSavedP5': round(saved[int(0.05 * (len(saved) - 1))], 1) if saved else None})
    return trips, bank, k, model, threshold, base, rows


def recommend_today(rows, share=0.75):
    """The plan's rule on this day only: helps in >= 95 % of the seeds; cheapest with >= 75 % of the best."""
    candidates = [r for r in rows if r['code'] not in ('AS', 'D1') and (r['ewtSavedP5'] or 0) > 0]
    if not candidates:
        return None
    best = max(r['ewtSaved'] for r in candidates)
    good = [r for r in candidates if r['ewtSaved'] >= share * best]
    cost = lambda r: (r['extraVehicles'], r['kpis'].get('hold_s_per_trip', {}).get('mean', 0),  # noqa: E731
                      r['kpis'].get('terminal_wait_s_per_trip', {}).get('mean', 0))
    return min(good, key=cost)['code']


def trajectories(trips, result, lo, hi, pairs, y_of):
    """Trips of the selected direction that run in the window: [[y, t_ms, bunched], ...] per trip."""
    out = {}
    for i, trip in enumerate(trips):
        if (trip.line, trip.direction) not in pairs:
            continue
        passages = result['history'].get(i, [])
        if not passages or passages[-1]['t'] < lo or passages[0]['t'] > hi:
            continue
        points = [[y_of[p['stop_id']], int(p['t'] * 1000),
                   1 if trip.stops[p['index']]['observed'] and S.is_bunched(p) else 0]
                  for p in passages if p['stop_id'] in y_of]
        if points:
            out[i] = points
    return out


@router.get('/run')
def run(date_value: date = Query(..., alias='date'), line: str = Query(..., min_length=1, max_length=10),
        direction: str = Query('0', max_length=5), start: str = '16:00', end: str = '20:00',
        scenario: str = 'D2', seeds: int = Query(10, ge=1, le=MAX_SEEDS), agency: str = 'IA9T6'):
    if scenario not in S.SCENARIO_BY_CODE:
        raise HTTPException(422, f'Unknown scenario {scenario}.')
    window_start, window_end = window(date_value, start, end)
    items, _, stops, names, heads = _day(date_value, line, agency)
    if not items:
        raise HTTPException(404, 'No recorded trips of this line on this day.')
    trips, bank, k, model, threshold, base, rows = _grid(date_value, line, direction, start, end, seeds, agency)
    lo, hi = window_start.timestamp(), window_end.timestamp()
    pairs = {(line, direction)}
    route = stops.get((line, direction)) or []
    y_of = {s: i for i, s in enumerate(dict.fromkeys(route))}

    sc = S.SCENARIO_BY_CODE[scenario]
    result = S.run(trips, bank, sc, 0, k, model, threshold)       # seed 0 = no noise, for the diagram
    as_run, simulated = trajectories(trips, S.observed(trips), lo, hi, pairs, y_of), \
        trajectories(trips, result, lo, hi, pairs, y_of)
    shown = sorted(set(as_run) | set(simulated), key=lambda i: trips[i].stops[0]['t_obs'])
    first_y = lambda i: y_of.get(trips[i].stops[0]['stop_id'])  # noqa: E731

    p = params()
    held_out = (p.get('held_out') or {}).get(line)
    return {
        'date': date_value.isoformat(), 'line': line, 'direction': direction,
        'directionName': f'towards {heads[direction]}' if heads.get(direction) else f'direction {direction}',
        'startTimestamp': ms(window_start), 'endTimestamp': ms(window_end),
        'scenario': scenario, 'seeds': seeds, 'k': k,
        'stops': [{'y': i, 'stop_id': s, 'name': names.get(s, s)} for s, i in y_of.items()],
        'trips': [{'id': i, 'vehicle': trips[i].key[1],
                   'dispatchable': trips[i].dispatchable,
                   'asRun': as_run.get(i, []), 'simulated': simulated.get(i, [])} for i in shown],
        'holds': [{'trip': h['trip'], 'y': y_of.get(trips[h['trip']].stops[h['index']]['stop_id']),
                   't': int(h['t'] * 1000), 's': round(h['seconds'])}
                  for h in result['holds'] if h['trip'] in set(shown)],
        'dispatch': [{'trip': i, 'y': first_y(i), 't': int(trips[i].stops[0]['t_obs'] * 1000),
                      'shift_s': round(result['history'][i][0]['t'] - trips[i].stops[0]['t_obs']),
                      'wait_s': round(result['dispatch_wait'].get(i, 0))}
                     for i in shown if i in result['history'] and trips[i].dispatchable
                     and abs(result['history'][i][0]['t'] - trips[i].stops[0]['t_obs']) >= 15],
        'baseline': base,
        'scenarios': rows,
        'recommendation': {
            'today': recommend_today(rows),
            'heldOut': held_out['recommended'] if held_out else None,
            'heldOutScenarios': {c: {key: s[key] for key in ('robust', 'ewt_saved', 'ewt_saved_range',
                                                            'bunched_pct_change', 'extra_vehicles')}
                                 for c, s in held_out['scenarios'].items()} if held_out else None,
        },
        'validation': {'status': p.get('status'), 'note': p.get('status_note'), 'k': p.get('k'),
                       'kRange': p.get('k_range'), 'testDays': p.get('test_days'),
                       'fitDays': p.get('fit_days')} if p else None,
    }
