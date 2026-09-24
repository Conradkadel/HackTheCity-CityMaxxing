"""Build the Findings view: WHERE, WHEN and WHY buses bunch every week, and WHAT to change.

Reads the week of stop passages exported by export_passages.py and the simulator's held-out
results, and writes one small JSON file that the API serves at /api/findings:

    cd code/prototype/backend
    ../.venv/bin/python build_findings.py        # ~1 min -> models/findings.json

Inputs (no database needed):
  models/experiments/passages_line.csv.gz   every CARRIS stop passage of the week (export_passages.py)
  models/simulator_validation.json          held-out scenario results (validate_simulator.py)
  models/stop_coords.json                   approximate stop positions from the GPS pings
                                            (rebuild with --vehicles <raw TML vehicles folder>)

Definitions (same as the rest of the app):
  bunched passage   the gap to the previous bus of the SAME line and direction is < 25 % of the planned gap
  departure gap     the gap to the bus in front at the first stop a trip was seen (terminal), vs plan
  shared-stop pile-up   two buses of DIFFERENT lines that share >= 5 stops pass the same stop < 60 s apart
                    at >= 3 stops in a row of the same trip pair
"""
import argparse
import glob
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
MODELS = HERE / 'models'
PASSAGES = MODELS / 'experiments' / 'passages_line.csv.gz'
VALIDATION = MODELS / 'simulator_validation.json'
COORDS = MODELS / 'stop_coords.json'
OUT = MODELS / 'findings.json'

WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
DAYS = WEEKDAYS + ['Sat', 'Sun']
BLOCKS = [('06:00–10:00', 6, 10), ('10:00–16:00', 10, 16), ('16:00–21:00', 16, 21), ('21:00–24:00', 21, 24)]
HOT_FACTOR = 2.0          # "problem" = at least 2x the network's weekday bunching rate ...
HOT_DAYS = 5              # ... on every weekday of the week
TOP_LINES = 10            # problem line-directions shown in the action plan
CLOSE_S = 60              # shared-stop pile-up: buses of different lines < 60 s apart ...
PLANNED_APART_S = 120     # ... although planned >= 2 min apart
MIN_SHARED = 5            # lines "share a corridor" if they serve >= 5 of the same stops
MIN_RUN = 3               # ... and stay together for >= 3 shared stops

FIX_TEXT = {
    'dispatch': ('Buses leave the terminal too soon after the bus in front',
                 'Headway-based dispatch at the terminal: a bus leaves only when the gap to the bus in front '
                 'is at least 90 % of plan (wait at most 3–5 min).'),
    'turnaround': ('The previous trip arrives late and the bus leaves again straight away',
                   'Add 2 min of turnaround (layover) at the terminal in these hours, so a late arrival does not '
                   'carry over into the next trip.'),
    'road': ('Gaps open on the road, not at the terminal',
             'Hold buses briefly (max 90 s) at 1–2 control stops in the middle of the route when the early '
             'warning fires.'),
}
SCENARIO_CAUSE = {'D2+H1': 'dispatch', 'D2': 'dispatch', 'D2-2': 'dispatch', 'D2-5': 'dispatch', 'T2-2': 'turnaround',
                  'T2-4': 'turnaround', 'M-90': 'road', 'H1-60': 'road', 'H1-120': 'road', 'D2+H1': 'dispatch'}


def r(x, n=3):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), n)


def _plain(x):
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.floating):
        return float(x)
    raise TypeError(type(x))


def block_of(hour):
    for name, a, b in BLOCKS:
        if a <= hour < b:
            return name
    return 'night'


def hour_ranges(hours):
    """[16, 17, 18, 20] -> ['16:00–19:00', '20:00–21:00']"""
    out, run = [], []
    for h in sorted(hours):
        if run and h != run[-1] + 1:
            out.append(run)
            run = []
        run.append(h)
    if run:
        out.append(run)
    return [f'{a[0]:02d}:00–{a[-1] + 1:02d}:00' for a in out]


