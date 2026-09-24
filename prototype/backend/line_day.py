"""Observed vehicle runs compared with their date-valid planned stop schedules."""

from collections import defaultdict
from datetime import date

from fastapi import APIRouter, HTTPException, Query

from db import active_version, connect
from domain import OPERATORS
from schedule import service_timestamp


router = APIRouter(prefix='/api')
MAX_RUNS = 500
MAX_STOP_REPORTS = 50_000
BUNCHING_OBSERVED_SECONDS = 180
BUNCHING_MIN_PLANNED_SECONDS = 300

RUNS_SQL = '''SELECT e.vehicle_id,e.trip_id,p.id AS package_id,t.route_id,
 t.direction_id,r.route_long_name,min(e.created_at) AS first_report,
 max(e.created_at) AS last_report,count(*) AS observations
 FROM vehicle_events e
 JOIN plan_packages p ON p.event_agency_id=e.agency_id
   AND e.operational_date BETWEEN p.active_from AND p.active_until
 JOIN schedule_trips t ON t.package_id=p.id AND t.trip_id=e.trip_id
 JOIN schedule_routes r ON r.package_id=t.package_id AND r.route_id=t.route_id
 WHERE e.version_id=%s AND e.operational_date=%s AND e.agency_id=%s
   AND r.line_short_name=%s
 GROUP BY e.vehicle_id,e.trip_id,p.id,t.route_id,t.direction_id,r.route_long_name
 ORDER BY first_report,e.vehicle_id,e.trip_id
 LIMIT %s'''

STOP_REPORTS_SQL = '''SELECT e.vehicle_id,e.trip_id,p.id AS package_id,t.route_id,
 t.direction_id,e.stop_id,min(e.created_at) AS first_report,
 max(e.created_at) AS last_report,count(*) AS observations
 FROM vehicle_events e
 JOIN plan_packages p ON p.event_agency_id=e.agency_id
   AND e.operational_date BETWEEN p.active_from AND p.active_until
 JOIN schedule_trips t ON t.package_id=p.id AND t.trip_id=e.trip_id
 JOIN schedule_routes r ON r.package_id=t.package_id AND r.route_id=t.route_id
 WHERE e.version_id=%s AND e.operational_date=%s AND e.agency_id=%s
   AND r.line_short_name=%s AND e.stop_id<>''
 GROUP BY e.vehicle_id,e.trip_id,p.id,t.route_id,t.direction_id,e.stop_id
 ORDER BY first_report,e.vehicle_id,e.trip_id,e.stop_id
 LIMIT %s'''

SCHEDULE_SQL = '''SELECT v.package_id,v.trip_id,v.stop_id,v.stop_sequence,
 v.arrival_time,v.departure_time,
 COALESCE(s.data->>'stop_name',v.stop_id) AS stop_name,
 NULLIF(s.data->>'stop_lat','')::double precision AS latitude,
 NULLIF(s.data->>'stop_lon','')::double precision AS longitude
 FROM schedule_stop_visits v
 LEFT JOIN LATERAL (
   SELECT pr.data FROM plan_records pr
   WHERE pr.package_id=v.package_id AND pr.table_name='stops'
     AND pr.data->>'stop_id'=v.stop_id
   ORDER BY pr.row_number LIMIT 1
 ) s ON true
 WHERE (v.package_id,v.trip_id) IN (
   SELECT * FROM UNNEST(%s::bigint[],%s::text[])
 )
 ORDER BY v.package_id,v.trip_id,v.stop_sequence'''


def milliseconds(value):
    return int(value.timestamp() * 1000) if value is not None else None


def line_mode(line):
    return 'tram' if line in {'12E', '15E', '18E', '24E', '25E', '28E'} else 'bus'


