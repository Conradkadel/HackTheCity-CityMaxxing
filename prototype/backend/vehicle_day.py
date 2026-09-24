from datetime import date

from fastapi import APIRouter, HTTPException, Query

from db import active_version, connect
from domain import LISBON, OPERATORS, schedule_reference


router = APIRouter(prefix='/api')

VEHICLE_DAY_SQL = '''SELECT e.created_at,e.received_at,e.agency_id,e.vehicle_id,e.trip_id,e.stop_id,
 e.latitude,e.longitude,e.geohash_5,p.id AS package_id,t.route_id,t.direction_id,
 r.line_short_name,r.route_long_name,sv.stop_sequence,sv.arrival_time,sv.departure_time,
 st.data->>'stop_name' AS stop_name
 FROM vehicle_events e
 LEFT JOIN LATERAL (SELECT pp.id FROM plan_packages pp WHERE pp.event_agency_id=e.agency_id
   AND e.operational_date BETWEEN pp.active_from AND pp.active_until ORDER BY pp.id DESC LIMIT 1) p ON true
 LEFT JOIN schedule_trips t ON t.package_id=p.id AND t.trip_id=e.trip_id
 LEFT JOIN schedule_routes r ON r.package_id=t.package_id AND r.route_id=t.route_id
 LEFT JOIN LATERAL (SELECT s.stop_sequence,s.arrival_time,s.departure_time FROM schedule_stop_visits s
   WHERE s.package_id=t.package_id AND s.trip_id=t.trip_id AND s.stop_id=e.stop_id
   ORDER BY s.stop_sequence LIMIT 1) sv ON true
 LEFT JOIN LATERAL (SELECT pr.data FROM plan_records pr WHERE pr.package_id=t.package_id
   AND pr.table_name='stops' AND pr.data->>'stop_id'=e.stop_id ORDER BY pr.row_number LIMIT 1) st ON true
 WHERE e.version_id=%s AND e.agency_id=%s AND e.vehicle_id=%s AND e.operational_date=%s
 ORDER BY e.created_at,e.received_at,e.observation_key'''


def timestamp(value):
    return int(value.timestamp() * 1000)


def line_mode(line):
    return 'tram' if line in {'12E', '15E', '18E', '24E', '25E', '28E'} else 'bus'


def route_for(row):
    if not row.get('route_id'):
        return None
    return {
        'packageId': row['package_id'],
        'routeId': row['route_id'],
        'line': row['line_short_name'],
        'routeName': row['route_long_name'],
        'directionId': row['direction_id'],
        'mode': line_mode(row['line_short_name']),
    }


def schedule_for(row, route):
    if not route or row.get('stop_sequence') is None:
        return None
    clock = row.get('departure_time') or row.get('arrival_time')
    scheduled = schedule_reference(row['created_at'], clock)
    return {
        **route,
        'stopSequence': row['stop_sequence'],
        'scheduledTime': timestamp(scheduled) if scheduled else None,
        'reportedStopDifferenceSeconds': (
            round((row['created_at'] - scheduled).total_seconds()) if scheduled else None
        ),
    }


