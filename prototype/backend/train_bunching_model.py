"""Train the bus-bunching models and write them to backend/models/.

    pip install -r backend/requirements-model.txt
    DATABASE_URL=postgresql://headway:<password>@127.0.0.1:5432/headway python backend/train_bunching_model.py

(or inside Compose:  docker compose run --rm -v "$PWD/backend/models:/app/models" api \
   sh -c "pip install -r requirements-model.txt && python train_bunching_model.py")

Two models are trained (see bunching.py for the definitions):
  line      -> models/bunching_model.json            bus in front = same line
  corridor  -> models/bunching_model_corridor.json   bus in front = any line at the same stop

For each model
  * builds stop passages + features for every operational date (bunching.py)
  * keeps passages that are valid and NOT bunched yet (we predict the onset); for the
    corridor model only pairs whose bus in front stays on the same route (shared_next >= 0.6)
  * label = bunched at any of the next 5 stops
  * splits BY DAY: the last weekday and the last weekend day are the test set,
    all other days train the model (a random split would leak: neighbouring
    stops of the same bus pair are almost identical)
  * logistic regression on standardised features
  * reports test ROC-AUC / average precision against the simple baseline
    "the smaller the current gap, the higher the risk"
  * picks the ALERT LEVEL (probability that triggers an alert) on the training days
    with leave-one-day-out predictions and the best F1, and compares it with the
    best simple rule "alert when the gap is below X"
"""
import argparse
import json
from datetime import datetime, timezone

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score

from bunching import (FEATURES_BY_MODE, HORIZON_BY_MODE, MODEL_FILES, TARGETS, build_features, feature_vector,
                      fetch_passages, fetch_schedule_fix, fetch_trip_stops, scoreable)
from db import active_version, connect

PROB_GRID = [round(0.05 * i, 2) for i in range(1, 19)]      # alert at 5 % .. 90 % risk
# simple rule "alert when the gap is below X": X as share of plan (line) or in seconds (corridor)
BASELINE = {
    'line': {'grid': [round(0.05 * i, 2) for i in range(6, 21)], 'value': 'ratio',
             'text': lambda x: f'alert when the gap is below {x:.0%} of the planned gap'},
    'corridor': {'grid': list(range(90, 601, 30)), 'value': 'hw',
                 'text': lambda x: f'alert when the bus in front is less than {x} s ahead'},
}


def split_days(days):
    """Test = last weekday + last weekend day; train = everything else."""
    weekdays = [d for d in days if d.weekday() < 5]
    weekends = [d for d in days if d.weekday() >= 5]
    test = {d for d in (weekdays[-1:] + weekends[-1:])}
    if len(test) == len(days):
        raise SystemExit('Need at least one more day of data than test days.')
    return [d for d in days if d not in test], sorted(test)


def fit(x, y):
    mean, std = x.mean(axis=0), x.std(axis=0)
    std[std == 0] = 1.0
    return LogisticRegression(max_iter=2000).fit((x - mean) / std, y), mean, std


def predict(model, mean, std, x):
    return model.predict_proba((x - mean) / std)[:, 1]


def alert_quality(y, alert):
    """precision = share of alerts that were right; recall = share of bunching that got an alert."""
    tp = int((alert & (y == 1)).sum()); n_alert = int(alert.sum()); n_pos = int(y.sum())
    precision = tp / n_alert if n_alert else 0.0
    recall = tp / n_pos if n_pos else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {'precision': round(precision, 4), 'recall': round(recall, 4), 'f1': round(f1, 4),
            'alerts_per_100': round(100 * n_alert / len(y), 3)}


def dataset(rows, day, mode, trip_stops, fix, stats):
    """-> features x, label y, and the current gap (for the simple baseline rule)."""
    features = FEATURES_BY_MODE[mode]
    items = [p for p in build_features(rows, day, mode, trip_stops, fix, stats=stats) if scoreable(p, mode) and p['label'] is not None]
    x = np.array([[feature_vector(p)[f] for f in features] for p in items], dtype=float).reshape(-1, len(features))
    y = np.array([p['label'] for p in items], dtype=int)
    gap = np.array([p[BASELINE[mode]['value']] for p in items], dtype=float)
    return x, y, gap


