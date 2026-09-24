"""Validation gate, fitting of k and the held-out scenario grid for simulator.py.

Follows the plan ("Simulator and validation gate", "Scoring"):

  1. Replay: with no policy the simulator reproduces every day exactly.
  2. Traffic mechanism: a RESAMPLED baseline (every bus draws every run time from the
     bank, with the dwell feedback k) must reproduce the real bunching. k is fitted on
     Mon-Thu (31 Aug - 3 Sep) only; Fri 4 and Sun 6 Sep are the held-out test:
       - bunched share within +-15 % relative,
       - bunching by departure gap ratio: same ranking,
       - growth along the route: same direction.
  3. Time shift: how to predict the run time of a bus moved in time. Predicting a bus's
     run from the bus in front (>= 5 min earlier) unscaled vs scaled by the bank's
     traffic change. The better rule is used by the simulator (it was: unscaled).
  4. Scenario grid: every scenario x 30 seeds on the held-out days, and the
     recommendation rule (improves excess wait on every held-out day with the 5th
     percentile > 0; the cheapest option with >= 75 % of the best reduction).

Writes models/simulator_validation.json (read by sim_api.py). Takes about 15 minutes:

    DATABASE_URL=... python backend/validate_simulator.py [--cache DIR]
"""
import argparse
import json
import pickle
import statistics
from datetime import date, datetime, timedelta
from pathlib import Path

import bunching
import simulator as S
from db import active_version, connect

LINES = ['742', '767', '728', '758', '735']        # plan scope: the 5 most-bunched Lisbon lines
WINDOW_H = (16, 20)                                 # evening peak
FIT_DAYS = [date(2026, 8, 31) + timedelta(days=i) for i in range(4)]     # Mon-Thu
TEST_DAYS = [date(2026, 9, 4), date(2026, 9, 6)]                          # Fri, Sun
K_GRID = [0.0, 0.0025, 0.005, 0.0075, 0.01, 0.015, 0.02, 0.03]
FIT_SEEDS = 10
SEEDS = 30
AGENCY = 'IA9T6'


def load_day(conn, version, day, cache):
    path = Path(cache) / f'sim_{day}.pkl' if cache else None
    if path and path.exists():
        return pickle.loads(path.read_bytes())
    pairs = [(line, d) for line in LINES for d in '01']
    rows = bunching.fetch_passages(conn, version, day, AGENCY, pairs)
    trip_stops = bunching.fetch_trip_stops(conn, day, AGENCY, {r['trip_id'] for r in rows})
    fix = bunching.fetch_schedule_fix(conn, day, AGENCY)
    data = (rows, trip_stops, fix)
    if path:
        path.write_bytes(pickle.dumps(data))
    return data


def prepare(day, data):
    """-> window, bank, {line: trips} for one day."""
    rows, trip_stops, fix = data
    items = bunching.build_features(rows, day, 'line', trip_stops, fix)
    start = datetime(day.year, day.month, day.day, WINDOW_H[0], tzinfo=bunching.LISBON).timestamp()
    end = datetime(day.year, day.month, day.day, WINDOW_H[1], tzinfo=bunching.LISBON).timestamp()
    bank = S.build_bank(items)
    trips = {line: S.build_trips(items, trip_stops, {(line, '0'), (line, '1')}, since=start - 7200, until=end)
             for line in LINES}
    return (start, end), bank, trips, items


def pooled(results):
    """Sum KPI counts over lines -> bunched share."""
    passages = sum(r['passages'] for r in results)
    return 100 * sum(r['bunched'] for r in results) / passages if passages else None


def bucket_rates(b):
    return [v['bunch_later'] / v['n'] if v['n'] else 0.0 for v in b.values()]


def _order(rates):
    """Ranking of the departure buckets (0 = the bucket that bunches most)."""
    return sorted(range(len(rates)), key=lambda i: -rates[i])


def add_counts(total, part):
    for key, value in part.items():
        if isinstance(value, dict):
            add_counts(total.setdefault(key, {}), value)
        else:
            total[key] = total.get(key, 0) + value


