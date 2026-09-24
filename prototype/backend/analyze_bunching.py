"""Precompute versioned stop-headway candidate episodes for later statistics."""

import argparse
from datetime import date, datetime, timedelta, timezone

from psycopg.types.json import Jsonb

from bunching_analysis import DEFAULT_PARAMETERS, DETECTOR_VERSION, group_candidates
from db import active_version, connect
from line_day import RUNS_SQL, SCHEDULE_SQL, STOP_REPORTS_SQL, build_line_day


UNBOUNDED_QUERY_LIMIT = 2_147_483_647


def timestamp(value):
    return datetime.fromtimestamp(value / 1000, timezone.utc)


def available_lines(conn, version, day, operator_id):
    return [row['line_short_name'] for row in conn.execute('''
      SELECT DISTINCT r.line_short_name
      FROM vehicle_events e
      JOIN plan_packages p ON p.event_agency_id=e.agency_id
        AND e.operational_date BETWEEN p.active_from AND p.active_until
      JOIN schedule_trips t ON t.package_id=p.id AND t.trip_id=e.trip_id
      JOIN schedule_routes r ON r.package_id=t.package_id AND r.route_id=t.route_id
      WHERE e.version_id=%s AND e.operational_date=%s AND e.agency_id=%s
      ORDER BY r.line_short_name
    ''', (version, day, operator_id))]


def analyze_line(conn, version, day, operator_id, line):
    params = (version, day, operator_id, line)
    runs = conn.execute(RUNS_SQL, (*params, UNBOUNDED_QUERY_LIMIT)).fetchall()
    reports = conn.execute(
        STOP_REPORTS_SQL, (*params, UNBOUNDED_QUERY_LIMIT)
    ).fetchall()
    pairs = sorted({(row['package_id'], row['trip_id']) for row in runs})
    schedules = []
    if pairs:
        schedules = conn.execute(
            SCHEDULE_SQL,
            ([pair[0] for pair in pairs], [pair[1] for pair in pairs]),
        ).fetchall()
    return build_line_day(day, operator_id, line, runs, reports, schedules)


def insert_episode(conn, run_id, operator_id, line, episode):
    package_ids = {item['packageId'] for item in episode['evidence']}
    if len(package_ids) != 1:
        raise ValueError('An episode cannot span operation-plan packages.')
    row = conn.execute('''INSERT INTO bunching_episodes(
      analysis_run_id,operator_id,public_line,package_id,route_id,direction_id,
      vehicle_a_id,trip_a_id,vehicle_b_id,trip_b_id,started_at,ended_at,
      first_stop_id,first_stop_name,last_stop_id,last_stop_name,evidence_count,
      distinct_stop_count,minimum_observed_gap_seconds,maximum_planned_gap_seconds,
      classification,latitude,longitude)
      VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
      RETURNING id''', (
        run_id, operator_id, line, package_ids.pop(), episode['routeId'],
        episode['directionId'], episode['vehicleAId'], episode['tripAId'],
        episode['vehicleBId'], episode['tripBId'], timestamp(episode['startedAt']),
        timestamp(episode['endedAt']), episode['firstStopId'],
        episode['firstStopName'], episode['lastStopId'], episode['lastStopName'],
        episode['evidenceCount'], episode['distinctStopCount'],
        episode['minimumObservedGapSeconds'], episode['maximumPlannedGapSeconds'],
        episode['classification'], episode['latitude'], episode['longitude'],
    )).fetchone()
    for sequence, evidence in enumerate(episode['evidence'], 1):
        conn.execute('''INSERT INTO bunching_evidence(
          episode_id,evidence_sequence,stop_id,stop_name,stop_sequence,
          first_vehicle_id,first_trip_id,second_vehicle_id,second_trip_id,
          first_reported_at,second_reported_at,first_scheduled_at,second_scheduled_at,
          observed_gap_seconds,planned_gap_seconds,latitude,longitude)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''', (
            row['id'], sequence, evidence['stopId'], evidence['stopName'],
            evidence['stopSequence'], evidence['firstVehicleId'],
            evidence['firstTripId'], evidence['secondVehicleId'],
            evidence['secondTripId'], timestamp(evidence['firstReportedTime']),
            timestamp(evidence['secondReportedTime']),
            timestamp(evidence['firstScheduledTime']),
            timestamp(evidence['secondScheduledTime']),
            evidence['observedGapSeconds'], evidence['plannedGapSeconds'],
            evidence.get('latitude'), evidence.get('longitude'),
        ))


