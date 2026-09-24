"""Replay simulator for timing changes (terminal dispatch, turnaround buffers, holding).

Follows the team plan ("Lisbon bus bunching - simulation & timetable plan", section
"Simulator and validation gate"). A scenario only changes WHEN a bus leaves or waits;
everything else comes from what really happened that day.

  * Replay. A bus on its real timeline keeps its own observed run time for every
    segment (stop -> next stop). With no policy the simulation reproduces the data
    exactly (checked by validate_simulator.py and a test).
  * Time shift. A bus moved in time keeps its own observed run times. The plan's
    alternative (scale them by the run-time bank's traffic at the new time) was
    tested on the held-out days and predicted run times worse, so it is off (see
    shifted_run). Seeds add +-5 % noise to the runs of shifted buses (seed 0 = none),
    with common random numbers, so all scenarios see the same noise.
  * Run-time bank. All observed stop-to-stop run times of the day. Used by the
    validation gate: a "resampled" baseline where every bus draws every run from
    the bank at its time must reproduce the real bunching (fits k).
  * Dwell feedback. A bus whose gap to the bus in front grows picks up more people
    and stops longer: extra stop time = k x (gap - gap it really had). k is fitted on
    Mon-Thu by validate_simulator.py.
  * Vehicle chain. A trip cannot start before its vehicle is back from its previous
    trip (+ the layover it really had, at most 1 min). Delays carry over.

Scenarios (plan table "1b"): D1 leave on schedule (ceiling), D2 headway-based dispatch,
T2 longer turnaround (+2 / +4 min, needs extra buses), H1 hold at two control stops,
M hold when the early-warning model fires, and combinations.
"""
import bisect
import heapq
import json
import math
import random
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import bunching

MIN_LAYOVER_S = 60                    # at most this much layover is required between two trips
BANK_WINDOWS_S = (900, 1800, 3600)    # run-time bank: +-15 min, then +-30, +-60
SHIFT_TOLERANCE_S = 30                # a bus within 30 s of its real time keeps its own run times
DWELL_CLIP_S = (-30.0, 120.0)         # the dwell feedback never changes a stop by more than this
NOISE = 0.05                          # seeds change a shifted bus's run time by up to +-5 %
CONTROL_POSITIONS = (1 / 3, 2 / 3)    # H1 control stops: a third and two thirds along the trip
HOLD_TRIGGER_S = 180                  # H1: hold when the bus is > 3 min closer than planned
PERSISTENCE = 0.5                     # resampled baseline only: how much a bus's speed persists
DEFAULT_K = 0.005
MAX_PACE_FACTOR = 2.0                 # trips slower than 2x the usual time per stop are broken records
VALIDATION_FILE = bunching.MODELS_DIR / 'simulator_validation.json'


@dataclass
class Trip:
    key: tuple              # (trip_id, vehicle_id)
    line: str
    direction: str
    stops: list             # [{'stop_id','seq','sched','t_obs','observed','gap_obs'}] first..last observed stop
    dispatchable: bool      # first seen at the terminal (or where this line's buses usually start reporting)
    prev: int = None        # index of the same vehicle's previous simulated trip
    prev_end_obs: float = None
    layover_s: float = 0.0  # layover it needs after the previous trip (observed, at most MIN_LAYOVER_S)


@dataclass
class Scenario:
    code: str
    name: str
    lever: str                     # what changes, in words (for the UI)
    dispatch: str = 'observed'     # observed | schedule | headway
    headway_share: float = 0.9     # D2: leave when the gap is >= 0.9 of plan ...
    max_wait_s: float = 180        # ... but wait at most this long
    buffer_s: float = 0            # T2: extra scheduled turnaround (needs extra buses)
    hold: str = 'none'             # none | control | model
    max_hold_s: float = 0
    package: str = ''              # plan: no cost | low cost | investment