def load_coords(vehicles=None):
    if vehicles:
        parts = []
        for f in glob.glob(os.path.join(vehicles, '*', '2026090[23]', '*.csv')):
            for ch in pd.read_csv(f, usecols=['agency_id', 'created_at', 'latitude', 'longitude', 'stop_id',
                                              'trip_id', 'vehicle_id'], dtype={'stop_id': str, 'vehicle_id': str},
                                  chunksize=500_000):
                ch = ch[(ch.agency_id == 'IA9T6') & ch.stop_id.notna()]
                parts.append(ch.sort_values('created_at').groupby(['trip_id', 'vehicle_id', 'stop_id']).tail(1))
        d = pd.concat(parts).sort_values('created_at').groupby(['trip_id', 'vehicle_id', 'stop_id']).tail(1)
        c = d.groupby('stop_id').agg(lat=('latitude', 'median'), lon=('longitude', 'median'))
        payload = {'source': 'median position of the last CARRIS GPS ping reporting each stop, 2-3 Sep 2026',
                   'stops': {s: [round(v.lat, 6), round(v.lon, 6)] for s, v in c.iterrows()}}
        COORDS.write_text(json.dumps(payload, separators=(',', ':')))
    return json.loads(COORDS.read_text())['stops'] if COORDS.exists() else {}


def load_passages(path):
    d = pd.read_csv(path, dtype={'line': str, 'direction_id': str, 'stop_id': str, 'route_id': str,
                                 'trip_id': str, 'vehicle_id': str})
    d['t'] = pd.to_datetime(d['t'], utc=True, format='ISO8601').dt.tz_convert('Europe/Lisbon')
    d['sched'] = pd.to_datetime(d['sched'], utc=True, format='ISO8601')
    d['hour'] = d['t'].dt.hour
    d['dow'] = pd.to_datetime(d['day']).dt.day_name().str[:3]
    d['weekday'] = d.dow.isin(WEEKDAYS)
    d['block'] = d.hour.map(block_of)
    return d


def trips_from_terminal(v):
    """One row per trip seen from (near) its first stop: departure gap ratio, delay, previous trip delay."""
    k = ['day', 'trip_id', 'vehicle_id']
    v = v.sort_values(k + ['seq'])
    first = v.groupby(k, sort=False).head(1).set_index(k)
    t = v.groupby(k, sort=False).agg(line=('line', 'first'), direction_id=('direction_id', 'first'),
                                     any_bunched=('bunched', 'max'))
    t = t.join(first[['ratio', 'delay', 'prev_trip_delay', 'progress', 'hour', 'block', 'weekday', 'dow',
                      'stop_id']].rename(columns={'ratio': 'dep_ratio', 'delay': 'dep_delay', 'progress': 'first_prog',
                                                  'stop_id': 'first_stop'}))
    return t[t.first_prog < 0.15].reset_index()


def departure_classes(trips, v):
    bins = [('left < 50 % of the planned gap after the bus in front', 0, 0.5, 'too close'),
            ('50–80 %', 0.5, 0.8, 'close'),
            ('80–120 % (as planned)', 0.8, 1.2, 'on plan'),
            ('more than 120 %', 1.2, 99, 'late')]
    wk = trips[trips.weekday & trips.dep_ratio.notna()]
    bunched = v[v.weekday & (v.bunched == 1)].merge(wk[['day', 'trip_id', 'vehicle_id', 'dep_ratio']],
                                                    on=['day', 'trip_id', 'vehicle_id'])
    out = []
    for label, a, b, key in bins:
        sel = wk[(wk.dep_ratio >= a) & (wk.dep_ratio < b)]
        bsel = bunched[(bunched.dep_ratio >= a) & (bunched.dep_ratio < b)]
        out.append({'key': key, 'label': label, 'trips': int(len(sel)), 'tripShare': r(len(sel) / len(wk)),
                    'pBunch': r(sel.any_bunched.mean()), 'bunchingShare': r(len(bsel) / max(len(bunched), 1))})
    return out