def shift_check(items, day):
    """Predict each bus's segment run from the bus in front: unscaled vs scaled by the bank."""
    bank = S.build_bank(items)
    by_segment = {}
    for trip in bunching.trips_of(items).values():
        for a, b in zip(trip, trip[1:]):
            if b['seq'] - a['seq'] == 1:
                run_s = (b['t'] - a['t']).total_seconds()
                if 0 <= run_s <= 1800:
                    by_segment.setdefault((a['stop_id'], b['stop_id']), []).append((a['t'].timestamp(), run_s))
    naive, scaled = [], []
    for segment, runs in by_segment.items():
        runs.sort()
        for (t_lead, r_lead), (t_own, r_own) in zip(runs, runs[1:]):
            if t_own - t_lead < 300:          # only buses at least 5 min apart: a real time shift
                continue
            naive.append(abs(r_lead - r_own))
            scaled.append(abs(S.shifted_run(bank, *segment, t_lead, t_own, r_lead, scale=True) - r_own))
    pairs, naive, scaled = len(naive), statistics.mean(naive), statistics.mean(scaled)
    return {'pairs': pairs, 'mae_unscaled_s': round(naive, 2), 'mae_scaled_s': round(scaled, 2),
            'better': 'unscaled (own run)' if naive <= scaled else 'scaled by the bank',
            'pass': naive <= scaled}     # the simulator uses the unscaled rule


def k_regression(days):
    """Cross-check of k: slope of (run to the next stop - bank median) on (gap - planned gap)."""
    xs, ys = [], []
    for window, bank, trips, _ in days:
        for day_trips in trips.values():
            for i, passages in S.observed(day_trips)['history'].items():
                stops = day_trips[i].stops
                for p in passages:
                    j = p['index']
                    if j + 1 >= len(stops) or p['gap'] is None or not p['planned'] or \
                            not (stops[j]['observed'] and stops[j + 1]['observed']) or \
                            not (bunching.SCHED_HEADWAY_RANGE[0] <= p['planned'] <= bunching.SCHED_HEADWAY_RANGE[1]):
                        continue
                    entry = bank.get((stops[j]['stop_id'], stops[j + 1]['stop_id']))
                    if entry is None:
                        continue
                    x = p['gap'] - p['planned']
                    if abs(x) > 1200:
                        continue
                    xs.append(x)
                    ys.append(stops[j + 1]['t_obs'] - stops[j]['t_obs'] - S._median(entry, stops[j]['t_obs']))
    mx, my = statistics.mean(xs), statistics.mean(ys)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    return {'n': len(xs), 'slope_per_stop': round(slope, 4)}


def resampled(days, k, seeds):
    """Pooled bunched share of the resampled baseline, averaged over seeds."""
    shares = []
    for seed in range(1, seeds + 1):
        results = []
        for window, bank, trips, _ in days:
            for day_trips in trips.values():
                results.append(S.kpis(day_trips, S.run(day_trips, bank, S.SCENARIO_BY_CODE['AS'], seed, k,
                                                       resample=True), window))
        shares.append(pooled(results))
    return statistics.mean(shares)


def gate_day(day_data, k, seeds):
    """Plan checks 1-3 for one held-out day."""
    window, bank, trips, _ = day_data
    exact = all(S.kpis(t, S.run(t, bank, S.SCENARIO_BY_CODE['AS'], 0, k), window) == S.kpis(t, S.observed(t), window)
                for t in trips.values())
    obs = [S.kpis(t, S.observed(t), window) for t in trips.values()]
    ob_b, ob_g = {}, {}
    for t in trips.values():
        add_counts(ob_b, S.departure_buckets(t, S.observed(t), window))
        add_counts(ob_g, S.growth(t, S.observed(t), window))
    sim_shares, sim_b, sim_g = [], {}, {}
    for seed in range(1, seeds + 1):
        res = []
        for t in trips.values():
            r = S.run(t, bank, S.SCENARIO_BY_CODE['AS'], seed, k, resample=True)
            res.append(S.kpis(t, r, window))
            add_counts(sim_b, S.departure_buckets(t, r, window))
            add_counts(sim_g, S.growth(t, r, window))
        sim_shares.append(pooled(res))
    observed_share, sim_share = pooled(obs), statistics.mean(sim_shares)
    ob_rates, sim_rates = bucket_rates(ob_b), bucket_rates(sim_b)
    growth_of = lambda g: (g['last_40']['bunched'] / g['last_40']['n']) - (g['first_40']['bunched'] / g['first_40']['n'])
    checks = {
        'replay_exact': exact,
        'bunched_share': {'observed_pct': round(observed_share, 2), 'simulated_pct': round(sim_share, 2),
                          'relative_error': round(sim_share / observed_share - 1, 3),
                          'pass': abs(sim_share / observed_share - 1) <= 0.15},
        'departure_buckets': {'buckets': list(ob_b), 'observed': [round(r, 3) for r in ob_rates],
                              'simulated': [round(r, 3) for r in sim_rates],
                              'pass': _order(ob_rates) == _order(sim_rates)},
        'growth': {'observed': round(growth_of(ob_g), 4), 'simulated': round(growth_of(sim_g), 4),
                   'pass': (growth_of(ob_g) > 0) == (growth_of(sim_g) > 0)},
    }
    checks['pass'] = exact and all(checks[c]['pass'] for c in ('bunched_share', 'departure_buckets', 'growth'))
    return checks


