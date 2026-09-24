"""Historical heatmaps of distinct, qualified stop-headway episodes.

Stop evidence is assigned to the incoming directed stop pair; no claim is made
about where the episode began or continuous bunching between stops.
"""
from collections import defaultdict
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from bunching_analysis import DEFAULT_PARAMETERS, DETECTOR_VERSION
from traffic_diagram import stop_paths

LISBON = ZoneInfo('Europe/Lisbon')
BUCKET_MINUTES = 30
MAX_EVIDENCE = 200_000


def load_history(conn, version, agency, line):
    dates = [r['operational_date'] for r in conn.execute('''
        SELECT DISTINCT operational_date FROM vehicle_events
        WHERE version_id=%s AND agency_id=%s ORDER BY operational_date
    ''', (version, agency))]
    runs = conn.execute('''
        SELECT DISTINCT ON (operational_date) id,operational_date
        FROM analysis_runs
        WHERE dataset_version=%s AND operator_id=%s AND detector_version=%s
          AND parameters=%s AND status='completed' AND operational_date=ANY(%s::date[])
          AND (%s=ANY(selected_lines) OR scope='all_observed_lines')
        ORDER BY operational_date,completed_at DESC NULLS LAST,id DESC
    ''', (version, agency, DETECTOR_VERSION, Jsonb(DEFAULT_PARAMETERS), dates, line)).fetchall()
    analyzed = {r['operational_date'] for r in runs}
    coverage = dict(availableDates=dates, analyzedDates=sorted(analyzed),
                    missingDates=[day for day in dates if day not in analyzed],
                    availableDays=len(dates), analyzedDays=len(analyzed),
                    complete=bool(dates) and len(analyzed) == len(dates),
                    analysisRunIds=[r['id'] for r in runs])
    rows = []
    if runs:
        rows = conn.execute('''
            SELECT e.id AS episode_id,e.direction_id,b.stop_id AS to_stop_id,
                   previous.stop_id AS from_stop_id,b.first_reported_at,b.second_reported_at,
                   r.operational_date
            FROM bunching_episodes e
            JOIN analysis_runs r ON r.id=e.analysis_run_id
            JOIN bunching_evidence b ON b.episode_id=e.id
            LEFT JOIN schedule_stop_visits current ON current.package_id=e.package_id
              AND current.trip_id=b.first_trip_id AND current.stop_id=b.stop_id
              AND current.stop_sequence=b.stop_sequence
            LEFT JOIN LATERAL (
                SELECT v.stop_id FROM schedule_stop_visits v
                WHERE v.package_id=current.package_id AND v.trip_id=current.trip_id
                  AND v.stop_sequence<current.stop_sequence
                ORDER BY v.stop_sequence DESC LIMIT 1
            ) previous ON true
            WHERE e.analysis_run_id=ANY(%s) AND e.operator_id=%s AND e.public_line=%s
              AND e.classification='multi_stop_candidate'
            ORDER BY e.id,b.evidence_sequence LIMIT %s
        ''', ([r['id'] for r in runs], agency, line, MAX_EVIDENCE+1)).fetchall()
    if len(rows) > MAX_EVIDENCE:
        raise HTTPException(413, 'Bunching history exceeds the on-demand limit. Precompute spatial summaries; no evidence was truncated.')
    return coverage, rows


def time_bucket(row):
    # Midpoint locates this stop detection, not the beginning of the whole episode.
    stamp = row['first_reported_at'] + (row['second_reported_at'] - row['first_reported_at']) / 2
    local = stamp.astimezone(LISBON)
    return (local.hour * 60 + local.minute) // BUCKET_MINUTES * BUCKET_MINUTES


def summarize(rows, analyzed_days):
    episodes = {r['episode_id'] for r in rows}
    dates = {r['operational_date'] for r in rows}
    count = len(episodes) if analyzed_days else None
    return dict(episodeCount=count, daysWithEpisodes=len(dates) if analyzed_days else None,
                episodesPerAnalyzedDay=round(len(episodes)/analyzed_days, 4) if analyzed_days else None)


def build_sections(stops, shape, direction, coverage, rows, include_cells):
    by_pair = defaultdict(list)
    for row in rows:
        if row['direction_id'] == direction and row['from_stop_id'] is not None:
            by_pair[row['from_stop_id'], row['to_stop_id']].append(row)
    analyzed_days = coverage['analyzedDays']
    sections = []
    mapped_episodes = set()
    pairs = list(zip(stops, stops[1:]))
    pair_counts = defaultdict(int)
    for first, second in pairs:
        pair_counts[first['stop_id'], second['stop_id']] += 1
    for (first, second), path in zip(pairs, stop_paths(stops, shape)):
        key = (first['stop_id'], second['stop_id'])
        # A repeated directed pair may refer to different legs of a loop.
        ambiguous = pair_counts[key] > 1
        evidence = [] if ambiguous else by_pair[key]
        mapped_episodes.update(r['episode_id'] for r in evidence)
        denominator = 0 if ambiguous else analyzed_days
        points = [path[0][0], *[piece[1] for piece in path]] if path else []
        section = dict(fromStopId=first['stop_id'], toStopId=second['stop_id'],
                       fromSequence=first['stop_sequence'], toSequence=second['stop_sequence'],
                       fromName=first['name'] or first['stop_id'], toName=second['name'] or second['stop_id'],
                       geometryAvailable=bool(path), points=points,
                       lengthMeters=round(sum(piece[2] for piece in path)),
                       status='ambiguous_stop_pair' if ambiguous else 'available' if analyzed_days else 'not_analyzed',
                       **summarize(evidence, denominator))
        if include_cells:
            buckets = defaultdict(list)
            for row in evidence:
                buckets[time_bucket(row)].append(row)
            section['cells'] = [dict(minute=minute, **summarize(buckets[minute], denominator))
                                for minute in range(0, 1440, BUCKET_MINUTES)]
        sections.append(section)
    return sections, mapped_episodes


def history_metadata(version, coverage, rows):
    dates = coverage['availableDates']
    return dict(datasetVersion=version, detectorVersion=DETECTOR_VERSION,
                detectorParameters=DEFAULT_PARAMETERS, method='incoming-stop-distinct-episodes-v1',
                timezone='Europe/Lisbon', bucketMinutes=BUCKET_MINUTES,
                period=dict(start=dates[0] if dates else None, end=dates[-1] if dates else None),
                coverage=coverage, **summarize(rows, coverage['analyzedDays']),
                unlocatedEvidenceCount=sum(r['from_stop_id'] is None for r in rows),
                warning=None if coverage['complete'] else 'History is incomplete. Run analyze_bunching.py --all-dates for the missing analysis.',
                evidenceNote='Distinct multi-stop candidate episodes, not confirmed incidents or predicted risk. '
                    'Evidence at a stop is assigned to its incoming section. Counts are not normalized by bus service frequency. '
                    'Do not sum section or time-bin counts: one episode can appear in several. '
                    'Historical variants match by public line, direction and ordered stop pair, not exact road alignment.')