def corridors(d, coords):
    """Buses of different lines on a shared stretch that pass together although planned apart."""
    v = d[d.valid == 1].sort_values(['day', 'stop_id', 't'])
    g = v.groupby(['day', 'stop_id'], sort=False)
    v = v.assign(pl=g.line.shift(), pdir=g.direction_id.shift(), pt=g.t.shift(), ps=g.sched.shift(),
                 ptrip=g.trip_id.shift())
    v = v[v.pl.notna() & (v.pl != v.line)]
    v = v.assign(gap=(v.t - v.pt).dt.total_seconds(), sgap=(v.sched - v.ps).dt.total_seconds().abs())

    stops = d[d.valid == 1].groupby(['line', 'direction_id']).stop_id.apply(
        lambda s: set(s.value_counts()[lambda c: c >= 20].index))
    keys = list(stops.index)
    shared = {}
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            if a[0] != b[0]:
                common = stops[a] & stops[b]
                if len(common) >= MIN_SHARED:
                    shared[frozenset([a, b])] = common
    v = v[[frozenset([(a, b), (c, e)]) in shared for a, b, c, e in zip(v.pl, v.pdir, v.line, v.direction_id)]]
    close = v[(v.gap < CLOSE_S)]
    ev = close.groupby(['day', 'trip_id', 'ptrip']).agg(
        n=('stop_id', 'size'), line=('line', 'first'), dirn=('direction_id', 'first'), pl=('pl', 'first'),
        pdir=('pdir', 'first'), planned_close=('sgap', lambda s: bool((s < PLANNED_APART_S).mean() > 0.5)),
        hour=('hour', 'min'), weekday=('weekday', 'first'), dow=('dow', 'first')).reset_index()
    ev = ev[ev.n >= MIN_RUN]
    ev['pair'] = [' & '.join(sorted([a, b])) for a, b in zip(ev.line, ev.pl)]
    ev['key'] = [frozenset([(a, b), (c, e)]) for a, b, c, e in zip(ev.pl, ev.pdir, ev.line, ev.dirn)]
    wk = ev[ev.weekday]
    passes = v.assign(pair=[' & '.join(sorted([a, b])) for a, b in zip(v.line, v.pl)])
    out = []
    for pair, grp in wk.groupby('pair'):
        key = grp.key.value_counts().index[0]
        (l1, d1), (l2, d2) = sorted(key)
        common = shared[key]
        order = (d[(d.line == l1) & (d.direction_id == d1) & d.stop_id.isin(common)]
                 .groupby('stop_id').seq.median().sort_values())
        hours = grp.groupby('hour').size()
        per_day = grp.groupby('dow').size().reindex(DAYS, fill_value=0)
        per_day[['Sat', 'Sun']] = ev[(ev.pair == pair) & ~ev.weekday].groupby('dow').size().reindex(
            ['Sat', 'Sun'], fill_value=0)
        pax = passes[passes.pair == pair]
        out.append({
            'pair': pair, 'lines': [l1, l2], 'directions': [d1, d2],
            'eventsPerWeekday': r(len(grp) / 5, 1), 'daysWithEvents': int(grp.dow.nunique()),
            'plannedTogetherShare': r(grp.planned_close.mean(), 2),
            'peakHours': hour_ranges(hours[hours >= hours.max() * 0.6].index.tolist()),
            'byHour': {int(h): int(n) for h, n in hours.items()},
            'byDay': {k: int(n) for k, n in per_day.items()},
            'closeShare': r((pax.gap < CLOSE_S).mean(), 3),
            'sharedStops': [{'stop_id': s, 'lat': coords.get(s, [None, None])[0], 'lon': coords.get(s, [None, None])[1]}
                            for s in order.index],
        })
    out.sort(key=lambda c: -c['eventsPerWeekday'])
    total = len(wk) / 5
    return out[:8], r(total, 0), r(wk.planned_close.mean(), 2)


def best_change(held_out):
    """The change with the biggest robust cut in waiting on the held-out days (both days, both k).

    'Leave exactly on time' (D1) is a best case, never a policy. When two changes are practically
    equal (within 1 s or 5 %), the cheaper one wins (fewer extra buses, then less holding).
    The frontend applies the same rule (sim.ts bestChange), so Findings and Simulation agree.
    """
    options = [(code, sc) for code, sc in held_out.get('scenarios', {}).items()
               if sc.get('robust') and code != 'D1' and (sc.get('ewt_saved') or 0) > 0]
    if not options:
        return None
    top = max(sc['ewt_saved'] for _, sc in options)
    close = [(code, sc) for code, sc in options if sc['ewt_saved'] >= top - max(1.0, 0.05 * top)]
    cost = lambda item: (item[1].get('extra_vehicles', 0),  # noqa: E731
                         item[1].get('hold_s_per_trip', 0) + item[1].get('terminal_wait_s_per_trip', 0))
    return min(close, key=cost)[0]