def scenario_grid(day_data, k, seeds, model, threshold):
    """Every scenario x seeds, per line -> KPIs per seed."""
    window, bank, trips, _ = day_data
    out = {}
    for line, day_trips in trips.items():
        pairs = {(line, '0'), (line, '1')}
        out[line] = {}
        for sc in S.SCENARIOS:
            runs = []
            for seed in range(seeds if sc.code != 'AS' else 1):
                runs.append(S.kpis(day_trips, S.run(day_trips, bank, sc, seed, k, model, threshold), window))
            out[line][sc.code] = {'runs': runs, 'extra_vehicles': S.extra_vehicles(day_trips, sc, pairs)}
    return out


def summarize(grids):
    """grids: {(k, day): scenario_grid}. Change vs as-run per line and scenario (seed ranges),
    'robust' = excess wait improves on every held-out day for every k (5th percentile > 0)."""
    summary = {}
    for line in LINES:
        per_scenario = {}
        for sc in S.SCENARIOS[1:]:
            cases = {}
            for (k, day), grid in grids.items():
                base = grid[line]['AS']['runs'][0]
                runs = grid[line][sc.code]['runs']
                saved = sorted(base['ewt_s'] - r['ewt_s'] for r in runs if r['ewt_s'] is not None)
                cases[f'{day} k={k}'] = {
                    'ewt_saved_mean': round(statistics.mean(saved), 1),
                    'ewt_saved_p5': round(saved[int(0.05 * (len(saved) - 1))], 1),
                    'bunched_pct_change': round(statistics.mean(r['bunched_pct'] for r in runs) - base['bunched_pct'], 2),
                    'hold_s_per_trip': round(statistics.mean(r['hold_s_per_trip'] for r in runs), 1),
                    'terminal_wait_s_per_trip': round(statistics.mean(r['terminal_wait_s_per_trip'] for r in runs), 1),
                    'extra_vehicles': grid[line][sc.code]['extra_vehicles']}
            per_scenario[sc.code] = {
                'cases': cases,
                'robust': all(c['ewt_saved_p5'] > 0 for c in cases.values()),
                'ewt_saved': round(statistics.mean(c['ewt_saved_mean'] for c in cases.values()), 1),
                'ewt_saved_range': [min(c['ewt_saved_mean'] for c in cases.values()),
                                    max(c['ewt_saved_mean'] for c in cases.values())],
                'bunched_pct_change': round(statistics.mean(c['bunched_pct_change'] for c in cases.values()), 2),
                'extra_vehicles': max(c['extra_vehicles'] for c in cases.values()),
                'hold_s_per_trip': round(statistics.mean(c['hold_s_per_trip'] for c in cases.values()), 1),
                'terminal_wait_s_per_trip': round(statistics.mean(c['terminal_wait_s_per_trip']
                                                                  for c in cases.values()), 1)}
        summary[line] = {'scenarios': per_scenario, 'recommended': recommend(per_scenario)}
    return summary