def train(mode, parts, train_days, test_days, agency, data_stats):
    features = FEATURES_BY_MODE[mode]
    stack = lambda days, i: np.concatenate([parts[d][i] for d in days])  # noqa: E731
    x_train, y_train = stack(train_days, 0), stack(train_days, 1)
    x_test, y_test, gap_test = stack(test_days, 0), stack(test_days, 1), stack(test_days, 2)
    model, mean, std = fit(x_train, y_train)
    p_test = predict(model, mean, std, x_test)
    metrics = {
        'roc_auc': round(float(roc_auc_score(y_test, p_test)), 4),
        'average_precision': round(float(average_precision_score(y_test, p_test)), 4),
        'baseline_roc_auc': round(float(roc_auc_score(y_test, -gap_test)), 4),
        'baseline_average_precision': round(float(average_precision_score(y_test, -gap_test)), 4),
        'test_positive_rate': round(float(y_test.mean()), 4),
        'n_train': int(len(y_train)), 'n_test': int(len(y_test)),
    }

    # Alert level: chosen on the TRAINING days only. Each training day is predicted by a
    # model that never saw it; the level with the best F1 (balance of "alerts that are
    # right" and "bunching that is caught") wins. Same for the simple gap rule.
    oof_p, oof_gap, oof_y = [], [], []
    for day in train_days:
        others = [d for d in train_days if d != day]
        m, mu, sd = fit(stack(others, 0), stack(others, 1))
        oof_p.append(predict(m, mu, sd, parts[day][0]))
        oof_gap.append(parts[day][2]); oof_y.append(parts[day][1])
    oof_p, oof_gap, oof_y = np.concatenate(oof_p), np.concatenate(oof_gap), np.concatenate(oof_y)
    table = [{'threshold': t, **alert_quality(oof_y, oof_p >= t)} for t in PROB_GRID]
    base = BASELINE[mode]
    base_table = [{'gap_below': g, **alert_quality(oof_y, oof_gap < g)} for g in base['grid']]
    best = max(table, key=lambda row: row['f1'])
    best_base = max(base_table, key=lambda row: row['f1'])
    # thresholds that give a fixed alert budget (1 and 2 alerts per 100 passages) on the training days
    budgets = {}
    for per_100 in (1, 2):
        level = float(np.quantile(oof_p, 1 - per_100 / 100))
        budgets[f'{per_100}_per_100'] = {'threshold': round(level, 4),
                                         'test': alert_quality(y_test, p_test >= level)}
    alerting = {
        'threshold': best['threshold'],
        'budgets': budgets,
        'chosen_by': 'highest F1 on the training days, each day predicted by a model that did not see it',
        'test': alert_quality(y_test, p_test >= best['threshold']),
        'baseline_rule': base['text'](best_base['gap_below']),
        'baseline_gap_below': best_base['gap_below'],
        'baseline_test': alert_quality(y_test, gap_test < best_base['gap_below']),
        'table': table, 'baseline_table': base_table,
    }
    out = {
        'model': 'logistic_regression', 'version': 3, 'mode': mode,
        'trained_at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'agency': agency,
        'target': f'{TARGETS[mode]}, at any of the next {HORIZON_BY_MODE[mode]} stops',
        'horizon_stops': HORIZON_BY_MODE[mode],
        'features': features, 'coef': [round(float(c), 6) for c in model.coef_[0]],
        'intercept': round(float(model.intercept_[0]), 6),
        'mean': [round(float(m), 6) for m in mean], 'std': [round(float(s), 6) for s in std],
        'train_days': [d.isoformat() for d in train_days], 'test_days': [d.isoformat() for d in test_days],
        'metrics': metrics, 'alerting': alerting, 'data': data_stats,
    }
    MODEL_FILES[mode].parent.mkdir(parents=True, exist_ok=True)
    MODEL_FILES[mode].write_text(json.dumps(out, indent=2) + '\n', encoding='utf-8')
    print(f'\n== {mode} ==', json.dumps(metrics))
    print('alert level', best['threshold'], '-> test', alerting['test'])
    print('alert budgets', budgets)
    print('simple rule:', alerting['baseline_rule'], '-> test', alerting['baseline_test'])
    print('coefficients:', dict(zip(features, out['coef'])))
    print(f'saved {MODEL_FILES[mode]}')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--agency', default='IA9T6', help='operator (event agency id), default CARRIS')
    parser.add_argument('--mode', choices=['line', 'corridor', 'both'], default='both')
    args = parser.parse_args()
    modes = ['line', 'corridor'] if args.mode == 'both' else [args.mode]

    parts = {mode: {} for mode in modes}
    totals = {'trips': 0, 'suspect_trips': 0}
    with connect() as conn:
        version = active_version(conn)
        if version is None:
            raise SystemExit('No active dataset. Restore or import the database first.')
        days = [r['operational_date'] for r in conn.execute(
            'SELECT DISTINCT operational_date FROM vehicle_events WHERE version_id=%s AND agency_id=%s ORDER BY 1',
            (version, args.agency))]
        train_days, test_days = split_days(days)
        for day in days:
            rows = fetch_passages(conn, version, day, args.agency)
            trip_stops = fetch_trip_stops(conn, day, args.agency, {r['trip_id'] for r in rows})
            fix = fetch_schedule_fix(conn, day, args.agency)
            for mode in modes:
                stats = {}
                parts[mode][day] = dataset(rows, day, mode, trip_stops, fix, stats)
                y = parts[mode][day][1]
                print(f'{day} {mode:8}: {len(y):,} passages, {y.mean():.2%} bunched within '
                      f'{HORIZON_BY_MODE[mode]} stops; excluded {stats["suspect_trips"]} of {stats["trips"]} trips '
                      f'with a suspect trip_id')
            totals['trips'] += stats['trips']; totals['suspect_trips'] += stats['suspect_trips']
    data_stats = {**totals, 'suspect_share': round(totals['suspect_trips'] / max(totals['trips'], 1), 4),
                  'rule': 'trip-day excluded when its median delay (after repairing flat stop times) is > 30 min'}
    print('suspect trip_ids excluded:', data_stats)
    for mode in modes:
        train(mode, parts[mode], train_days, test_days, args.agency, data_stats)


if __name__ == '__main__':
    main()
