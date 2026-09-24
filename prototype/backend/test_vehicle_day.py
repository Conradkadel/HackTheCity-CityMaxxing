from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from vehicle_day import summarize_vehicle_day


def row(at, *, line='755', trip='trip-a', stop='stop-1', area='eyckp'):
    return {
        'created_at': at,
        'received_at': at,
        'agency_id': 'IA9T6',
        'vehicle_id': 'bus-1',
        'trip_id': trip,
        'stop_id': stop,
        'latitude': 38.7,
        'longitude': -9.1,
        'geohash_5': area,
        'package_id': 4,
        'route_id': f'route-{line}' if line else None,
        'direction_id': '0',
        'line_short_name': line,
        'route_long_name': f'Route {line}',
        'stop_sequence': 3 if stop else None,
        'arrival_time': '08:00:00' if stop else None,
        'departure_time': '08:00:00' if stop else None,
        'stop_name': 'Example stop' if stop else None,
    }


def test_vehicle_day_exposes_line_changes_gaps_and_stop_comparisons():
    start = datetime(2026, 9, 1, 7, 59, tzinfo=ZoneInfo('Europe/Lisbon'))
    rows = [
        row(start),
        row(start + timedelta(seconds=30)),
        row(start + timedelta(minutes=5), line='28E', trip='trip-b',
            stop='stop-2', area='eyckr'),
        row(start + timedelta(minutes=6), line=None, trip='', stop=''),
    ]

    result = summarize_vehicle_day(
        rows, date(2026, 9, 1), 'IA9T6', 'bus-1'
    )

    assert result['vehicleId'] == 'bus-1'
    assert [line['line'] for line in result['lines']] == ['755', '28E']
    assert result['lines'][0]['observations'] == 2
    assert len(result['linePeriods']) == 3
    assert result['linePeriods'][-1]['line'] is None
    assert result['unresolvedObservations'] == 1
    assert result['gaps'] == [{
        'start': int((start + timedelta(seconds=30)).timestamp() * 1000),
        'end': int((start + timedelta(minutes=5)).timestamp() * 1000),
        'durationSeconds': 270,
        'fromArea': 'eyckp',
        'toArea': 'eyckr',
        'fromLine': '755',
        'toLine': '28E',
        'areaChanged': True,
        'lineChanged': True,
    }]
    # Consecutive reports at the same trip/stop are one stop encounter.
    assert len(result['stopReports']) == 2
    assert result['stopReports'][0]['stopName'] == 'Example stop'
    assert result['stopReports'][0]['differenceSeconds'] == -60


def test_vehicle_day_returns_none_without_reports():
    assert summarize_vehicle_day(
        [], date(2026, 9, 1), 'IA9T6', 'missing'
    ) is None