def build_line_day(day, operator_id, line, run_rows, report_rows, schedule_rows):
    schedules = defaultdict(list)
    for row in schedule_rows:
        clock = row.get('departure_time') or row.get('arrival_time')
        planned = service_timestamp(day, clock)
        stop = {
            'stopId': row['stop_id'],
            'stopName': row.get('stop_name') or row['stop_id'],
            'stopSequence': row['stop_sequence'],
            'arrivalTime': row.get('arrival_time') or '',
            'departureTime': row.get('departure_time') or '',
            'scheduledTime': milliseconds(planned),
            'reportedTime': None,
            'differenceSeconds': None,
            'reportObservations': 0,
            'latitude': row.get('latitude'),
            'longitude': row.get('longitude'),
        }
        key = (row['package_id'], row['trip_id'])
        schedules[key].append(stop)

    run_schedules = {}
    schedule_by_stop = defaultdict(list)
    for row in run_rows:
        run_key = (row['vehicle_id'], row['package_id'], row['trip_id'])
        run_schedule = [
            dict(stop) for stop in schedules.get((row['package_id'], row['trip_id']), [])
        ]
        run_schedules[run_key] = run_schedule
        for stop in run_schedule:
            schedule_by_stop[(*run_key, stop['stopId'])].append(stop)

    reports_by_run = defaultdict(list)
    unmatched_reports = 0
    for row in report_rows:
        run_key = (row['vehicle_id'], row['package_id'], row['trip_id'])
        key = (*run_key, row['stop_id'])
        candidates = schedule_by_stop.get(key, [])
        reported_ms = milliseconds(row['first_report'])
        candidates_with_time = [
            stop for stop in candidates if stop['scheduledTime'] is not None
        ]
        if candidates_with_time:
            matched = min(
                candidates_with_time,
                key=lambda stop: abs(stop['scheduledTime'] - reported_ms),
            )
        elif candidates:
            matched = candidates[0]
        else:
            unmatched_reports += 1
            continue
        matched['reportedTime'] = reported_ms
        matched['differenceSeconds'] = (
            round((reported_ms - matched['scheduledTime']) / 1000)
            if matched['scheduledTime'] is not None
            else None
        )
        matched['reportObservations'] = row['observations']
        reports_by_run[run_key].append(matched)

    runs = []
    for row in run_rows:
        run_key = (row['vehicle_id'], row['package_id'], row['trip_id'])
        schedule = run_schedules.get(run_key, [])
        reported = reports_by_run.get(run_key, [])
        planned_times = [
            stop['scheduledTime']
            for stop in schedule
            if stop['scheduledTime'] is not None
        ]
        runs.append({
            'vehicleId': row['vehicle_id'],
            'tripId': row['trip_id'],
            'packageId': row['package_id'],
            'routeId': row['route_id'],
            'routeName': row.get('route_long_name') or line,
            'directionId': row['direction_id'],
            'firstReport': milliseconds(row['first_report']),
            'lastReport': milliseconds(row['last_report']),
            'observations': row['observations'],
            'scheduledStart': min(planned_times) if planned_times else None,
            'scheduledEnd': max(planned_times) if planned_times else None,
            'scheduledStops': schedule,
            'reportedStops': len(reported),
        })

    encounters = defaultdict(list)
    for run in runs:
        for stop in run['scheduledStops']:
            if stop['reportedTime'] is None or stop['scheduledTime'] is None:
                continue
            encounters[(run['routeId'], run['directionId'], stop['stopId'])].append({
                'packageId': run['packageId'],
                'vehicleId': run['vehicleId'],
                'tripId': run['tripId'],
                'stopId': stop['stopId'],
                'stopName': stop['stopName'],
                'stopSequence': stop['stopSequence'],
                'scheduledTime': stop['scheduledTime'],
                'reportedTime': stop['reportedTime'],
                'directionId': run['directionId'],
                'routeId': run['routeId'],
                'latitude': stop.get('latitude'),
                'longitude': stop.get('longitude'),
            })

    candidates = []
    for stop_encounters in encounters.values():
        stop_encounters.sort(key=lambda encounter: encounter['reportedTime'])
        for first, second in zip(stop_encounters, stop_encounters[1:]):
            if first['tripId'] == second['tripId']:
                continue
            observed_gap = abs(second['reportedTime'] - first['reportedTime']) // 1000
            planned_gap = abs(second['scheduledTime'] - first['scheduledTime']) // 1000
            if (
                observed_gap <= BUNCHING_OBSERVED_SECONDS
                and planned_gap >= BUNCHING_MIN_PLANNED_SECONDS
            ):
                candidates.append({
                    'stopId': first['stopId'],
                    'stopName': first['stopName'],
                    'stopSequence': first['stopSequence'],
                    'directionId': first['directionId'],
                    'routeId': first['routeId'],
                    'packageId': first['packageId'],
                    'firstVehicleId': first['vehicleId'],
                    'firstTripId': first['tripId'],
                    'secondVehicleId': second['vehicleId'],
                    'secondTripId': second['tripId'],
                    'firstReportedTime': first['reportedTime'],
                    'secondReportedTime': second['reportedTime'],
                    'firstScheduledTime': first['scheduledTime'],
                    'secondScheduledTime': second['scheduledTime'],
                    'observedGapSeconds': observed_gap,
                    'plannedGapSeconds': planned_gap,
                    'latitude': first.get('latitude'),
                    'longitude': first.get('longitude'),
                })
    candidates.sort(key=lambda item: item['firstReportedTime'])

    warnings = []
    if not runs:
        warnings.append('No date-valid matched vehicle trips were found for this line and day.')
    if any(not run['scheduledStops'] for run in runs):
        warnings.append('Some matched trips have no normalized scheduled-stop rows.')
    if unmatched_reports:
        warnings.append(
            f'{unmatched_reports} reported stop identifiers did not match the trip schedule.'
        )

    return {
        'date': day.isoformat(),
        'operatorId': operator_id,
        'operatorName': OPERATORS.get(operator_id, operator_id),
        'line': line,
        'mode': line_mode(line),
        'runs': runs,
        'bunchingCandidates': candidates,
        'thresholds': {
            'maximumObservedGapSeconds': BUNCHING_OBSERVED_SECONDS,
            'minimumPlannedGapSeconds': BUNCHING_MIN_PLANNED_SECONDS,
        },
        'coverage': {
            'vehicles': len({run['vehicleId'] for run in runs}),
            'runs': len(runs),
            'scheduledStops': sum(len(run['scheduledStops']) for run in runs),
            'reportedStops': sum(run['reportedStops'] for run in runs),
            'unmatchedReportedStops': unmatched_reports,
        },
        'warnings': warnings,
        'evidenceNote': (
            'Reported stop identifiers are observation evidence, not confirmed '
            'door-open arrival events. Candidate bunching requires reports at the '
            'same scheduled stop within three minutes where the timetable separated '
            'the trips by at least five minutes.'
        ),
    }


