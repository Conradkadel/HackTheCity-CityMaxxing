"""Experiments to see whether the bunching early-warning model can be improved.

Does NOT touch the production models (models/bunching_model*.json). It writes a report to
models/experiments/report_<mode>.json and prints a comparison table.

    cd code/prototype
    python3 -m venv .venv && .venv/bin/pip install -r backend/requirements-model.txt
    export DATABASE_URL=postgresql://headway:<password>@127.0.0.1:5433/headway
    .venv/bin/python backend/experiment_bunching_model.py            # line model (default)
    .venv/bin/python backend/experiment_bunching_model.py --mode corridor

The first run reads the database (~3-5 min) and caches the features in
models/experiments/cache_<mode>.pkl; later runs take ~1-2 min. Use --refresh to rebuild the cache.

Same data, same day split (train Mon-Thu + Sat, test Fri + Sun) as train_bunching_model.py, so the
numbers are directly comparable. What is compared:

  A  logistic regression, current features                 (= the production model)
  B  logistic regression, current + new features
  C  gradient-boosted trees (HistGradientBoosting), current features
  D  gradient-boosted trees, current + new features

New features (all known at the moment the bus passes the stop, so no leakage):
  leader_log_ratio   gap of the bus in front to ITS leader (is the bus in front itself squeezed?)
  leader_trend       how that gap changed over the last stops
  hour_sin/hour_cos  time of day as a smooth cycle instead of 3 peak flags
  stop_rate          how often bunching starts after this stop  (learned on training days only)
  line_rate          how often bunching starts on this line     (learned on training days only)

Plus a learning curve (train on 1..5 days) to answer "do we need more data?".
"""
import argparse
import json
import math
import pickle
import time
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score

from bunching import (FEATURES_BY_MODE, LISBON, build_features, feature_vector, fetch_passages,
                      fetch_schedule_fix, fetch_trip_stops, scoreable, stop_key)
from db import active_version, connect
from train_bunching_model import BASELINE, split_days

OUT_DIR = Path(__file__).parent / 'models' / 'experiments'
NEW_NUMERIC = ['leader_log_ratio', 'leader_trend', 'hour_sin', 'hour_cos']
SMOOTH = 200          # target-encoding smoothing: a stop needs ~200 passages before its own rate counts


# ---------------------------------------------------------------- data
def day_rows(rows, day, mode, trip_stops, fix):
    items = build_features(rows, day, mode, trip_stops, fix, stats={})
    # the bus in front at the same stop = previous passage in the stop group (as in build_features)
    by_stop = {}
    for p in items:
        by_stop.setdefault(stop_key(p, mode), []).append(p)
    for group in by_stop.values():
        group.sort(key=lambda p: p['t'])
        for prev, p in zip([None] + group[:-1], group):
            p['_leader'] = prev
    base, extra, lines, stops, y, gap = [], [], [], [], [], []
    feats = FEATURES_BY_MODE[mode]
    for p in items:
        if not scoreable(p, mode) or p['label'] is None:
            continue
        fv = feature_vector(p)
        lead = p.get('_leader')
        lr = lead.get('ratio') if lead else None
        lrp = lead.get('ratio_prev') if lead else None
        leader_log_ratio = math.log(min(max(lr, 0.05), 3.0)) if lr is not None else 0.0
        leader_trend = min(max(lr - lrp, -3.0), 3.0) if lr is not None and lrp is not None else 0.0
        local = p['t'].astimezone(LISBON)
        h = local.hour + local.minute / 60
        base.append([fv[f] for f in feats])
        extra.append([leader_log_ratio, leader_trend, math.sin(2 * math.pi * h / 24), math.cos(2 * math.pi * h / 24)])
        lines.append(f"{p['line']}|{p['direction_id']}")
        stops.append(f"{p['line']}|{p['direction_id']}|{p['stop_id']}")
        y.append(int(p['label']))
        gap.append(p[BASELINE[mode]['value']])
    return {'base': np.array(base, float).reshape(-1, len(feats)), 'extra': np.array(extra, float).reshape(-1, 4),
            'line': np.array(lines), 'stop': np.array(stops), 'y': np.array(y, int), 'gap': np.array(gap, float)}


