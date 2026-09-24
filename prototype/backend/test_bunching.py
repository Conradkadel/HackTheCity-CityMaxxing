from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

import bunching

LISBON = ZoneInfo('Europe/Lisbon')
DAY = date(2026, 9, 1)
T0 = datetime(2026, 9, 1, 8, 0, tzinfo=LISBON)
WINDOW = (T0 - timedelta(hours=1), T0 + timedelta(hours=2))
LINE_FEATURES = bunching.FEATURES_BY_MODE['line']
MODEL = {'features': LINE_FEATURES, 'intercept': -4.0,
         'coef': [-2.0, 0.5] + [0.0] * (len(LINE_FEATURES) - 2),
         'mean': [0.0] * len(LINE_FEATURES), 'std': [1.0] * len(LINE_FEATURES)}
CORRIDOR_FEATURES = bunching.FEATURES_BY_MODE['corridor']
CORRIDOR_MODEL = {**MODEL, 'features': CORRIDOR_FEATURES,
                  'coef': [-2.0, 0.5] + [0.0] * (len(CORRIDOR_FEATURES) - 3) + [-1.0],
                  'mean': [0.0] * len(CORRIDOR_FEATURES), 'std': [1.0] * len(CORRIDOR_FEATURES)}


def rows_for(trip, vehicle, first_departure, actual_offsets, line='742', stops=None, flat=False):
    """One trip; scheduled every 2 min (or all at the start time when flat), actual = schedule + offset."""
    out = []
    for i, offset in enumerate(actual_offsets):
        sched = first_departure + timedelta(minutes=2 * i)
        out.append({'trip_id': trip, 'vehicle_id': vehicle, 'stop_id': (stops or [f'S{n}' for n in range(1, 99)])[i],
                    'line': line, 'direction_id': '0', 'route_id': f'{line}_0', 'stop_sequence': i + 1,
                    'departure_time': (first_departure if flat else sched).strftime('%H:%M:%S'),
                    't_pass': (sched + timedelta(seconds=offset)).astimezone(ZoneInfo('UTC'))})
    return out


def sample_rows():
    leader = rows_for('A', 'v1', T0, [0, 60, 120, 180, 240, 300, 360, 420])          # leader gets later and later
    follower = rows_for('B', 'v2', T0 + timedelta(minutes=10), [0] * 8)                # follower on time, 10 min behind
    behind = rows_for('C', 'v3', T0 + timedelta(minutes=20), [0] * 8)                  # next bus, on time
    return leader + follower + behind


def sample():
    return bunching.build_features(sample_rows(), DAY)


def test_leader_headway_ratio_and_label():
    items = {(p['trip_id'], p['seq']): p for p in sample()}
    first = items[('B', 1)]
    assert first['leader_trip'] == 'A' and first['hw'] == 600 and first['sched_hw'] == 600
    assert first['ratio'] == pytest.approx(1.0)
    last = items[('B', 8)]
    assert last['hw'] == 600 - 420 and last['ratio'] == pytest.approx(0.3)
    assert not last['bunched']
    assert items[('A', 1)]['leader_trip'] is None and not items[('A', 1)]['valid']


def test_label_looks_only_at_the_next_five_stops():
    by = {(p['trip_id'], p['seq']): p for p in sample()}
    assert by[('B', 8)]['label'] is None          # no future stops
    assert by[('B', 1)]['label'] is False


def test_predict_is_a_probability_and_falls_when_gap_grows():
    p = next(q for q in sample() if q['trip_id'] == 'B' and q['seq'] == 7)
    base = bunching.predict(MODEL, bunching.feature_vector(p))
    held = bunching.predict(MODEL, bunching.feature_vector({**p, 'hw': p['hw'] + 120}, 120))
    assert 0 < held < base < 1


