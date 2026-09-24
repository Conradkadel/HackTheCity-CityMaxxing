"""Bus-bunching prediction and timing what-if (Challenge 7, phase two).

Shared by the API (``bunching_api.py``) and the training script
(``train_bunching_model.py``), so features are computed the same way in
training and in the app.

Two views of bunching
  * ``line``      the bus in front is the previous bus of the SAME line and
                  direction at the stop. Bunched = gap < 25 % of the planned gap.
  * ``corridor``  the bus in front is the previous bus of ANY selected line at
                  the same stop (lines sharing a route). Bunched = the two buses
                  pass the stop less than 60 s apart although they were planned
                  at least 2 min apart (unplanned pairing).

Pipeline
  1. Stop passages: ``vehicle_events.stop_id`` is the stop a bus is serving or
     heading to; the LAST ping that still reports stop S is the moment the bus
     left S. Passages are joined to the date-valid plan (line, direction,
     stop sequence, scheduled time).
  2. Headways to the bus in front (see the two views above).
  3. Label (training): bunched at any of the bus's next 5 observed stops.
  4. Logistic regression -> P(bunching within 5 stops). Coefficients live in
     ``models/*.json``; inference here is plain Python.
  5. What-if (``simulate``): replays the real trajectories in time order. When
     a bus's predicted risk reaches the alert level it waits ``hold`` seconds
     at that stop (never so long that it gets within 60 s of the bus behind;
     at most 3 holds per trip, 3+ stops apart). Everything that bus does later
     happens that much later; all headways and bunching are recomputed from the
     shifted times. With hold = 0 the replay reproduces the observed data exactly.
"""
import heapq
import json
import math
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

LISBON = ZoneInfo('Europe/Lisbon')
MODELS_DIR = Path(__file__).parent / 'models'
MODEL_FILES = {'line': MODELS_DIR / 'bunching_model.json',
               'corridor': MODELS_DIR / 'bunching_model_corridor.json'}
BUNCHED_RATIO = 0.25          # line view: gap < 25 % of the planned gap
CORRIDOR_GAP_S = 60           # corridor view: buses < 60 s apart ...
PLANNED_MIN_GAP_S = 120       # ... although planned >= 2 min apart
HORIZON_BY_MODE = {'line': 10, 'corridor': 5}   # predict bunching within the next N stops
HORIZON_STOPS = HORIZON_BY_MODE['corridor']     # used by shared_next (look-ahead of the route)
ONSET_MIN_RATIO = 0.5         # same line: only predict while the pair is not close yet (P2 in the handoff)
TREND_STOPS = 3               # gap change over the last 3 stops
MAX_ABS_DELAY_S = 1800        # passages > 30 min off schedule are unreliable
SCHED_HEADWAY_RANGE = (PLANNED_MIN_GAP_S, 3600)
SAFE_GAP_BEHIND_S = 60        # a hold never brings the held bus within 60 s of the bus behind
MIN_HOLD_S = 10               # shorter holds are not worth doing
MAX_HOLDS_PER_TRIP = 3        # a bus can be held again, but at most 3 times per trip ...
STOPS_BETWEEN_HOLDS = 3       # ... and at least 3 stops apart
FEATURES = ['log_ratio', 'trend', 'delay_min', 'lead_delay_min', 'sched_hw_min',
            'progress', 'peak_am', 'peak_pm', 'weekend']
FEATURES_BY_MODE = {'line': FEATURES + ['delay_gap_min', 'prev_trip_delay_min'],
                    'corridor': FEATURES + ['same_line', 'shared_next', 'log_gap']}
SUSPECT_MEDIAN_DELAY_S = 1800 # trips whose median delay is > 30 min report the wrong trip_id -> excluded
SHARED_ROUTE_MIN = 0.6        # corridor view: the bus in front also serves >= 60 % of the next 5 stops
TARGETS = {
    'line': f'gap to the previous bus of the same line < {BUNCHED_RATIO:.0%} of the planned gap '
            f'(predicted only while the gap is still >= {ONSET_MIN_RATIO:.0%} of plan)',
    'corridor': f'a bus of any selected line passes the stop < {CORRIDOR_GAP_S} s in front although '
                f'planned >= {PLANNED_MIN_GAP_S // 60} min apart',
}

