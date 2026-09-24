from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from line_day import build_line_day


DAY = date(2026, 9, 1)
LISBON = ZoneInfo('Europe/Lisbon')


def run(vehicle, trip, first):
    return {
        'vehicle_id': vehicle,
        'trip_id': trip,
        'package_id': 8,
        'route_id': '118_0',
        'direction_id': '0',
        'route_long_name': 'Poço do Bispo - Sete Rios',
        'first_report': first,
        'last_report': first + timedelta(minutes=40),
        'observations': 80,
    }


def schedule(trip, stop, sequence, clock):
    return {
        'package_id': 8,
        'trip_id': trip,
        'stop_id': stop,
        'stop_sequence': sequence,
        'arrival_time': clock,
        'departure_time': clock,
        'stop_name': f'Stop {stop}',
    }


def report(vehicle, trip, stop, at):
    return {
        'vehicle_id': vehicle,
        'trip_id': trip,
        'package_id': 8,
        'route_id': '118_0',
        'direction_id': '0',
        'stop_id': stop,
        'first_report': at,
        'last_report': at + timedelta(seconds=20),
        'observations': 2,
    }


def test_line_day_links_vehicle_runs_to_schedule_and_flags_convergence():
    eight = datetime(2026, 9, 1, 8, tzinfo=LISBON)
    runs = [run('2671', 'trip-a', eight), run('2762', 'trip-b', eight)]
    schedules = [
        schedule('trip-a', 'stop-1', 1, '08:00:00'),
        schedule('trip-a', 'stop-2', 2, '08:20:00'),
        schedule('trip-b', 'stop-1', 1, '08:30:00'),
        schedule('trip-b', 'stop-2', 2, '08:50:00'),
    ]
    reports = [
        report('2671', 'trip-a', 'stop-1', eight + timedelta(minutes=28)),
        report('2762', 'trip-b', 'stop-1', eight + timedelta(minutes=30)),
    ]

    result = build_line_day(DAY, 'IA9T6', '755', runs, reports, schedules)

    assert result['coverage'] == {
        'vehicles': 2,
        'runs': 2,
        'scheduledStops': 4,
        'reportedStops': 2,
        'unmatchedReportedStops': 0,
    }
    assert result['runs'][0]['scheduledStops'][0]['differenceSeconds'] == 28 * 60
    assert result['bunchingCandidates'][0]['observedGapSeconds'] == 120
    assert result['bunchingCandidates'][0]['plannedGapSeconds'] == 30 * 60


def test_line_day_keeps_runs_with_partial_or_missing_stop_matches():
    eight = datetime(2026, 9, 1, 8, tzinfo=LISBON)
    result = build_line_day(
        DAY,
        'IA9T6',
        '755',
        [run('2671', 'trip-a', eight)],
        [report('2671', 'trip-a', 'unknown', eight)],
        [schedule('trip-a', 'stop-1', 1, '08:00:00')],
    )

    assert len(result['runs']) == 1
    assert result['runs'][0]['reportedStops'] == 0
    assert result['coverage']['unmatchedReportedStops'] == 1
    assert result['warnings']