def analyze_operator(conn, day, operator_id, selected_lines=None,
                     detector_version=DETECTOR_VERSION, parameters=None):
    version = active_version(conn)
    if version is None:
        raise ValueError('No completed active dataset is available.')
    parameters = {**DEFAULT_PARAMETERS, **(parameters or {})}
    scope = 'selected_lines' if selected_lines else 'all_observed_lines'
    lines = sorted(set(selected_lines or available_lines(
        conn, version, day, operator_id
    )))
    run = conn.execute('''INSERT INTO analysis_runs(
      dataset_version,operational_date,operator_id,detector_version,scope,
      selected_lines,parameters,status)
      VALUES(%s,%s,%s,%s,%s,%s,%s,'running') RETURNING id''',
      (version, day, operator_id, detector_version, scope, lines,
       Jsonb(parameters))).fetchone()
    counts = {'lines': len(lines), 'rawCandidates': 0, 'episodes': 0,
              'multiStopCandidates': 0, 'singlePointEpisodes': 0}
    try:
        with conn.transaction():
            for line in lines:
                result = analyze_line(conn, version, day, operator_id, line)
                candidates = result['bunchingCandidates']
                episodes = group_candidates(
                    candidates,
                    parameters['maximumEvidenceGapSeconds'],
                    parameters['minimumDistinctStops'],
                )
                counts['rawCandidates'] += len(candidates)
                counts['episodes'] += len(episodes)
                counts['multiStopCandidates'] += sum(
                    item['classification'] == 'multi_stop_candidate'
                    for item in episodes
                )
                counts['singlePointEpisodes'] += sum(
                    item['classification'] == 'single_point'
                    for item in episodes
                )
                for episode in episodes:
                    insert_episode(conn, run['id'], operator_id, line, episode)
            conn.execute('''UPDATE analysis_runs SET status='completed',
              completed_at=now(),counts=%s WHERE id=%s''', (Jsonb(counts), run['id']))
    except Exception as exc:
        conn.execute('''UPDATE analysis_runs SET status='failed',completed_at=now(),
          error_message=%s WHERE id=%s''', (str(exc)[:2000], run['id']))
        raise
    return {'runId': run['id'], 'datasetVersion': version,
            'operatorId': operator_id, 'date': day.isoformat(),
            'scope': scope, **counts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    date_group = parser.add_mutually_exclusive_group(required=True)
    date_group.add_argument('--date', type=date.fromisoformat)
    date_group.add_argument('--week-containing', type=date.fromisoformat)
    date_group.add_argument('--all-dates', action='store_true', help='Analyze every imported operational date in the active dataset.')
    parser.add_argument('--operator', action='append', dest='operators')
    parser.add_argument('--line', action='append', dest='lines')
    parser.add_argument('--detector-version', default=DETECTOR_VERSION)
    parser.add_argument('--skip-completed', action='store_true', help='Skip days/operators already analyzed with the same detector and parameters.')
    args = parser.parse_args()
    with connect() as conn:
        initial_version = active_version(conn)
        if initial_version is None:
            raise ValueError('No completed active dataset is available.')
        if args.all_dates:
            days = [row['operational_date'] for row in conn.execute('''
                SELECT DISTINCT e.operational_date FROM vehicle_events e
                JOIN active_dataset d ON d.version_id=e.version_id
                WHERE (%s::text[] IS NULL OR e.agency_id=ANY(%s::text[])) ORDER BY e.operational_date
            ''', (args.operators, args.operators))]
        elif args.week_containing:
            monday = args.week_containing - timedelta(
                days=args.week_containing.weekday()
            )
            days = [monday + timedelta(days=offset) for offset in range(7)]
        else:
            days = [args.date]
        for day in days:
            operators = args.operators or [
                row['agency_id'] for row in conn.execute('''
                  SELECT DISTINCT agency_id FROM vehicle_events e
                  JOIN active_dataset d ON d.version_id=e.version_id
                  WHERE e.operational_date=%s ORDER BY agency_id''', (day,))
            ]
            for operator_id in operators:
                if active_version(conn) != initial_version:
                    raise RuntimeError('Active dataset changed during analysis. Restart the command for the new dataset.')
                if args.skip_completed and analysis_is_complete(conn, day, operator_id, args.lines, args.detector_version):
                    print({'date': day.isoformat(), 'operatorId': operator_id, 'skipped': True}, flush=True)
                    continue
                print(analyze_operator(
                    conn, day, operator_id, args.lines, args.detector_version
                ), flush=True)


def analysis_is_complete(conn, day, operator_id, lines, detector_version=DETECTOR_VERSION):
    rows = conn.execute('''SELECT scope,selected_lines FROM analysis_runs
        WHERE dataset_version=%s AND operational_date=%s AND operator_id=%s
          AND detector_version=%s AND parameters=%s AND status='completed'
    ''', (active_version(conn), day, operator_id, detector_version, Jsonb(DEFAULT_PARAMETERS))).fetchall()
    if any(r['scope'] == 'all_observed_lines' for r in rows):
        return True
    return bool(lines) and set(lines) <= {line for r in rows for line in r['selected_lines']}


if __name__ == '__main__':
    main()