def test_corridor_view_pairs_different_lines_on_shared_stops():
    t = T0
    a = rows_for('A', 'v1', t, [0, 0, 0, 0], line='736', stops=['X1', 'X2', 'X3', 'X4'])
    b = rows_for('B', 'v2', t + timedelta(minutes=3), [-150, -160, -170, -170], line='738',
                 stops=['X1', 'X2', 'X3', 'Y4'])
    trip_stops = {'A': ['X1', 'X2', 'X3', 'X4'], 'B': ['X1', 'X2', 'X3', 'Y4']}
    items = {(p['trip_id'], p['seq']): p for p in bunching.build_features(a + b, DAY, 'corridor', trip_stops)}
    x2 = items[('B', 2)]
    assert x2['leader_trip'] == 'A' and not x2['same_line'] and x2['hw'] == 20 and x2['bunched']
    assert x2['shared_next'] == pytest.approx(0.5)          # of X3, Y4 only X3 is on the leader's route
    assert items[('B', 4)]['leader_trip'] is None           # Y4 is not on line 736
    # the line view ignores the other line completely
    line_view = {(p['trip_id'], p['seq']): p for p in bunching.build_features(a + b, DAY, 'line', trip_stops)}
    assert line_view[('B', 2)]['leader_trip'] is None


def test_simulation_without_holds_reproduces_the_data():
    items = bunching.score(sample(), MODEL)
    run = bunching.simulate(items, MODEL, 'line', 0, 0.05, WINDOW)
    assert run['bunched_passages'] == sum(p['bunched'] for p in items)
    assert run['holds_made'] == 0


def test_simulated_hold_shifts_the_bus_and_its_later_stops():
    items = bunching.score(sample(), MODEL)
    run = bunching.simulate(items, MODEL, 'line', 60, 0.05, WINDOW)
    assert run['holds_made'] >= 1 and all(h['trip_id'] == 'B' or h['trip_id'] == 'C' for h in run['holds'])
    first = run['holds'][0]
    assert first['hold_s'] == 60 and first['prob_after'] < first['prob_before']
    assert run['total_hold_min'] == pytest.approx(sum(h['hold_s'] for h in run['holds']) / 60, abs=0.05)


def test_hold_never_brings_the_bus_within_a_minute_of_the_bus_behind():
    t = T0
    rows = (rows_for('A', 'v1', t, [0, 200, 400, 500, 520, 540])
            + rows_for('B', 'v2', t + timedelta(minutes=10), [0] * 6)
            + rows_for('C', 'v3', t + timedelta(minutes=11, seconds=30), [0] * 6))     # only 90 s behind B
    items = bunching.score(bunching.build_features(rows, DAY), MODEL)
    run = bunching.simulate(items, MODEL, 'line', 180, 0.05, WINDOW)
    for h in run['holds']:
        if h['trip_id'] == 'B':
            assert h['hold_s'] <= 90 - bunching.SAFE_GAP_BEHIND_S


def test_recommendation_prefers_the_shortest_good_hold():
    runs = [{'hold_s': 0, 'bunched_passages': 20}, {'hold_s': 30, 'bunched_passages': 14},
            {'hold_s': 60, 'bunched_passages': 11}, {'hold_s': 90, 'bunched_passages': 10}]
    assert bunching.recommend(runs)['hold_s'] == 60      # 9 of the best 10 avoided
    assert bunching.recommend([{'hold_s': 0, 'bunched_passages': 5}, {'hold_s': 30, 'bunched_passages': 6}]) is None


def test_top_pairs_ranks_most_bunched_pairs_first():
    t = T0
    rows = rows_for('A', 'v1', t, [0] * 6) + rows_for('B', 'v2', t + timedelta(minutes=10), [-560] * 6)
    pairs = bunching.top_pairs(bunching.build_features(rows, DAY))
    assert pairs[0]['follower_vehicle'] == 'v2' and pairs[0]['leader_vehicle'] == 'v1' and pairs[0]['stops'] == 6


def test_scheduled_time_and_flat_stop_times():
    assert bunching.scheduled_time(DAY, '25:10:00') == datetime(2026, 9, 2, 1, 10, tzinfo=LISBON)
    assert bunching.scheduled_time(DAY, '01:10:00') == datetime(2026, 9, 2, 1, 10, tzinfo=LISBON)
    assert bunching.scheduled_time(DAY, 'bad') is None
    row = rows_for('F', 'v9', T0, [0, 0, 0], flat=True)[2]
    fix = {'flat': {'F'}, 'route': {('742_0', 'S3'): 240.0}, 'line': {}}
    assert bunching.planned_time(row, DAY, fix) == T0 + timedelta(minutes=4)
    assert bunching.planned_time(row, DAY, {'flat': {'F'}, 'route': {}, 'line': {}}) is None


class _Result:
    def __init__(self, rows): self.rows = rows
    def __iter__(self): return iter(self.rows)
    def fetchone(self): return self.rows[0] if self.rows else None
    def fetchall(self): return self.rows