def hot_areas(d, coords, cell=0.005):
    """Areas where gaps close on the road more than the lines passing through would lead us to expect.

    Only trips that left the terminal on plan are used, so terminal dispatch is ruled out. For every
    ~500 m cell we count where bunching starts (onsets) and compare with the expected number given the
    line, direction and time of day of every bus that passed there.
    """
    v = d[(d.valid == 1) & d.weekday].copy()
    v = v.sort_values(['day', 'trip_id', 'vehicle_id', 'seq'])
    k = ['day', 'trip_id', 'vehicle_id']
    prev = v.groupby(k).bunched.shift().fillna(0)
    v['onset'] = ((v.bunched == 1) & (prev == 0)).astype(int)
    first = v.groupby(k).head(1)[k + ['ratio', 'progress']].rename(columns={'ratio': 'dep', 'progress': 'fp'})
    v = v.merge(first, on=k, how='left')
    raw = v.copy()
    v = v[(v.dep >= 0.8) & (v.fp < 0.15)]
    v['exp'] = v.groupby(['line', 'direction_id', 'block']).onset.transform('mean')
    v['lat'] = v.stop_id.map(lambda s: coords.get(s, [None, None])[0])
    v['lon'] = v.stop_id.map(lambda s: coords.get(s, [None, None])[1])
    v = v.dropna(subset=['lat'])
    v['cell'] = (np.floor(v.lat / cell)).astype(int).astype(str) + '_' + \
        (np.floor(v.lon / (cell * 1.2))).astype(int).astype(str)
    g = v.groupby('cell').agg(n=('onset', 'size'), onsets=('onset', 'sum'), exp=('exp', 'sum'),
                              lat=('lat', 'mean'), lon=('lon', 'mean'), lines=('line', 'nunique'))
    g['ratio'] = g.onsets / g.exp
    per_day = v.groupby(['cell', 'day']).agg(o=('onset', 'sum'), e=('exp', 'sum'))
    per_day = per_day[per_day.o > 1.2 * per_day.e].reset_index().groupby('cell').size()
    g['days'] = per_day.reindex(g.index).fillna(0).astype(int)
    hot = g[(g.onsets >= 30) & (g.ratio >= 1.3) & (g.days >= 4)].sort_values('ratio', ascending=False)
    out = []
    for cid, a in hot.iterrows():
        inside = v[(v.cell == cid) & (v.onset == 1)]
        hours = inside.groupby('hour').size()
        out.append({'lat': r(a.lat, 5), 'lon': r(a.lon, 5), 'ratio': r(a.ratio, 1), 'days': int(a.days),
                    'onsetsPerWeekday': r(a.onsets / 5, 1), 'lines': int(a.lines),
                    'topLines': inside.line.value_counts().index[:5].tolist(),
                    'peakHours': hour_ranges(hours[hours >= hours.max() * 0.6].index.tolist()),
                    'stops': [{'stop_id': s, 'lat': coords.get(s, [None, None])[0],
                               'lon': coords.get(s, [None, None])[1], 'onsets': int(n)}
                              for s, n in inside.stop_id.value_counts().head(4).items()]})
    # how concentrated is bunching in space at all? (all weekday bunching, same cells)
    raw['lat'] = raw.stop_id.map(lambda s: coords.get(s, [None, None])[0])
    raw['lon'] = raw.stop_id.map(lambda s: coords.get(s, [None, None])[1])
    raw = raw.dropna(subset=['lat'])
    raw['cell'] = (np.floor(raw.lat / cell)).astype(int).astype(str) + '_' + \
        (np.floor(raw.lon / (cell * 1.2))).astype(int).astype(str)
    cells = raw.groupby('cell').agg(b=('bunched', 'sum'), n=('bunched', 'size')).sort_values('b', ascending=False)
    top = cells.head(10)
    summary = {'cells': int(len(cells)), 'top10BunchingShare': r(top.b.sum() / cells.b.sum()),
               'top10VisitShare': r(top.n.sum() / cells.n.sum()),
               'onRoadOnsetsPerWeekday': r(v.onset.sum() / 5, 0),
               'hotAreaShareOfOnRoad': r(hot.onsets.sum() / max(v.onset.sum(), 1))}
    return out, summary