SCENARIOS = [
    Scenario('AS', 'As run', 'nothing (the real day)'),
    Scenario('D1', 'Leave on schedule', 'every bus leaves the terminal at its timetable time (if it is there)',
             dispatch='schedule', package='ceiling'),
    Scenario('D2-2', 'Headway dispatch, max 2 min', 'wait at the terminal until the gap is 90 % of plan, max 2 min',
             dispatch='headway', max_wait_s=120, package='no cost'),
    Scenario('D2', 'Headway dispatch, max 3 min', 'wait at the terminal until the gap is 90 % of plan, max 3 min',
             dispatch='headway', max_wait_s=180, package='no cost'),
    Scenario('D2-5', 'Headway dispatch, max 5 min', 'wait at the terminal until the gap is 90 % of plan, max 5 min',
             dispatch='headway', max_wait_s=300, package='no cost'),
    Scenario('H1-60', 'Control-stop hold, max 60 s', 'hold at 2 mid-route stops when > 3 min too close, max 60 s',
             hold='control', max_hold_s=60, package='low cost'),
    Scenario('H1-120', 'Control-stop hold, max 120 s', 'hold at 2 mid-route stops when > 3 min too close, max 120 s',
             hold='control', max_hold_s=120, package='low cost'),
    Scenario('M-90', 'Early-warning hold, max 90 s', 'hold where the model predicts bunching, max 90 s',
             hold='model', max_hold_s=90, package='low cost'),
    Scenario('D2+H1', 'Headway dispatch + control hold', 'D2 (max 3 min) and H1 (max 90 s) together',
             dispatch='headway', max_wait_s=180, hold='control', max_hold_s=90, package='low cost'),
    Scenario('T2-2', 'Turnaround +2 min', 'leave on schedule with 2 min more layover between trips',
             dispatch='schedule', buffer_s=120, package='investment'),
    Scenario('T2-4', 'Turnaround +4 min', 'leave on schedule with 4 min more layover between trips',
             dispatch='schedule', buffer_s=240, package='investment'),
]
SCENARIO_BY_CODE = {s.code: s for s in SCENARIOS}