# One row per (trip, vehicle, stop): first and last ping that reported the stop.
# The LAST ping is when the bus left the stop, except at the final stop of the trip,
# where the bus then waits (layover): there the FIRST ping (arrival) is used.
PASSAGES_SQL = '''
WITH pkg AS (
  SELECT id FROM plan_packages WHERE event_agency_id=%(agency)s
    AND %(day)s BETWEEN active_from AND active_until ORDER BY id DESC LIMIT 1
), trips AS (
  SELECT t.package_id, t.trip_id, t.route_id, t.direction_id, r.line_short_name
  FROM schedule_trips t JOIN pkg ON t.package_id=pkg.id
  JOIN schedule_routes r ON r.package_id=t.package_id AND r.route_id=t.route_id
  WHERE %(lines)s::text[] IS NULL
     OR (r.line_short_name, t.direction_id) IN (SELECT * FROM unnest(%(lines)s::text[], %(directions)s::text[]))
), pings AS (
  SELECT e.trip_id, e.vehicle_id, e.stop_id, min(e.created_at) AS t_first, max(e.created_at) AS t_pass
  FROM vehicle_events e
  WHERE e.version_id=%(version)s AND e.agency_id=%(agency)s AND e.operational_date=%(day)s
    AND e.trip_id IN (SELECT trip_id FROM trips) AND e.stop_id<>''
    AND e.created_at BETWEEN %(start)s AND %(end)s
  GROUP BY 1,2,3
)
SELECT p.trip_id, p.vehicle_id, p.stop_id, p.t_pass, p.t_first, tr.line_short_name AS line, tr.direction_id,
       tr.route_id, v.stop_sequence, v.departure_time, l.last_seq
FROM pings p
JOIN trips tr ON tr.trip_id=p.trip_id
JOIN LATERAL (SELECT stop_sequence, departure_time FROM schedule_stop_visits s
  WHERE s.package_id=tr.package_id AND s.trip_id=p.trip_id AND s.stop_id=p.stop_id
  ORDER BY stop_sequence LIMIT 1) v ON true
JOIN LATERAL (SELECT max(stop_sequence) AS last_seq FROM schedule_stop_visits s
  WHERE s.package_id=tr.package_id AND s.trip_id=p.trip_id) l ON true
'''


def fetch_passages(conn, version, day, agency='IA9T6', pairs=None, start=None, end=None):
    """Stop passages for one operational date.

    pairs: [(line, direction_id), ...] to restrict to some lines, None = all lines.
    """
    start = start or datetime.combine(day, datetime.min.time(), LISBON)
    end = end or start + timedelta(days=2)
    lines = [p[0] for p in pairs] if pairs else None
    directions = [p[1] for p in pairs] if pairs else None
    return conn.execute(PASSAGES_SQL, {'version': version, 'day': day, 'agency': agency, 'lines': lines,
                                       'directions': directions, 'start': start, 'end': end}).fetchall()


TRIP_STOPS_SQL = '''
SELECT s.trip_id, array_agg(s.stop_id ORDER BY s.stop_sequence) AS stops
FROM schedule_stop_visits s
WHERE s.trip_id = ANY(%(trips)s) AND s.package_id = (
  SELECT id FROM plan_packages WHERE event_agency_id=%(agency)s
    AND %(day)s BETWEEN active_from AND active_until ORDER BY id DESC LIMIT 1)
GROUP BY s.trip_id
'''


def fetch_trip_stops(conn, day, agency, trip_ids):
    """Planned stop order of each trip (from the timetable, so no future data is used)."""
    if not trip_ids:
        return {}
    rows = conn.execute(TRIP_STOPS_SQL, {'trips': list(trip_ids), 'agency': agency, 'day': day}).fetchall()
    return {r['trip_id']: r['stops'] for r in rows}


def shared_next(p, leader_trip, trip_stops):
    """Share of this bus's next 5 planned stops that the bus in front will also serve.
    Two lines that split right after this stop cannot stay bunched."""
    if not trip_stops or leader_trip is None:
        return 1.0 if p.get('same_line') else 0.5
    own, lead = trip_stops.get(p['trip_id']), trip_stops.get(leader_trip)
    if not own or not lead or p['stop_id'] not in own:
        return 1.0 if p.get('same_line') else 0.5
    i = own.index(p['stop_id'])
    upcoming = own[i + 1:i + 1 + HORIZON_STOPS]
    return sum(stop in set(lead) for stop in upcoming) / len(upcoming) if upcoming else 0.0