@router.get('/lines/{operator_id}/{line}/day')
def line_day(operator_id: str, line: str, date_value: date = Query(..., alias='date')):
    if not operator_id or len(operator_id) > 100 or not line or len(line) > 100:
        raise HTTPException(422, 'Invalid operator or public line identifier.')
    with connect() as conn:
        with conn.transaction():
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            conn.execute("SET LOCAL statement_timeout='30s'")
            version = active_version(conn)
            if version is None:
                raise HTTPException(503, 'No completed vehicle dataset is available.')
            params = (version, date_value, operator_id, line)
            run_rows = conn.execute(RUNS_SQL, (*params, MAX_RUNS + 1)).fetchall()
            if len(run_rows) > MAX_RUNS:
                raise HTTPException(
                    413,
                    f'More than {MAX_RUNS} vehicle trips match this line and day.',
                )
            report_rows = conn.execute(
                STOP_REPORTS_SQL, (*params, MAX_STOP_REPORTS + 1)
            ).fetchall()
            if len(report_rows) > MAX_STOP_REPORTS:
                raise HTTPException(
                    413,
                    'Too many stop-report groups; choose a different line or day.',
                )
            pairs = sorted({(row['package_id'], row['trip_id']) for row in run_rows})
            schedule_rows = []
            if pairs:
                schedule_rows = conn.execute(
                    SCHEDULE_SQL,
                    ([pair[0] for pair in pairs], [pair[1] for pair in pairs]),
                ).fetchall()
    return build_line_day(
        date_value, operator_id, line, run_rows, report_rows, schedule_rows
    )