class _Connection:
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def transaction(self): return self
    def execute(self, query, params=None):
        if 'FROM active_dataset' in query: return _Result([{'version_id': 1}])
        if 'HAVING count(*)' in query:
            return _Result([{'line': '742', 'direction_id': '0', 'trips': 12, 'headsign': 'Bairro Madre Deus',
                             'route_name': 'Ajuda - Bairro Madre Deus'},
                            {'line': '742', 'direction_id': '1', 'trips': 11, 'headsign': None,
                             'route_name': 'Ajuda - Bairro Madre Deus'},
                            {'line': '760', 'direction_id': '0', 'trips': 9, 'headsign': 'Gomes Freire',
                             'route_name': 'Cemitério da Ajuda - Gomes Freire'}])
        if 'WITH counts AS' in query:                  # planned stop list per line + direction
            return _Result([{'line': '742', 'direction_id': '0', 'stops': [f'S{n}' for n in range(1, 9)]},
                            {'line': '760', 'direction_id': '0', 'stops': ['S2', 'S3', 'S4', 'Z9']},
                            {'line': '742', 'direction_id': '1', 'stops': ['S8', 'Q1']}])
        if "table_name='stops'" in query: return _Result([{'stop_id': 'S1', 'stop_name': 'First stop'}])
        if 'array_agg(s.stop_id' in query:            # planned stops per trip
            return _Result([{'trip_id': t, 'stops': [f'S{n}' for n in range(1, 9)]} for t in 'ABC'])
        if 'SELECT id FROM plan_packages' in query and 'WITH' not in query: return _Result([{'id': 6}])
        if 'WITH pkg AS' in query: return _Result(sample_rows())
        if 'trip_headsign' in query: return _Result([{'line': '742', 'direction_id': '0', 'headsign': 'Madre Deus'}])
        return _Result([])


@pytest.fixture
def api(monkeypatch):
    import bunching_api
    monkeypatch.setattr(bunching_api, 'connect', lambda: _Connection())
    monkeypatch.setattr(bunching_api, '_route_stops_cache', {})
    models = {'line': MODEL, 'corridor': CORRIDOR_MODEL}
    monkeypatch.setattr(bunching_api.bunching, 'load_model',
                        lambda mode='line': {**models[mode], 'metrics': {}, 'target': 't', 'trained_at': 'now'})
    return bunching_api


def test_diagram_endpoint(api):
    value = api.diagram(DAY, '742', '0', None, '07:30', '09:30', hold=60, threshold=0.05)
    assert value['mode'] == 'line' and value['directionName'] == 'towards Madre Deus'
    assert [s['hold_s'] for s in value['scenarios']] == api.HOLD_OPTIONS
    assert value['stops'][0] == {'y': 0, 'stop_id': 'S1', 'name': 'First stop'}
    assert {t['vehicle_id'] for t in value['trips']} == {'v1', 'v2', 'v3'}
    assert value['selected']['hold_s'] == 60 and value['selected']['holds']
    assert value['scenarios'][0]['bunched_passages'] == value['summary']['bunchedPassages']


def test_diagram_with_several_lines_uses_the_corridor_model(api):
    value = api.diagram(DAY, '742', '0', ['760:0'], '07:30', '09:30', hold=60, threshold=0.05)
    assert value['mode'] == 'corridor' and [x['line'] for x in value['lines']] == ['742', '760']
    with pytest.raises(api.HTTPException):
        api.diagram(DAY, '742', '0', ['760'], '07:30', '09:30', hold=60, threshold=0.05)


def test_shared_lists_lines_on_the_same_route(api):
    value = api.shared(DAY, '742', '0', '07:00', '10:00')
    assert [(x['line'], x['sharedStops']) for x in value['shared']] == [('760', 3)]


def test_diagram_without_model_is_503(monkeypatch):
    import bunching_api
    monkeypatch.setattr(bunching_api.bunching, 'load_model', lambda mode='line': None)
    with pytest.raises(bunching_api.HTTPException) as info:
        bunching_api.diagram(DAY, '742', '0', None, '07:00', '10:00', 60, None)
    assert info.value.status_code == 503


def test_lines_endpoint_names_directions(api):
    value = api.lines(DAY, '07:00', '10:00')
    line = value['lines'][0]
    assert line['name'] == 'Ajuda - Bairro Madre Deus'
    assert [d['name'] for d in line['directions']] == ['towards Bairro Madre Deus', 'direction 1']