# Some CARRIS trips repeat the trip's start time at every stop ("flat" stop times). For
# those, the time at a stop = start + the typical planned running time to that stop,
# taken from the non-flat trips of the same route (planned data only, no observations).
SCHEDULE_FIX_SQL = '''
WITH v AS (
  SELECT s.trip_id, s.stop_id, split_part(s.departure_time, ':', 1)::int * 3600
         + split_part(s.departure_time, ':', 2)::int * 60 + split_part(s.departure_time, ':', 3)::int AS sec
  FROM schedule_stop_visits s WHERE s.package_id=%(pkg)s
), trip AS (
  SELECT trip_id, min(sec) AS start, max(sec) = min(sec) AS flat FROM v GROUP BY 1
)
SELECT t.route_id, r.line_short_name AS line, t.direction_id, v.stop_id, NULL::text AS flat_trip,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY v.sec - trip.start) AS offset_s
FROM v JOIN trip USING (trip_id)
JOIN schedule_trips t ON t.package_id=%(pkg)s AND t.trip_id=v.trip_id
JOIN schedule_routes r ON r.package_id=t.package_id AND r.route_id=t.route_id
WHERE NOT trip.flat GROUP BY 1,2,3,4
UNION ALL
SELECT NULL, NULL, NULL, NULL, trip_id, NULL FROM trip WHERE flat
'''
_schedule_fix_cache = {}


