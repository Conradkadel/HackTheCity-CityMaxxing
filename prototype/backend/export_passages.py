"""Export EVERY stop passage (same-line view) with all computed fields to a gzipped CSV,
so feature research can happen offline without the database.

    cd code/prototype/backend
    export DATABASE_URL=postgresql://headway:<password>@127.0.0.1:5433/headway
    ../.venv/bin/python export_passages.py          # ~2 min -> models/experiments/passages_line.csv.gz

Uses exactly the same preparation as the model (build_features: schedule repair, suspect trips
removed, gap to the bus in front, label). Nothing is filtered, so you can rebuild any feature.
"""
import csv
import gzip
import time
from pathlib import Path

from bunching import build_features, fetch_passages, fetch_schedule_fix, stop_key
from db import active_version, connect

OUT = Path(__file__).parent / 'models' / 'experiments' / 'passages_line.csv.gz'
COLS = ['day', 'trip_id', 'vehicle_id', 'line', 'direction_id', 'route_id', 'stop_id', 'seq', 'last_seq', 'is_last',
        't', 't_first', 'sched', 'delay', 'prev_trip_delay', 'leader_trip', 'leader_vehicle', 'hw', 'sched_hw',
        'lead_delay', 'ratio', 'ratio_prev', 'valid', 'bunched', 'progress', 'label']


def iso(v):
    return v.isoformat() if hasattr(v, 'isoformat') else v


def main(agency='IA9T6'):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with connect() as conn, gzip.open(OUT, 'wt', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(COLS)
        version = active_version(conn)
        days = [r['operational_date'] for r in conn.execute(
            'SELECT DISTINCT operational_date FROM vehicle_events WHERE version_id=%s AND agency_id=%s ORDER BY 1',
            (version, agency))]
        for day in days:
            t0 = time.time()
            rows = fetch_passages(conn, version, day, agency)
            extra = {(r['trip_id'], r['vehicle_id'], r['stop_id']): r for r in rows}
            fix = fetch_schedule_fix(conn, day, agency)
            items = build_features(rows, day, 'line', None, fix, stats={})
            for p in items:
                r = extra.get((p['trip_id'], p['vehicle_id'], p['stop_id']), {})
                w.writerow([day.isoformat(), p['trip_id'], p['vehicle_id'], p['line'], p['direction_id'],
                            r.get('route_id'), p['stop_id'], p['seq'], r.get('last_seq'), int(bool(p.get('is_last'))),
                            iso(p['t']), iso(r.get('t_first')), iso(p.get('sched')), p.get('delay'), p.get('prev_trip_delay'),
                            p.get('leader_trip'), p.get('leader_vehicle'), p.get('hw'), p.get('sched_hw'),
                            p.get('lead_delay'), p.get('ratio'), p.get('ratio_prev'), int(bool(p.get('valid'))),
                            int(bool(p.get('bunched'))), p.get('progress'),
                            '' if p.get('label') is None else int(p['label'])])
            n += len(items)
            print(f'{day}: {len(items):,} passages ({time.time() - t0:.0f}s)')
    print(f'saved {n:,} passages to {OUT} ({OUT.stat().st_size / 1e6:.0f} MB)')


if __name__ == '__main__':
    main()