def load_params():
    """Fitted parameters from validate_simulator.py ({} if it has not run yet)."""
    try:
        return json.loads(Path(VALIDATION_FILE).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {}


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
def build_bank(items):
    """(from_stop, to_stop) -> (departure times, runs in that order, all runs sorted), from
    consecutive observed passages of every bus (the traffic record of the day)."""
    bank = {}
    for trip in bunching.trips_of(items).values():
        for a, b in zip(trip, trip[1:]):
            if b['seq'] - a['seq'] != 1:
                continue
            run_s = (b['t'] - a['t']).total_seconds()
            if 0 <= run_s <= 1800:
                bank.setdefault((a['stop_id'], b['stop_id']), []).append((a['t'].timestamp(), run_s))
    out = {}
    for segment, runs in bank.items():
        runs.sort()
        out[segment] = ([r[0] for r in runs], [r[1] for r in runs], sorted(r[1] for r in runs))
    return out


def usual_first_seq(items):
    """(line, direction) -> the stop where its buses most often start reporting.
    Some lines (e.g. 742 towards Bairro Madre Deus) only report from their 5th stop."""
    counts = {}
    for trip in bunching.trips_of(items).values():
        key = (trip[0]['line'], trip[0]['direction_id'])
        counts.setdefault(key, {}).setdefault(trip[0]['seq'], 0)
        counts[key][trip[0]['seq']] += 1
    return {key: max(c, key=c.get) for key, c in counts.items()}


def build_trips(items, trip_stops, pairs, since=None, until=None):
    """Simulation trips for the (line, direction) pairs, in order of their first passage.

    items: bunching.build_features(mode='line') output; it must contain both directions
    of a line so each vehicle's previous trip is known.
    since / until (epoch s): keep only trips that start in between (speed; a window's
    KPIs need the trips of the window plus about 2 hours before it, as buses in front).
    """
    usual = usual_first_seq(items)
    trips = []
    for key, passages in bunching.trips_of(items).items():
        first = passages[0]
        if (first['line'], first['direction_id']) not in pairs or \
                (since is not None and first['t'].timestamp() < since) or \
                (until is not None and first['t'].timestamp() >= until):
            continue
        planned = trip_stops.get(key[0]) or []
        seen = {p['seq']: p for p in passages}
        stops = []
        for seq in range(first['seq'], passages[-1]['seq'] + 1):
            p = seen.get(seq)
            stop_id = p['stop_id'] if p else (planned[seq - 1] if seq - 1 < len(planned) else None)
            if stop_id is None:
                continue
            stops.append({'stop_id': stop_id, 'seq': seq, 'observed': p is not None,
                          't_obs': p['t'].timestamp() if p else None,
                          'sched': p['sched'].timestamp() if p and p['sched'] else None, 'gap_obs': None})
        _interpolate(stops, 't_obs')
        _interpolate(stops, 'sched')
        for a, b in zip(stops, stops[1:]):      # passage times never go backwards
            b['t_obs'] = max(b['t_obs'], a['t_obs'])
        start_limit = max(usual.get((first['line'], first['direction_id']), 1), 2)
        trips.append(Trip(key=key, line=first['line'], direction=first['direction_id'], stops=stops,
                          dispatchable=first['seq'] <= start_limit))
    # drop broken records: a trip that took more than twice the usual time of its line and direction
    # (e.g. a bus that kept reporting the same trip for hours)
    durations = {}
    for trip in trips:
        span = (trip.stops[-1]['t_obs'] - trip.stops[0]['t_obs']) / max(trip.stops[-1]['seq'] - trip.stops[0]['seq'], 1)
        durations.setdefault((trip.line, trip.direction), []).append(span)
    usual_pace = {key: statistics.median(v) for key, v in durations.items()}
    trips = [t for t in trips if (t.stops[-1]['t_obs'] - t.stops[0]['t_obs'])
             / max(t.stops[-1]['seq'] - t.stops[0]['seq'], 1) <= MAX_PACE_FACTOR * usual_pace[(t.line, t.direction)]]
    trips.sort(key=lambda trip: trip.stops[0]['t_obs'])
    last_of_vehicle = {}
    for i, trip in enumerate(trips):
        previous = last_of_vehicle.get(trip.key[1])
        if previous is not None and trips[previous].stops[-1]['t_obs'] <= trip.stops[0]['t_obs']:
            trip.prev = previous
            trip.prev_end_obs = trips[previous].stops[-1]['t_obs']
            trip.layover_s = min(trip.stops[0]['t_obs'] - trip.prev_end_obs, MIN_LAYOVER_S)
        last_of_vehicle[trip.key[1]] = i
    for i, passages in observed(trips)['history'].items():     # the gap each bus really had at each stop
        for p in passages:
            trips[i].stops[p['index']]['gap_obs'] = p['gap']
    return trips


def _interpolate(stops, field):
    known = [i for i, s in enumerate(stops) if s[field] is not None]
    for a, b in zip(known, known[1:]):
        for i in range(a + 1, b):
            stops[i][field] = stops[a][field] + (stops[b][field] - stops[a][field]) * (i - a) / (b - a)


# ---------------------------------------------------------------------------
# Run times
# ---------------------------------------------------------------------------
def _window(entry, t):
    times, runs, all_sorted = entry
    for width in BANK_WINDOWS_S:
        lo, hi = bisect.bisect_left(times, t - width), bisect.bisect_right(times, t + width)
        if hi - lo >= 3:
            return sorted(runs[lo:hi])
    return all_sorted


def _median(entry, t):
    times, runs, all_sorted = entry
    for width in BANK_WINDOWS_S:
        lo, hi = bisect.bisect_left(times, t - width), bisect.bisect_right(times, t + width)
        if hi - lo >= 5:
            return statistics.median(runs[lo:hi])
    return statistics.median(all_sorted)


def shifted_run(bank, a, b, t_real, t_new, own_run, noise=0.0, scale=False):
    """Run time a -> b for a bus leaving at t_new instead of its real time t_real.

    A shifted bus keeps its own observed run (+-5 % seed noise when it is >= 30 s off its
    real time). scale=True would also scale it by the traffic change in the bank (median
    run around t_new / around t_real), as the plan suggests; validate_simulator.py tests
    that on the held-out days and it predicted run times WORSE than keeping the own run
    (Fri 37.5 s vs 36.2 s mean error), so it is off."""
    if abs(t_new - t_real) < SHIFT_TOLERANCE_S:
        return own_run
    factor = 1.0
    entry = bank.get((a, b))
    if scale and entry is not None:
        before, after = _median(entry, t_real), _median(entry, t_new)
        factor = min(max(after / before, 0.5), 2.0) if before > 0 else 1.0
    return own_run * factor * (1 + noise)


def _noise(seed, trip):
    """Common random numbers: same seed + same bus -> same noise in every scenario."""
    if seed == 0:
        return [0.0] * len(trip.stops)
    rng = random.Random(f'{seed}|{trip.key}')
    return [rng.uniform(-NOISE, NOISE) for _ in trip.stops]


def _resampled(seed, trip):
    """Resampled baseline (validation only): persistent random quantiles for every segment."""
    rng = random.Random(f'r{seed}|{trip.key}')
    z_trip = rng.gauss(0, 1)
    return [0.5 * (1 + math.erf((PERSISTENCE * z_trip + math.sqrt(1 - PERSISTENCE ** 2) * rng.gauss(0, 1))
                                / math.sqrt(2))) for _ in trip.stops]


# ---------------------------------------------------------------------------
# The simulation
# ---------------------------------------------------------------------------
def run(trips, bank, scenario, seed=0, k=DEFAULT_K, model=None, threshold=None, resample=False):
    """Simulate all trips under one scenario.

    Returns {'history': {trip index: [passage, ...]}, 'holds': [...], 'dispatch_wait': {i: s}}.
    A passage: {'index','stop_id','t','leader','gap','planned'}. resample=True replaces every
    run time by a draw from the bank (validation of the traffic mechanism only).
    """
    noise = [_resampled(seed, t) if resample else _noise(seed, t) for t in trips]
    heap, order = [], 0
    waiting = {}                     # previous trip index -> trips waiting for that vehicle
    for i, trip in enumerate(trips):
        if trip.prev is None:
            heapq.heappush(heap, (_start(trip, scenario, None), i, 0, order, 'start'))
            order += 1
        else:
            waiting.setdefault(trip.prev, []).append(i)
    last = {}                        # (line, direction, stop) -> (trip index, time, sched)
    history, holds, dispatch_wait, done_holds = {}, [], {}, {}
    recent = {}                      # (line, direction) -> [(time, |log gap ratio|)] for the model's line_irreg30
    control = {i: {max(1, round((len(t.stops) - 1) * p)) for p in CONTROL_POSITIONS} for i, t in enumerate(trips)}

    while heap:
        time, i, j, _, kind = heapq.heappop(heap)   # ties: same order as observed()
        trip, stop = trips[i], trips[i].stops[j]
        key = (trip.line, trip.direction, stop['stop_id'])
        leader = last.get(key)
        planned = stop['sched'] - leader[2] if leader and leader[2] is not None and stop['sched'] is not None \
            else None

        if kind == 'start' and trip.dispatchable and scenario.dispatch == 'headway' \
                and leader is not None and planned and planned > 0:
            wait = min(max(leader[1] + scenario.headway_share * planned - time, 0.0), scenario.max_wait_s)
            if wait >= 1:
                dispatch_wait[i] = dispatch_wait.get(i, 0.0) + wait
                heapq.heappush(heap, (time + wait, i, 0, order, 'go'))
                order += 1
                continue
        if j > 0 and leader is not None:
            reference = (stop['gap_obs'] if not resample else planned)
            if reference is not None and k:
                extra = k * ((time - leader[1]) - reference)
                time += min(max(extra, DWELL_CLIP_S[0]), DWELL_CLIP_S[1])
            if scenario.hold != 'none' and planned:
                hold = _hold(scenario, trip, i, j, time, leader, planned, control, history,
                             done_holds, model, threshold, recent)
                if hold >= bunching.MIN_HOLD_S:
                    holds.append({'trip': i, 'index': j, 'seconds': hold, 't': time})
                    done_holds.setdefault(i, []).append(j)
                    time += hold
        history.setdefault(i, []).append({'index': j, 'stop_id': stop['stop_id'], 't': time,
                                          'leader': leader[0] if leader else None,
                                          'gap': time - leader[1] if leader else None, 'planned': planned})
        if scenario.hold == 'model' and leader is not None and planned and \
                bunching.SCHED_HEADWAY_RANGE[0] <= planned <= bunching.SCHED_HEADWAY_RANGE[1]:
            recent.setdefault((trip.line, trip.direction), []).append((time, bunching._log_dev((time - leader[1]) / planned)))
        last[key] = (i, time, stop['sched'])

        if j + 1 < len(trip.stops):
            nxt = trip.stops[j + 1]
            own = nxt['t_obs'] - stop['t_obs']
            if resample:
                entry = bank.get((stop['stop_id'], nxt['stop_id']))
                if entry is not None and stop['observed'] and nxt['observed']:
                    runs = _window(entry, time)
                    own = runs[min(int(noise[i][j] * len(runs)), len(runs) - 1)]
            else:
                own = shifted_run(bank, stop['stop_id'], nxt['stop_id'], stop['t_obs'], time, own, noise[i][j])
            heapq.heappush(heap, (time + own, i, j + 1, order, 'stop'))
            order += 1
        else:
            for follower in waiting.pop(i, []):          # the vehicle is back: its next trip can start
                heapq.heappush(heap, (_start(trips[follower], scenario, time), follower, 0, order, 'start'))
                order += 1
    return {'history': history, 'holds': holds, 'dispatch_wait': dispatch_wait}


def _start(trip, scenario, prev_end):
    """When a trip leaves its first stop: the policy's wish, but never before its vehicle is back."""
    first = trip.stops[0]
    wish = first['t_obs']
    if trip.dispatchable and scenario.dispatch == 'schedule' and first['sched'] is not None:
        wish = first['sched']
    if prev_end is None:
        # vehicle's previous trip unknown: we cannot tell when it was ready, so never earlier than it really left
        return max(wish, first['t_obs'])
    ready = prev_end + trip.layover_s - scenario.buffer_s     # T2: the extra layover absorbs a late arrival
    if not trip.dispatchable:
        # the trip was first seen mid-route: keep its real distance to the vehicle's arrival
        ready = prev_end + (first['t_obs'] - trip.prev_end_obs) - scenario.buffer_s
    return max(wish, ready)


def _hold(scenario, trip, i, j, time, leader, planned, control, history, done_holds, model, threshold, recent=None):
    """Seconds to hold bus i at stop j (0 = none). Holding never makes the gap more than 90 % of plan."""
    gap = time - leader[1]
    room = 0.9 * planned - gap
    if room <= 0:
        return 0.0
    if scenario.hold == 'control':
        return min(scenario.max_hold_s, room) if j in control[i] and gap < planned - HOLD_TRIGGER_S else 0.0
    if scenario.hold == 'model' and model is not None:
        done = done_holds.get(i, [])
        if len(done) >= bunching.MAX_HOLDS_PER_TRIP or any(j - d < bunching.STOPS_BETWEEN_HOLDS for d in done):
            return 0.0
        p = _model_state(trip, j, time, leader, planned, history, i, recent)
        if p is not None and p['ratio'] >= bunching.ONSET_MIN_RATIO and \
                bunching.predict(model, bunching.feature_vector(p)) >= threshold:
            return min(scenario.max_hold_s, room)
    return 0.0


def _model_state(trip, j, time, leader, planned, history, i=None, recent=None):
    """The early-warning model's inputs, from the simulated state only.
    history: {trip index: simulated passages so far} (a plain list = this bus's own passages, older callers)."""
    stop = trip.stops[j]
    if not (bunching.SCHED_HEADWAY_RANGE[0] <= planned <= bunching.SCHED_HEADWAY_RANGE[1]):
        return None
    past = history if isinstance(history, list) else history.get(i, [])
    earlier = [p for p in past if p['index'] <= j - bunching.TREND_STOPS and p['gap'] is not None and p['planned']]
    gap = time - leader[1]
    state = {'hw': gap, 'sched_hw': planned, 'ratio': gap / planned,
             'ratio_prev': earlier[-1]['gap'] / earlier[-1]['planned'] if earlier else None,
             'delay': time - stop['sched'], 'lead_delay': leader[1] - leader[2],
             'progress': stop['seq'] / trip.stops[-1]['seq'], 'prev_trip_delay': None,
             't': datetime.fromtimestamp(time, timezone.utc)}
    # context features (bunching.CONTEXT_FEATURES) from the simulated history
    by_index = {p['index']: p for p in past}
    for k in (1, 3, 5):
        q = by_index.get(j - k)
        state[f'close{k}'] = (gap - q['gap']) / k if q is not None and q['gap'] is not None else None
    q = by_index.get(j - 1)
    state['leader_changed'] = None if q is None else float(q['leader'] != leader[0])
    q = by_index.get(j - 3)
    state['delay_change3'] = ((time - stop['sched']) - (q['t'] - trip.stops[j - 3]['sched'])) / 60 \
        if q is not None and stop['sched'] is not None and trip.stops[j - 3]['sched'] is not None else None
    lead = None if isinstance(history, list) else next(
        (p for p in reversed(history.get(leader[0], [])) if p['stop_id'] == stop['stop_id']), None)
    if lead is not None and lead['gap'] is not None and lead['planned']:
        state['lead_ratio'] = lead['gap'] / lead['planned']
        lead_by_index = {p['index']: p for p in history.get(leader[0], [])}
        q = lead_by_index.get(lead['index'] - 3)
        state['lead_close3'] = (lead['gap'] - q['gap']) / 3 if q is not None and q['gap'] is not None else None
    if recent is not None:
        seen = recent.get((trip.line, trip.direction), [])
        while seen and seen[0][0] < time - bunching.IRREGULARITY_WINDOW_S:
            seen.pop(0)                      # passages are recorded in (almost) time order
        window = [dev for t, dev in seen if time - bunching.IRREGULARITY_WINDOW_S <= t < time]
        state['line_n30'] = float(len(window))
        state['line_irreg30'] = sum(window) / len(window) if window else None
    return state


def observed(trips):
    """The real day in the same format as run() (for the validation gate and the diagram)."""
    events = sorted((s['t_obs'], i, j) for i, t in enumerate(trips) for j, s in enumerate(t.stops))
    last, history = {}, {}
    for t, i, j in events:
        trip, stop = trips[i], trips[i].stops[j]
        key = (trip.line, trip.direction, stop['stop_id'])
        leader = last.get(key)
        planned = stop['sched'] - leader[2] if leader and leader[2] is not None and stop['sched'] is not None \
            else None
        history.setdefault(i, []).append({'index': j, 'stop_id': stop['stop_id'], 't': t,
                                          'leader': leader[0] if leader else None,
                                          'gap': t - leader[1] if leader else None, 'planned': planned})
        last[key] = (i, t, stop['sched'])
    for passages in history.values():
        passages.sort(key=lambda p: p['index'])
    return {'history': history, 'holds': [], 'dispatch_wait': {}}


# ---------------------------------------------------------------------------
# KPIs (plan section "Scoring")
# ---------------------------------------------------------------------------
def in_window(trips, window, pairs=None):
    """Trips that really started inside the window (the same set in every scenario)."""
    start, end = window
    return {i for i, t in enumerate(trips) if start <= t.stops[0]['t_obs'] < end
            and (pairs is None or (t.line, t.direction) in pairs)}


def is_bunched(p):
    return p['gap'] is not None and p['planned'] is not None and \
        bunching.SCHED_HEADWAY_RANGE[0] <= p['planned'] <= bunching.SCHED_HEADWAY_RANGE[1] and \
        p['gap'] / p['planned'] < bunching.BUNCHED_RATIO


def kpis(trips, result, window, pairs=None):
    """Bunched share, headway CV, excess wait time, holding and trip time for the trips
    that really started in the window, at the stops where they were really seen."""
    chosen = in_window(trips, window, pairs)
    valid, by_stop, durations = [], {}, []
    for i in chosen:
        passages = result['history'].get(i, [])
        if passages:
            durations.append(passages[-1]['t'] - passages[0]['t'])
        for p in passages:
            if not trips[i].stops[p['index']]['observed'] or p['gap'] is None or p['planned'] is None \
                    or not (bunching.SCHED_HEADWAY_RANGE[0] <= p['planned'] <= bunching.SCHED_HEADWAY_RANGE[1]):
                continue
            valid.append(p)
            by_stop.setdefault((trips[i].line, trips[i].direction, p['stop_id']), []).append(max(p['gap'], 0.0))
    bunched = sum(1 for p in valid if p['gap'] / p['planned'] < bunching.BUNCHED_RATIO)
    cvs, ewt_sum, ewt_n = [], 0.0, 0
    for gaps in by_stop.values():
        mean = statistics.mean(gaps)
        if len(gaps) >= 3 and mean > 0:
            cvs.append(statistics.pstdev(gaps) / mean)
            # excess wait = wait of a passenger arriving at random - wait with the same buses evenly spaced
            ewt_sum += (sum(g * g for g in gaps) / (2 * sum(gaps)) - mean / 2) * len(gaps)
            ewt_n += len(gaps)
    n = max(len(chosen), 1)
    return {'trips': len(chosen), 'passages': len(valid), 'bunched': bunched,
            'bunched_pct': round(100 * bunched / len(valid), 2) if valid else None,
            'headway_cv': round(statistics.mean(cvs), 3) if cvs else None,
            'ewt_s': round(ewt_sum / ewt_n, 1) if ewt_n else None,
            'holds': sum(1 for h in result['holds'] if h['trip'] in chosen),
            'hold_s_per_trip': round(sum(h['seconds'] for h in result['holds'] if h['trip'] in chosen) / n, 1),
            'terminal_wait_s_per_trip': round(sum(w for i, w in result['dispatch_wait'].items() if i in chosen) / n, 1),
            'trip_time_min': round(statistics.mean(durations) / 60, 2) if durations else None}


def extra_vehicles(trips, scenario, pairs):
    """T2: a longer turnaround needs more buses = extra cycle time / planned headway (rounded up)."""
    if not scenario.buffer_s:
        return 0
    extra = 0
    for pair in {(t.line, t.direction) for t in trips if (t.line, t.direction) in pairs}:
        starts = sorted(t.stops[0]['sched'] for t in trips if (t.line, t.direction) == pair and t.dispatchable
                        and t.stops[0]['sched'] is not None)
        gaps = [b - a for a, b in zip(starts, starts[1:]) if b > a]
        if gaps:
            extra = max(extra, math.ceil(2 * scenario.buffer_s / statistics.median(gaps)))
    return extra


def departure_buckets(trips, result, window, pairs=None):
    """Plan check 2: gap ratio when the bus leaves -> share of trips that bunch later on."""
    edges = [(0.25, 0.5), (0.5, 0.75), (0.75, 0.9), (0.9, 1.1)]
    counts = {e: [0, 0] for e in edges}
    for i in in_window(trips, window, pairs):
        passages = result['history'].get(i, [])
        if not trips[i].dispatchable or not passages:
            continue
        first = passages[0]
        if first['gap'] is None or not first['planned'] or \
                not (bunching.SCHED_HEADWAY_RANGE[0] <= first['planned'] <= bunching.SCHED_HEADWAY_RANGE[1]):
            continue
        r0 = first['gap'] / first['planned']
        later = any(is_bunched(p) and trips[i].stops[p['index']]['observed'] for p in passages[1:])
        for e in edges:
            if e[0] <= r0 < e[1]:
                counts[e][0] += 1
                counts[e][1] += later
    return {f'{a}-{b}': {'n': c[0], 'bunch_later': c[1]} for (a, b), c in counts.items()}


def growth(trips, result, window, pairs=None):
    """Plan check 3: bunched share in the first 40 % vs the last 40 % of each trip."""
    parts = {'first_40': [0, 0], 'last_40': [0, 0]}
    for i in in_window(trips, window, pairs):
        n = trips[i].stops[-1]['seq']
        for p in result['history'].get(i, []):
            stop = trips[i].stops[p['index']]
            if not stop['observed'] or p['gap'] is None or not p['planned'] or \
                    not (bunching.SCHED_HEADWAY_RANGE[0] <= p['planned'] <= bunching.SCHED_HEADWAY_RANGE[1]):
                continue
            share = stop['seq'] / n
            part = 'first_40' if share <= 0.4 else 'last_40' if share >= 0.6 else None
            if part:
                parts[part][0] += 1
                parts[part][1] += is_bunched(p)
    return {k: {'n': v[0], 'bunched': v[1]} for k, v in parts.items()}