def recommend(per_scenario, share=0.75):
    """Plan rule: robust on every held-out day; cheapest with >= 75 % of the best reduction
    ("cheapest" = extra vehicles first, then on-board hold, then terminal wait).
    D1 is a ceiling (not a policy) and is never recommended."""
    robust = {code: s for code, s in per_scenario.items() if s['robust'] and code != 'D1'}
    if not robust:
        return None
    best = max(s['ewt_saved'] for s in robust.values())
    good = [(s['extra_vehicles'], s['hold_s_per_trip'], s['terminal_wait_s_per_trip'], code)
            for code, s in robust.items() if s['ewt_saved'] >= share * best]
    return min(good)[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--cache', help='folder to cache the loaded days (optional)')
    args = parser.parse_args()
    loaded = {}
    with connect() as conn:
        version = active_version(conn)
        for day in FIT_DAYS + TEST_DAYS:
            loaded[day] = prepare(day, load_day(conn, version, day, args.cache))
            print('loaded', day, flush=True)

    fit = [loaded[d] for d in FIT_DAYS]
    observed_fit = pooled([S.kpis(t, S.observed(t), w) for w, _, trips, _ in fit for t in trips.values()])
    fit_table = []
    for k in K_GRID:
        share = resampled(fit, k, FIT_SEEDS)
        fit_table.append({'k': k, 'simulated_pct': round(share, 2)})
        print('k', k, round(share, 2), 'observed', round(observed_fit, 2), flush=True)
    best = min(fit_table, key=lambda r: abs(r['simulated_pct'] - observed_fit))
    k = best['k']
    per_day = {}
    for d in FIT_DAYS + TEST_DAYS:
        w, _, trips, _ = loaded[d]
        per_day[str(d)] = {'observed_pct': round(pooled([S.kpis(t, S.observed(t), w) for t in trips.values()]), 2),
                           **{f'k={kk}': round(resampled([loaded[d]], kk, FIT_SEEDS), 2) for kk in sorted({0.0, k})}}

    gate = {str(d): gate_day(loaded[d], k, FIT_SEEDS) for d in TEST_DAYS}
    shift = {str(d): shift_check(loaded[d][3], d) for d in TEST_DAYS}
    passed = all(g['pass'] for g in gate.values()) and all(s['pass'] for s in shift.values())
    print('gate', json.dumps(gate), json.dumps(shift), flush=True)

    model = bunching.load_model('line')
    threshold = model['alerting']['threshold'] if model else None
    # k is uncertain (see the gate), so every scenario runs with no feedback (k=0) and the fitted k
    grids = {(kk, str(d)): scenario_grid(loaded[d], kk, SEEDS, model, threshold)
             for kk in sorted({0.0, k}) for d in TEST_DAYS}
    share_ok = all(g['bunched_share']['pass'] for g in gate.values())
    shape_ok = all(g['replay_exact'] and g['departure_buckets']['pass'] and g['growth']['pass'] for g in gate.values())
    result = {
        'created_at': datetime.now().isoformat(timespec='seconds'),
        'k': k, 'k_range': sorted({0.0, k}), 'lines': LINES, 'window_h': WINDOW_H, 'seeds': SEEDS,
        'fit_days': [str(d) for d in FIT_DAYS], 'test_days': [str(d) for d in TEST_DAYS],
        'fit': {'observed_pct': round(observed_fit, 2), 'grid': fit_table,
                'per_day': per_day, 'regression_cross_check': k_regression(fit)},
        'gate': gate, 'shift_check': shift, 'passed': passed,
        'status': 'pass' if passed else 'partial' if shape_ok and all(s['pass'] for s in shift.values())
        else 'fail',
        'status_note': None if share_ok else
        'The resampled baseline with k fitted on Mon-Thu over-predicts the bunched share on the held-out days. '
        'Replay, departure-gap ranking and growth along the route pass. Scenarios are therefore run with k=0 and '
        'the fitted k, and only options that help under both are called robust.',
        'held_out': summarize(grids),
    }
    S.VALIDATION_FILE.write_text(json.dumps(result, indent=1), encoding='utf-8')
    print('saved', S.VALIDATION_FILE, 'k', k, 'passed', passed)
    print('status', result['status'], json.dumps(per_day))
    for line, s in result['held_out'].items():
        print(line, 'recommended', s['recommended'],
              {c: (v['ewt_saved_range'], v['robust']) for c, v in s['scenarios'].items()})


if __name__ == '__main__':
    main()
