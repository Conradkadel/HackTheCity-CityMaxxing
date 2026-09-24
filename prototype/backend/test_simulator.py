from datetime import timedelta

import pytest

import bunching
import simulator as S
from test_bunching import DAY, T0, rows_for

PAIRS = {('742', '0')}
TRIP_STOPS = {t: [f'S{n}' for n in range(1, 9)] for t in 'ABCDE'}


def setup(rows):
    items = bunching.build_features(rows, DAY, 'line', TRIP_STOPS)
    return S.build_trips(items, TRIP_STOPS, PAIRS), S.build_bank(items)


def window():
    return (T0 - timedelta(hours=1)).timestamp(), (T0 + timedelta(hours=2)).timestamp()


def sample():
    return (rows_for('A', 'v1', T0, [0, 60, 120, 180, 240, 300, 360, 420])       # leader gets later
            + rows_for('B', 'v2', T0 + timedelta(minutes=10), [-200] * 8)        # follower left 200 s early
            + rows_for('C', 'v3', T0 + timedelta(minutes=20), [0] * 8))


def test_replay_with_no_change_reproduces_the_day_exactly():
    trips, bank = setup(sample())
    result = S.run(trips, bank, S.SCENARIO_BY_CODE['AS'], seed=0, k=0.01)
    real = S.observed(trips)
    for i, passages in real['history'].items():
        assert [p['t'] for p in result['history'][i]] == pytest.approx([p['t'] for p in passages])
    assert S.kpis(trips, result, window()) == S.kpis(trips, real, window())


def test_seeds_do_not_change_buses_that_stay_on_their_real_time():
    trips, bank = setup(sample())
    assert S.kpis(trips, S.run(trips, bank, S.SCENARIO_BY_CODE['AS'], seed=7), window()) == \
        S.kpis(trips, S.observed(trips), window())


def test_headway_dispatch_waits_until_the_gap_is_90_percent_of_plan():
    trips, bank = setup(sample())
    result = S.run(trips, bank, S.SCENARIO_BY_CODE['D2'], seed=0, k=0)
    b = next(i for i, t in enumerate(trips) if t.key[0] == 'B')
    # B left 400 s after A although planned 600 s: wait 0.9 x 600 - 400 = 140 s (< 3 min)
    assert result['dispatch_wait'][b] == pytest.approx(140)
    assert result['history'][b][0]['t'] == pytest.approx(trips[b].stops[0]['t_obs'] + 140)


def test_a_trip_never_starts_before_its_vehicle_is_back():
    rows = sample() + rows_for('D', 'v1', T0 + timedelta(minutes=23), [0] * 8)   # v1 again, after trip A
    trips, bank = setup(rows)
    d = next(i for i, t in enumerate(trips) if t.key[0] == 'D')
    a = trips[d].prev
    assert trips[a].key[0] == 'A'
    for code in ('D1', 'D2', 'T2-4'):
        result = S.run(trips, bank, S.SCENARIO_BY_CODE[code], seed=0, k=0)
        end_a = result['history'][a][-1]['t']
        start_d = result['history'][d][0]['t']
        buffer = S.SCENARIO_BY_CODE[code].buffer_s
        assert start_d >= end_a + trips[d].layover_s - buffer - 1e-6


def test_control_hold_is_capped_and_counted():
    trips, bank = setup(sample())
    result = S.run(trips, bank, S.SCENARIO_BY_CODE['H1-60'], seed=0, k=0)
    assert result['holds'] and all(h['seconds'] <= 60 for h in result['holds'])
    assert S.kpis(trips, result, window())['hold_s_per_trip'] > 0


def test_shifted_bus_keeps_its_own_run_time():
    trips, bank = setup(sample())
    stop = trips[0].stops[0]
    assert S.shifted_run(bank, 'S1', 'S2', 1000.0, 1010.0, 77.0, noise=0.05) == 77.0      # < 30 s: unchanged
    assert S.shifted_run(bank, 'S1', 'S2', 1000.0, 1300.0, 77.0, noise=0.05) == pytest.approx(77 * 1.05)
    assert stop['observed']


def test_turnaround_buffer_needs_extra_buses():
    trips, _ = setup(sample())
    assert S.extra_vehicles(trips, S.SCENARIO_BY_CODE['T2-4'], PAIRS) >= 1
    assert S.extra_vehicles(trips, S.SCENARIO_BY_CODE['D2'], PAIRS) == 0