def summarize_vehicle_day(rows, day, operator_id, vehicle_id):
    if not rows:
        return None

    line_summaries = {}
    line_periods = []
    gaps = []
    stop_reports = []
    current_period = None
    current_stop_key = None

    previous = None
    for row in rows:
        route = route_for(row)
        schedule = schedule_for(row, route)
        line = route['line'] if route else None
        stamp = timestamp(row['created_at'])

        if route:
            summary = line_summaries.setdefault(line, {
                'line': line,
                'mode': route['mode'],
                'routes': set(),
                'trips': set(),
                'observations': 0,
                'firstReport': stamp,
                'lastReport': stamp,
            })
            summary['routes'].add(route['routeId'])
            if row['trip_id']:
                summary['trips'].add(row['trip_id'])
            summary['observations'] += 1
            summary['lastReport'] = stamp

        period_key = (line, row['trip_id'] or None)
        if current_period is None or current_period['_key'] != period_key:
            if current_period is not None:
                current_period.pop('_key')
                line_periods.append(current_period)
            current_period = {
                '_key': period_key,
                'line': line,
                'routeId': route['routeId'] if route else None,
                'tripId': row['trip_id'] or None,
                'start': stamp,
                'end': stamp,
                'observations': 1,
                'startArea': row['geohash_5'],
                'endArea': row['geohash_5'],
            }
        else:
            current_period['end'] = stamp
            current_period['observations'] += 1
            current_period['endArea'] = row['geohash_5']

        if previous is not None:
            seconds = round((row['created_at'] - previous['created_at']).total_seconds())
            if seconds > 120:
                previous_route = route_for(previous)
                gaps.append({
                    'start': timestamp(previous['created_at']),
                    'end': stamp,
                    'durationSeconds': seconds,
                    'fromArea': previous['geohash_5'],
                    'toArea': row['geohash_5'],
                    'fromLine': previous_route['line'] if previous_route else None,
                    'toLine': line,
                    'areaChanged': previous['geohash_5'] != row['geohash_5'],
                    'lineChanged': (previous_route['line'] if previous_route else None) != line,
                })

        stop_key = (row['trip_id'], row['stop_id']) if row['stop_id'] else None
        if schedule and stop_key != current_stop_key:
            stop_reports.append({
                'reportedTime': stamp,
                'tripId': row['trip_id'],
                'stopId': row['stop_id'],
                'stopName': row.get('stop_name') or None,
                'line': line,
                'routeId': route['routeId'],
                'directionId': route['directionId'],
                'stopSequence': schedule['stopSequence'],
                'scheduledTime': schedule['scheduledTime'],
                'differenceSeconds': schedule['reportedStopDifferenceSeconds'],
            })
        current_stop_key = stop_key
        previous = row

    if current_period is not None:
        current_period.pop('_key', None)
        line_periods.append(current_period)

    lines = []
    for summary in line_summaries.values():
        summary['routes'] = sorted(summary['routes'])
        summary['trips'] = sorted(summary['trips'])
        lines.append(summary)
    lines.sort(key=lambda item: (item['firstReport'], item['line']))

    first, last = rows[0], rows[-1]
    return {
        'date': day.isoformat(),
        'operatorId': operator_id,
        'operatorName': OPERATORS.get(operator_id, operator_id),
        'vehicleId': vehicle_id,
        'firstReport': timestamp(first['created_at']),
        'lastReport': timestamp(last['created_at']),
        'observations': len(rows),
        'unresolvedObservations': sum(not row.get('route_id') for row in rows),
        'areas': sorted({row['geohash_5'] for row in rows}),
        'lines': lines,
        'linePeriods': line_periods,
        'gaps': gaps,
        'stopReports': stop_reports,
        'gapThresholdSeconds': 120,
    }


@router.get('/vehicles/{operator_id}/{vehicle_id}/day')
def vehicle_day(operator_id: str, vehicle_id: str, date_value: date = Query(..., alias='date')):
    if not operator_id or len(operator_id) > 100 or not vehicle_id or len(vehicle_id) > 200:
        raise HTTPException(422, 'Invalid operator or vehicle identifier.')
    with connect() as conn:
        with conn.transaction():
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            conn.execute("SET LOCAL statement_timeout='30s'")
            version = active_version(conn)
            if version is None:
                raise HTTPException(503, 'No completed vehicle dataset is available.')
            rows = conn.execute(
                VEHICLE_DAY_SQL, (version, operator_id, vehicle_id, date_value)
            ).fetchall()
    result = summarize_vehicle_day(rows, date_value, operator_id, vehicle_id)
    if result is None:
        raise HTTPException(404, 'No reports found for this vehicle on this operational day.')
    return result