def load(mode, agency, refresh):
    cache = OUT_DIR / f'cache_{mode}.pkl'
    if cache.exists() and not refresh:
        print(f'using cached features {cache}')
        return pickle.loads(cache.read_bytes())
    parts = {}
    with connect() as conn:
        version = active_version(conn)
        if version is None:
            raise SystemExit('No active dataset. Restore or import the database first.')
        days = [r['operational_date'] for r in conn.execute(
            'SELECT DISTINCT operational_date FROM vehicle_events WHERE version_id=%s AND agency_id=%s ORDER BY 1',
            (version, agency))]
        for day in days:
            t0 = time.time()
            rows = fetch_passages(conn, version, day, agency)
            trip_stops = fetch_trip_stops(conn, day, agency, {r['trip_id'] for r in rows})
            fix = fetch_schedule_fix(conn, day, agency)
            parts[day] = day_rows(rows, day, mode, trip_stops, fix)
            print(f"{day}: {len(parts[day]['y']):,} rows, {parts[day]['y'].mean():.2%} positive ({time.time() - t0:.0f}s)")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(pickle.dumps(parts))
    return parts


def stack(parts, days, key):
    return np.concatenate([parts[d][key] for d in days])


def target_encode(train_keys, train_y, keys):
    """Smoothed positive rate per key, learned on training rows only."""
    prior = train_y.mean()
    sums, counts = {}, {}
    for k, v in zip(train_keys, train_y):
        sums[k] = sums.get(k, 0) + v
        counts[k] = counts.get(k, 0) + 1
    enc = {k: (sums[k] + SMOOTH * prior) / (counts[k] + SMOOTH) for k in sums}
    return np.array([enc.get(k, prior) for k in keys])


def matrices(parts, train_days, test_days, extended):
    x_tr, x_te = stack(parts, train_days, 'base'), stack(parts, test_days, 'base')
    if not extended:
        return x_tr, x_te
    y_tr = stack(parts, train_days, 'y')
    # target encoding for TRAIN rows: out-of-day (each training day encoded from the other days)
    # so the model cannot memorise its own labels; TEST rows: encoded from all training days.
    enc_tr = []
    for d in train_days:
        others = [o for o in train_days if o != d]
        oy = stack(parts, others, 'y')
        enc_tr.append(np.column_stack([target_encode(stack(parts, others, 'stop'), oy, parts[d]['stop']),
                                       target_encode(stack(parts, others, 'line'), oy, parts[d]['line'])]))
    enc_tr = np.concatenate(enc_tr)
    enc_te = np.column_stack([target_encode(stack(parts, train_days, 'stop'), y_tr, stack(parts, test_days, 'stop')),
                              target_encode(stack(parts, train_days, 'line'), y_tr, stack(parts, test_days, 'line'))])
    logit = lambda r: np.log(np.clip(r, 1e-4, 1 - 1e-4) / (1 - np.clip(r, 1e-4, 1 - 1e-4)))  # noqa: E731
    x_tr = np.column_stack([x_tr, stack(parts, train_days, 'extra'), logit(enc_tr)])
    x_te = np.column_stack([x_te, stack(parts, test_days, 'extra'), logit(enc_te)])
    return x_tr, x_te


# ---------------------------------------------------------------- models
def fit_predict(kind, x_tr, y_tr, x_te):
    if kind == 'logreg':
        mu, sd = x_tr.mean(0), x_tr.std(0)
        sd[sd == 0] = 1
        m = LogisticRegression(max_iter=3000).fit((x_tr - mu) / sd, y_tr)
        return m.predict_proba((x_te - mu) / sd)[:, 1]
    m = HistGradientBoostingClassifier(max_iter=400, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=200,
                                       l2_regularization=1.0, early_stopping=True, validation_fraction=0.1,
                                       random_state=0)
    return m.fit(x_tr, y_tr).predict_proba(x_te)[:, 1]