def fetch_schedule_fix(conn, day, agency):
    """Planned running-time offsets used to repair flat stop times (cached per plan package)."""
    row = conn.execute('SELECT id FROM plan_packages WHERE event_agency_id=%s AND %s BETWEEN active_from AND '
                       'active_until ORDER BY id DESC LIMIT 1', (agency, day)).fetchone()
    if row is None:
        return None
    if row['id'] not in _schedule_fix_cache:
        fix = {'flat': set(), 'route': {}, 'line': {}}
        line_offsets = {}
        for r in conn.execute(SCHEDULE_FIX_SQL, {'pkg': row['id']}):
            if r['flat_trip']:
                fix['flat'].add(r['flat_trip'])
            else:
                fix['route'][(r['route_id'], r['stop_id'])] = r['offset_s']
                line_offsets.setdefault((r['line'], r['direction_id'], r['stop_id']), []).append(r['offset_s'])
        fix['line'] = {k: sorted(v)[len(v) // 2] for k, v in line_offsets.items()}
        _schedule_fix_cache[row['id']] = fix
    return _schedule_fix_cache[row['id']]


def scheduled_time(day, clock):
    """GTFS 'HH:MM:SS' on the operational date -> aware datetime.
    CARRIS writes after-midnight times as 00:xx-03:xx instead of 24:xx-27:xx, and its
    service day starts at 04:00, so hours < 4 belong to the next calendar day."""
    try:
        h, m, s = (int(x) for x in clock.split(':'))
    except (ValueError, AttributeError):
        return None
    if h < 4:
        h += 24
    return datetime(day.year, day.month, day.day, tzinfo=LISBON) + timedelta(hours=h, minutes=m, seconds=s)


def planned_time(r, day, fix):
    """Scheduled time of a passage, repairing flat stop times when possible (else None)."""
    sched = scheduled_time(day, r['departure_time'])
    if sched is None or not fix or r['trip_id'] not in fix['flat']:
        return sched
    offset = fix['route'].get((r.get('route_id'), r['stop_id']))
    if offset is None:
        offset = fix['line'].get((r['line'], r['direction_id'], r['stop_id']))
    return sched + timedelta(seconds=offset) if offset is not None else None


def stop_key(p, mode):
    """Which passages compete for 'the bus in front' at a stop."""
    return p['stop_id'] if mode == 'corridor' else (p['line'], p['direction_id'], p['stop_id'])


def set_headway(p, leader, mode, p_time, leader_time, p_shift=0.0, leader_shift=0.0, trip_stops=None):
    """Fill p's gap to the bus in front. Shifts = seconds a bus has been held (simulation)."""
    p.update(leader_trip=None, leader_vehicle=None, leader_line=None, hw=None, sched_hw=None,
             ratio=None, lead_delay=None, same_line=None)
    if leader is not None:
        p['leader_trip'], p['leader_vehicle'], p['leader_line'] = leader['trip_id'], leader['vehicle_id'], leader['line']
        p['same_line'] = leader['line'] == p['line']
        p['hw'] = (p_time - leader_time).total_seconds()
        p['lead_delay'] = leader['delay'] + leader_shift if leader['delay'] is not None else None
        if p['sched'] and leader['sched']:
            p['sched_hw'] = (p['sched'] - leader['sched']).total_seconds()
    p['valid'] = (p['hw'] is not None and p['sched_hw'] is not None
                  and SCHED_HEADWAY_RANGE[0] <= p['sched_hw'] <= SCHED_HEADWAY_RANGE[1]
                  and p['delay'] is not None and abs(p['delay'] + p_shift) <= MAX_ABS_DELAY_S
                  and p['lead_delay'] is not None and abs(p['lead_delay']) <= MAX_ABS_DELAY_S)
    p['ratio'] = p['hw'] / p['sched_hw'] if p['valid'] else None
    p['shared_next'] = shared_next(p, p['leader_trip'], trip_stops)
    if not p['valid']:
        p['bunched'] = False
    elif mode == 'corridor':
        p['bunched'] = p['hw'] < CORRIDOR_GAP_S
    else:
        p['bunched'] = p['ratio'] < BUNCHED_RATIO


def build_features(rows, day, mode='line', trip_stops=None, fix=None, keep=None, stats=None):
    """Passages (PASSAGES_SQL rows for ONE operational date) -> dicts with headways, features, label.

    trip_stops (fetch_trip_stops) is needed for the corridor feature 'shared_next';
    fix (fetch_schedule_fix) repairs trips whose stop times are all equal;
    keep: set of (line, direction) to keep after trip-level features are computed
          (fetch both directions so a bus's previous trip is known);
    stats: dict that receives counts (trips, suspect_trips).
    """
    items = []
    for r in rows:
        sched = planned_time(r, day, fix)
        last = r.get('last_seq') is not None and r['stop_sequence'] == r['last_seq']
        t = r['t_first'] if last and r.get('t_first') else r['t_pass']
        items.append({'trip_id': r['trip_id'], 'vehicle_id': r['vehicle_id'], 'stop_id': r['stop_id'],
                      'line': r['line'], 'direction_id': r['direction_id'], 'seq': r['stop_sequence'],
                      't': t, 'sched': sched, 'is_last': last,
                      'delay': (t - sched).total_seconds() if sched else None})

    # trip-level: wrong trip_id (median delay > 30 min) and the delay the bus brings from its previous trip
    trips = trips_of(items)
    suspect = set()
    for key, trip in trips.items():
        delays = sorted(p['delay'] for p in trip if p['delay'] is not None)
        if delays and abs(delays[len(delays) // 2]) > SUSPECT_MEDIAN_DELAY_S:
            suspect.add(key)
    if stats is not None:
        stats.update(trips=len(trips), suspect_trips=len(suspect))
    by_vehicle = {}
    for key, trip in trips.items():
        if key not in suspect:
            by_vehicle.setdefault(key[1], []).append(trip)
    for chain in by_vehicle.values():
        chain.sort(key=lambda trip: trip[0]['t'])
        for previous, trip in zip([None] + chain[:-1], chain):
            end = previous[-1] if previous and previous[-1]['t'] <= trip[0]['t'] else None
            for p in trip:
                p['prev_trip_delay'] = end['delay'] if end and end['delay'] is not None \
                    and abs(end['delay']) <= MAX_ABS_DELAY_S else None
    items = [p for p in items if (p['trip_id'], p['vehicle_id']) not in suspect
             and (keep is None or (p['line'], p['direction_id']) in keep)]

    by_stop = {}
    for p in items:
        by_stop.setdefault(stop_key(p, mode), []).append(p)
    for group in by_stop.values():
        group.sort(key=lambda p: p['t'])
        for previous, p in zip([None] + group[:-1], group):
            set_headway(p, previous, mode, p['t'], previous['t'] if previous else None, trip_stops=trip_stops)
    horizon = HORIZON_BY_MODE[mode]
    for trip in trips_of(items).values():
        last_seq = trip[-1]['seq'] or 1
        for i, p in enumerate(trip):
            p['ratio_prev'] = trip[i - TREND_STOPS]['ratio'] if i >= TREND_STOPS else None
            p['progress'] = (p['seq'] or 0) / last_seq
            future = trip[i + 1:i + 1 + horizon]
            p['label'] = any(q['bunched'] for q in future) if future else None
    return items


def trips_of(items):
    """(trip, vehicle) -> its passages in stop order."""
    trips = {}
    for p in items:
        trips.setdefault((p['trip_id'], p['vehicle_id']), []).append(p)
    for trip in trips.values():
        trip.sort(key=lambda p: p['seq'])
    return trips


def feature_vector(p, shift_s=0.0):
    """Model inputs for one passage. shift_s: seconds this bus has been held so far."""
    ratio = max(p['hw'] / p['sched_hw'], 0.0)
    trend = ratio - p['ratio_prev'] if p['ratio_prev'] is not None else 0.0
    local = p['t'].astimezone(LISBON)
    return {
        'log_ratio': math.log(min(max(ratio, 0.05), 3.0)),
        'trend': min(max(trend, -3.0), 3.0),
        'delay_min': (p['delay'] + shift_s) / 60,
        'lead_delay_min': p['lead_delay'] / 60,
        'delay_gap_min': (p['lead_delay'] - p['delay'] - shift_s) / 60,      # > 0: the bus in front is later
        'prev_trip_delay_min': (p.get('prev_trip_delay') or 0.0) / 60,
        'sched_hw_min': p['sched_hw'] / 60,
        'progress': p['progress'],
        'peak_am': 1.0 if 7 <= local.hour <= 9 else 0.0,
        'peak_pm': 1.0 if 17 <= local.hour <= 19 else 0.0,
        'weekend': 1.0 if local.weekday() >= 5 else 0.0,
        'same_line': 1.0 if p.get('same_line') else 0.0,
        'shared_next': p.get('shared_next', 1.0),
        'log_gap': math.log(max(p['hw'], 5.0) / 60),
    }


def scoreable(p, mode):
    """Can the model make a prediction here? Needs a reliable gap and no bunching yet;
    same line: the gap is still >= 50 % of plan (early warning, P2 in the handoff);
    across lines: the bus in front stays on the same route (the model is trained on those)."""
    if not p['valid'] or p['bunched']:
        return False
    if mode == 'line':
        return p['ratio'] >= ONSET_MIN_RATIO
    return p.get('shared_next', 0.0) >= SHARED_ROUTE_MIN


@lru_cache(maxsize=4)
def load_model(mode='line'):
    """The trained model for a view (see train_bunching_model.py). None if not trained yet."""
    try:
        return json.loads(MODEL_FILES[mode].read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None


def predict(model, features):
    """Logistic regression: P(bunched within the next 5 stops)."""
    z = model['intercept']
    for name, coef, mean, std in zip(model['features'], model['coef'], model['mean'], model['std']):
        z += coef * (features[name] - mean) / std
    return 1.0 / (1.0 + math.exp(-max(min(z, 50.0), -50.0)))


def score(items, model, mode='line'):
    """Add 'prob' to every passage that can be scored (see scoreable)."""
    for p in items:
        p['prob'] = predict(model, feature_vector(p)) if scoreable(p, mode) else None
    return items


def simulate(items, model, mode, hold_s, threshold, window, trip_stops=None, max_holds=MAX_HOLDS_PER_TRIP):
    """Replay the data with a holding policy; returns the outcome and the holds made.

    Passages are processed in simulated time order. At each passage the gap to
    the bus in front is recomputed from simulated times and scored with the
    model (only information available at that moment). If the risk reaches the
    threshold, the bus was not held before and the passage is inside the window,
    the bus waits min(hold_s, gap to the bus behind - 60 s) at that stop; this
    passage and all later ones of that bus move that much later.
    Assumption: a held bus keeps its observed running times afterwards and the
    other buses are unaffected except through the changed gaps.
    hold_s = 0 reproduces the observed data exactly.
    """
    start, end = window
    by_id = {id(p): p for p in items}
    sim = {pid: {**p} for pid, p in by_id.items()}
    trip_passages = trips_of(items)
    position = {id(p): i for trip in trip_passages.values() for i, p in enumerate(trip)}
    stop_lists = {}
    for p in items:
        stop_lists.setdefault(stop_key(p, mode), []).append(p)
    shift = {}                                   # (trip, vehicle) -> seconds held
    version = dict.fromkeys(by_id, 0)
    heap = [(p['t'], i, id(p), 0) for i, p in enumerate(items)]
    heapq.heapify(heap)
    counter = len(heap)
    last = {}                                    # stop key -> last finalised passage
    held, holds_of = [], {}                      # trip -> list of stop positions where it was held

    def trip_of(q):
        return (q['trip_id'], q['vehicle_id'])

    def at(q):                                   # simulated time of a passage
        return q['t'] + timedelta(seconds=shift.get(trip_of(q), 0.0))

    while heap:
        time, _, pid, ver = heapq.heappop(heap)
        if ver != version[pid]:
            continue                             # outdated entry: the bus was held meanwhile
        p, s = by_id[pid], sim[pid]
        trip, key = trip_of(p), stop_key(p, mode)
        leader = last.get(key)
        set_headway(s, sim[id(leader)] if leader else None, mode, time, at(leader) if leader else None,
                    shift.get(trip, 0.0), shift.get(trip_of(leader), 0.0) if leader else 0.0, trip_stops)
        passages, index = trip_passages[trip], position[pid]
        s['ratio_prev'] = sim[id(passages[index - TREND_STOPS])]['ratio'] if index >= TREND_STOPS else None

        previous_holds = holds_of.get(trip, [])
        can_hold = (len(previous_holds) < max_holds
                    and all(index - i >= STOPS_BETWEEN_HOLDS for i in previous_holds))
        if hold_s > 0 and can_hold and start <= p['t'] <= end and scoreable(s, mode):
            prob = predict(model, feature_vector(s, shift.get(trip, 0.0)))
            if prob >= threshold:
                holds_of.setdefault(trip, []).append(index)
                behind = [at(q) for q in stop_lists[key] if q is not p and at(q) > time]
                hold = hold_s if not behind else min(hold_s, (min(behind) - time).total_seconds() - SAFE_GAP_BEHIND_S)
                if hold >= MIN_HOLD_S:
                    shift[trip] = shift.get(trip, 0.0) + hold
                    after = {**s, 'hw': s['hw'] + hold}
                    held.append({'trip_id': p['trip_id'], 'vehicle_id': p['vehicle_id'], 'line': p['line'],
                                 'stop_id': p['stop_id'], 'seq': p['seq'], 't': time, 'hold_s': round(hold),
                                 'prob_before': prob, 'prob_after': predict(model, feature_vector(after, shift[trip]))})
                    for q in passages[index:]:   # this stop and everything later moves
                        version[id(q)] += 1
                        counter += 1
                        heapq.heappush(heap, (at(q), counter, id(q), version[id(q)]))
                    continue
        s['t_sim'] = time
        last[key] = p

    in_window = [sim[id(p)] for p in items if start <= p['t'] <= end]
    bunched = [s for s in in_window if s['bunched']]
    return {'hold_s': hold_s, 'threshold': threshold, 'holds_made': len(held),
            'buses_held': len({(h['trip_id'], h['vehicle_id']) for h in held}),
            'total_hold_min': round(sum(h['hold_s'] for h in held) / 60, 1),
            'bunched_passages': len(bunched), 'passages': len(in_window),
            'bunched_pairs': len({(s['vehicle_id'], s['leader_vehicle']) for s in bunched}),
            'holds': held}


def recommend(runs, share=0.75):
    """Shortest hold that achieves at least 75 % of the best reduction in bunched passages.

    Longer holds may help a little more, but every second of holding delays the
    passengers on board, so we stop where the extra benefit gets small.
    """
    base = next((r for r in runs if r['hold_s'] == 0), None)
    if base is None:
        return None
    gains = {r['hold_s']: base['bunched_passages'] - r['bunched_passages'] for r in runs if r['hold_s'] > 0}
    best = max(gains.values(), default=0)
    if best <= 0:
        return None
    hold = min(h for h, gain in gains.items() if gain >= share * best)
    return next(r for r in runs if r['hold_s'] == hold)


def top_pairs(items, limit=8):
    """Bus pairs that bunch most often in the data: follower + the bus in front."""
    pairs = {}
    for p in items:
        if not p['bunched']:
            continue
        pair = pairs.setdefault((p['vehicle_id'], p['leader_vehicle']), {
            'follower_vehicle': p['vehicle_id'], 'follower_line': p['line'], 'follower_trip': p['trip_id'],
            'leader_vehicle': p['leader_vehicle'], 'leader_line': p['leader_line'], 'leader_trip': p['leader_trip'],
            'stops': 0, 'min_gap_s': p['hw'], 'first': p['t'], 'last': p['t']})
        pair['stops'] += 1
        pair['min_gap_s'] = min(pair['min_gap_s'], p['hw'])
        pair['first'], pair['last'] = min(pair['first'], p['t']), max(pair['last'], p['t'])
    return sorted(pairs.values(), key=lambda x: (-x['stops'], x['first']))[:limit]