def main(vehicles=None, passages=PASSAGES):
    coords = load_coords(vehicles)
    d = load_passages(passages)
    v = d[d.valid == 1]
    wk = v[v.weekday]
    base = wk.bunched.mean()
    total_bunched = wk.bunched.sum()

    # ---- 1. which lines ------------------------------------------------------------------------------
    L = wk.groupby(['line', 'direction_id']).agg(passages=('bunched', 'size'), bunched=('bunched', 'sum'),
                                                 sched_hw=('sched_hw', 'median')).reset_index()
    L['rate'] = L.bunched / L.passages
    L['share'] = L.bunched / total_bunched
    L = L.sort_values('bunched', ascending=False)
    by_line = wk.groupby('line').bunched.sum().sort_values(ascending=False)
    top5 = by_line.index[:5].tolist()

    # ---- 2. when: line-direction x hour and x weekday -------------------------------------------------
    h = wk.groupby(['line', 'direction_id', 'hour', 'day']).agg(n=('bunched', 'size'), b=('bunched', 'sum')).reset_index()
    h['rate'] = h.b / h.n
    H = h.groupby(['line', 'direction_id', 'hour']).agg(
        days=('day', 'nunique'), hot=('rate', lambda s: int((s >= HOT_FACTOR * base).sum())),
        rate=('rate', 'mean'), n=('n', 'sum')).reset_index()

    blk = v.groupby(['line', 'direction_id', 'block', 'dow']).agg(n=('bunched', 'size'), b=('bunched', 'sum')).reset_index()
    blk['rate'] = blk.b / blk.n
    B = blk[blk.dow.isin(WEEKDAYS)].groupby(['line', 'direction_id', 'block']).agg(
        days=('dow', 'nunique'), hot=('rate', lambda s: int((s >= HOT_FACTOR * base).sum())),
        rate=('rate', 'mean'), bunched=('b', 'sum')).reset_index()
    recurring = B[(B.days == 5) & (B.hot >= HOT_DAYS)].sort_values('bunched', ascending=False)

    # ---- 3. why: departures from the terminal --------------------------------------------------------
    trips = trips_from_terminal(v)
    dep = departure_classes(trips, v)
    net_wk_trips = trips[trips.weekday]
    net_close = (net_wk_trips.dep_ratio < 0.8).mean()
    net_late_prev = (net_wk_trips.prev_trip_delay > 300).mean()

    sim = json.loads(VALIDATION.read_text()).get('held_out', {}) if VALIDATION.exists() else {}

    # ---- problem list: worst block of the top line-directions ----------------------------------------
    problems = []
    seen = set()
    candidates = pd.concat([recurring, B[(B.days == 5)].sort_values('bunched', ascending=False)])
    for _, row in candidates.iterrows():
        key = (row.line, row.direction_id)
        if key in seen:
            continue
        seen.add(key)
        sel = v[(v.line == row.line) & (v.direction_id == row.direction_id)]
        in_blk = sel[sel.block == row.block]
        hh = H[(H.line == row.line) & (H.direction_id == row.direction_id)]
        hot_hours = hh[(hh.rate >= HOT_FACTOR * base) & (hh.hot >= 4) & (hh.n >= 60)].hour.tolist()
        a, b = next((x, y) for n_, x, y in BLOCKS if n_ == row.block)
        hot_hours = [x for x in hot_hours if a <= x < b] or list(range(a, b))
        per_day = in_blk.groupby('dow').bunched.mean().reindex(DAYS)
        t = trips[(trips.line == row.line) & (trips.direction_id == row.direction_id) & (trips.block == row.block)
                  & trips.weekday]
        too_close = (t.dep_ratio < 0.8).mean()
        late_prev = (t.prev_trip_delay > 300).mean()
        # where along the route: bunching rate per stop in the problem hours, and where it STARTS
        w = in_blk[in_blk.weekday].sort_values(['day', 'trip_id', 'vehicle_id', 'seq'])
        prev = w.groupby(['day', 'trip_id', 'vehicle_id']).bunched.shift().fillna(0)
        onsets = w[(w.bunched == 1) & (prev == 0)]
        st = w.groupby('stop_id').agg(seq=('seq', 'median'), rate=('bunched', 'mean'), n=('bunched', 'size'),
                                      days=('day', lambda s: 0),
                                      onsets=('bunched', 'size')).reset_index()
        st['days'] = st.stop_id.map(w[w.bunched == 1].groupby('stop_id').day.nunique()).fillna(0).astype(int)
        st['onsets'] = st.stop_id.map(onsets.stop_id.value_counts()).fillna(0).astype(int)
        st = st[st.n >= 20].sort_values('seq')
        worst = st[(st.days == 5)].sort_values('rate', ascending=False).head(5)
        stretch = st[st.stop_id.isin(worst.stop_id)].sort_values('seq')
        terminal = t.first_stop.value_counts().index[0] if len(t) else None
        # cause: the simulator's held-out recommendation when we have one, otherwise the data rule
        s = sim.get(row.line)
        # the simulator was validated on 16-20 h, so its answer only covers the evening peak
        rec = best_change(s) if s and row.block == '16:00–21:00' else None
        if rec:
            cause = SCENARIO_CAUSE.get(rec, 'dispatch')
        elif late_prev >= 1.5 * net_late_prev:
            cause = 'turnaround'
        elif too_close >= 1.3 * net_close:
            cause = 'dispatch'
        else:
            cause = 'road'
        tested = None
        if s and rec:
            sc = s['scenarios'][rec]
            tested = {'scenario': rec, 'ewtSaved': sc['ewt_saved'], 'ewtSavedRange': sc['ewt_saved_range'],
                      'bunchedPctChange': sc['bunched_pct_change'], 'extraVehicles': sc['extra_vehicles'],
                      'holdPerTrip': sc['hold_s_per_trip'], 'terminalWaitPerTrip': sc['terminal_wait_s_per_trip'],
                      'robust': sc['robust'], 'days': 'held-out Fri 4 + Sun 6 Sep, 16–20 h, 30 seeds, both k',
                      'alsoRobust': [c for c, x in s['scenarios'].items() if x['robust'] and c not in (rec, 'D1')]}
        problems.append({
            'line': row.line, 'direction': row.direction_id, 'block': row.block,
            'hours': hour_ranges(hot_hours), 'hotHours': [int(x) for x in hot_hours],
            'rate': r(row.rate), 'timesNetwork': r(row.rate / base, 1), 'daysHot': int(row.hot),
            'bunchedPerWeekday': r(row.bunched / 5, 0),
            'tripsPerWeekday': r(len(t) / 5, 0) if len(t) else None,
            'schedHeadwayMin': r(sel.sched_hw.median() / 60, 0),
            'byDay': {k: r(x) for k, x in per_day.items()},
            'byHour': {int(x.hour): r(x.rate) for x in hh.itertuples() if x.n >= 60},
            'evidence': {'departTooClose': r(too_close, 2), 'prevTripLate': r(late_prev, 2),
                         'onsetMedianProgress': r(onsets.progress.median(), 2),
                         'onsetFirstQuarter': r((onsets.progress < 0.25).mean(), 2)},
            'cause': cause, 'causeText': FIX_TEXT[cause][0], 'fix': FIX_TEXT[cause][1], 'tested': tested,
            'terminal': {'stop_id': terminal, 'lat': coords.get(terminal, [None, None])[0],
                         'lon': coords.get(terminal, [None, None])[1]} if terminal else None,
            'stretch': [{'stop_id': x.stop_id, 'seq': int(x.seq), 'rate': r(x.rate), 'days': int(x.days),
                         'lat': coords.get(x.stop_id, [None, None])[0], 'lon': coords.get(x.stop_id, [None, None])[1]}
                        for x in stretch.itertuples()],
            'profile': [{'stop_id': x.stop_id, 'seq': int(x.seq), 'rate': r(x.rate), 'onsets': int(x.onsets),
                         'lat': coords.get(x.stop_id, [None, None])[0], 'lon': coords.get(x.stop_id, [None, None])[1]}
                        for x in st.itertuples()],
        })
        if len(problems) >= TOP_LINES:
            break

    # ---- hotspot stops for the map (same line, every weekday) ----------------------------------------
    s = wk.groupby(['stop_id', 'day']).bunched.sum().reset_index()
    S = s.groupby('stop_id').agg(bunched=('bunched', 'sum'), days=('bunched', lambda x: int((x > 0).sum())))
    S['passages'] = wk.groupby('stop_id').size()
    S['rate'] = S.bunched / S.passages
    lines_at = wk[wk.bunched == 1].groupby('stop_id').line.agg(lambda x: x.value_counts().index[:3].tolist())
    peak = wk[wk.bunched == 1].groupby('stop_id').hour.agg(lambda x: int(x.mode().iloc[0]))
    S = S[(S.days == 5) & (S.passages >= 200)].sort_values('bunched', ascending=False).head(80)
    hotspots = [{'stop_id': sid, 'lat': coords.get(sid, [None, None])[0], 'lon': coords.get(sid, [None, None])[1],
                 'bunchedPerWeekday': r(x.bunched / 5, 1), 'rate': r(x.rate), 'lines': lines_at.get(sid, []),
                 'peakHour': peak.get(sid)} for sid, x in S.iterrows()]

    corr, corr_total, corr_planned = corridors(d, coords)
    areas, area_summary = hot_areas(d, coords)

    hours = wk.groupby('hour').bunched.mean()
    top5_mask = wk.line.isin(top5)
    out = {
        'generatedAt': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'source': {'operator': 'CARRIS (IA9T6)', 'from': str(d.day.min()), 'to': str(d.day.max()),
                   'passages': int(len(d)), 'lines': int(d.line.nunique()),
                   'definition': 'A stop passage is bunched when the gap to the previous bus of the same line and '
                                 'direction is less than 25 % of the planned gap.'},
        'headline': {
            'weekdayRate': r(base, 4), 'weekendRate': r(v[~v.weekday].bunched.mean(), 4),
            'bunchedPerWeekday': r(total_bunched / 5, 0),
            'topLines': top5, 'topLinesBunchingShare': r(wk[top5_mask].bunched.sum() / total_bunched),
            'topLinesPassageShare': r(top5_mask.mean()),
            'recurringBlocks': int(len(recurring)),
            'recurringBlocksShare': r(recurring.bunched.sum() / total_bunched),
            'peakHours': hour_ranges(hours[hours >= 1.5 * base].index.tolist()),
            'departTooCloseTripShare': r(sum(x['tripShare'] for x in dep[:2])),
            'departTooCloseBunchingShare': r(sum(x['bunchingShare'] for x in dep[:2])),
            'networkDepartTooClose': r(net_close, 2), 'networkPrevTripLate': r(net_late_prev, 2),
            'corridorEventsPerWeekday': corr_total, 'corridorPlannedTogether': corr_planned,
        },
        'hours': [{'hour': int(k), 'rate': r(x, 4)} for k, x in hours.items()],
        'byDay': {k: r(x, 4) for k, x in v.groupby('dow').bunched.mean().reindex(DAYS).items()},
        'lines': [{'line': x.line, 'direction': x.direction_id, 'bunchedPerWeekday': r(x.bunched / 5, 0),
                   'rate': r(x.rate), 'share': r(x.share), 'schedHeadwayMin': r(x.sched_hw / 60, 0)}
                  for x in L.head(20).itertuples()],
        'departure': dep,
        'problems': problems,
        'hotspots': hotspots,
        'corridors': corr,
        'areas': areas,
        'areaSummary': area_summary,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=_plain))
    print(f'wrote {OUT} ({OUT.stat().st_size / 1e3:.0f} kB): {len(problems)} problems, '
          f'{len(hotspots)} hotspot stops, {len(corr)} corridors')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--vehicles', help='raw TML vehicles folder, to rebuild models/stop_coords.json')
    ap.add_argument('--passages', default=PASSAGES, help='passages export (default: models/experiments/passages_line.csv.gz)')
    args = ap.parse_args()
    main(args.vehicles, args.passages)