def evaluate(y, p, test_day_idx):
    prec, rec, _ = precision_recall_curve(y, p)
    at_recall = lambda r: float(prec[rec >= r].max()) if (rec >= r).any() else 0.0  # noqa: E731
    top = p >= np.quantile(p, 0.99)                       # budget: 1 alert per 100 passages
    return {'roc_auc': round(roc_auc_score(y, p), 4), 'avg_precision': round(average_precision_score(y, p), 4),
            'lift_over_base_rate': round(average_precision_score(y, p) / y.mean(), 2),
            'precision_at_recall_28': round(at_recall(0.28), 4),
            'precision_at_recall_50': round(at_recall(0.50), 4),
            'budget_1_per_100': {'precision': round(float(y[top].mean()), 4),
                                 'recall': round(float(y[top].sum() / y.sum()), 4)},
            'avg_precision_per_test_day': {d: round(average_precision_score(y[i], p[i]), 4)
                                           for d, i in test_day_idx.items() if y[i].sum()}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', choices=['line', 'corridor'], default='line')
    ap.add_argument('--agency', default='IA9T6')
    ap.add_argument('--refresh', action='store_true', help='rebuild the feature cache from the database')
    ap.add_argument('--skip-curve', action='store_true', help='skip the learning curve')
    args = ap.parse_args()

    parts = load(args.mode, args.agency, args.refresh)
    days = sorted(parts)
    train_days, test_days = split_days(days)
    y_tr, y_te = stack(parts, train_days, 'y'), stack(parts, test_days, 'y')
    offsets = np.cumsum([0] + [len(parts[d]['y']) for d in test_days])
    test_idx = {d.isoformat(): np.arange(offsets[i], offsets[i + 1]) for i, d in enumerate(test_days)}
    print(f'\ntrain {[d.isoformat() for d in train_days]}  ({len(y_tr):,} rows, {y_tr.mean():.2%} positive)')
    print(f'test  {[d.isoformat() for d in test_days]}  ({len(y_te):,} rows, {y_te.mean():.2%} positive)\n')

    results = {'baseline_rule': evaluate(y_te, -stack(parts, test_days, 'gap'), test_idx)}
    for name, kind, extended in [('A logreg (production)', 'logreg', False), ('B logreg + new features', 'logreg', True),
                                 ('C boosted trees', 'hgb', False), ('D boosted trees + new features', 'hgb', True)]:
        t0 = time.time()
        x_tr, x_te = matrices(parts, train_days, test_days, extended)
        results[name] = evaluate(y_te, fit_predict(kind, x_tr, y_tr, x_te), test_idx)
        print(f'{name:32} done in {time.time() - t0:.0f}s')

    print(f"\n{'model':32} {'AUC':>6} {'AP':>6} {'lift':>5} {'P@R28':>6} {'P@R50':>6} {'P@1/100':>8} {'R@1/100':>8}")
    for name, r in results.items():
        b = r['budget_1_per_100']
        print(f"{name:32} {r['roc_auc']:6.3f} {r['avg_precision']:6.3f} {r['lift_over_base_rate']:5.1f} "
              f"{r['precision_at_recall_28']:6.3f} {r['precision_at_recall_50']:6.3f} {b['precision']:8.3f} {b['recall']:8.3f}")

    curve = []
    if not args.skip_curve:
        print('\nlearning curve (does more data help?) - trained on the first N training days, same test days')
        for n in range(1, len(train_days) + 1):
            sub = train_days[:n]
            row = {'train_days': n, 'train_rows': int(sum(len(parts[d]['y']) for d in sub))}
            for kind in ('logreg', 'hgb'):
                x_tr, x_te = matrices(parts, sub, test_days, extended=(kind == 'hgb' and n > 1))
                row[kind] = round(average_precision_score(y_te, fit_predict(kind, x_tr, stack(parts, sub, 'y'), x_te)), 4)
            curve.append(row)
            print(f"  {n} day(s), {row['train_rows']:>9,} rows:  AP logreg {row['logreg']:.3f}   AP boosted trees {row['hgb']:.3f}")
        print('  flat curve  -> more days of the same data will not help much; better features/labels will')
        print('  rising curve -> more data will help')

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f'report_{args.mode}.json'
    out.write_text(json.dumps({'mode': args.mode, 'train_days': [d.isoformat() for d in train_days],
                               'test_days': [d.isoformat() for d in test_days], 'base_rate_test': round(float(y_te.mean()), 4),
                               'results': results, 'learning_curve': curve}, indent=2), encoding='utf-8')
    print(f'\nreport saved to {out}')


if __name__ == '__main__':
    main()
