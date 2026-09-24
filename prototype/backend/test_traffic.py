from datetime import date

import pytest

from traffic import TrafficIndex, parse_linestring, speed_ratio


ROAD = 'LINESTRING(-9.15 38.73, -9.145 38.73)'


def report(geometry=ROAD, intensity='20% a 1% da velocidade de fluxo livre',
           day=date(2026, 9, 1), reports=1, speed=5):
    return dict(geometry_wkt=geometry, intensity=intensity, operational_date=day,
                reports=reports, speed_kmh=speed)


def route(points=None, shape_id='road'):
    return dict(key='1:bus', shapes=[dict(shape_id=shape_id, direction_id='0',
                points=points or [[38.73, -9.15], [38.73, -9.145]])])


def test_source_bands_and_unknown_intensity():
    assert speed_ratio(' 80% a 61% da velocidade de fluxo livre ') == 70.5
    assert speed_ratio('40% a 21% da velocidade de fluxo livre') == 30.5
    assert speed_ratio('Estrada bloqueada') == 0
    assert speed_ratio('unknown') is None
    assert speed_ratio('80% a 1% da velocidade de fluxo livre') is None


@pytest.mark.parametrize('wkt', ['POINT(-9 38)', 'LINESTRING EMPTY',
                                'LINESTRING(1 2 3, 2 3 4)', 'LINESTRING(NaN 1, 2 3)',
                                'LINESTRING(-9 91, -9 38)', 'LINESTRING(x y)'])
def test_invalid_geometry_is_not_matched(wkt):
    assert parse_linestring(wkt) == []


def test_reversed_geometry_and_full_route_match():
    index = TrafficIndex([report(geometry='LINESTRING(-9.145 38.73, -9.15 38.73)')])
    result = index.route(route())
    assert result['matchedMeters'] == result['totalMeters']
    assert result['sections'][0]['speedRatio'] == 10.5
    assert result['sections'][0]['points'][0] == [38.73, -9.15]
    assert result['sections'][-1]['points'][-1] == [38.73, -9.145]
    assert all(s['reports'] == 1 for s in result['sections'])


def test_daily_means_do_not_let_frequent_reporting_dominate():
    index = TrafficIndex([report(reports=100), report(day=date(2026, 9, 2),
        intensity='80% a 61% da velocidade de fluxo livre', speed=35)])
    section = index.route(route())['sections'][0]
    assert section['speedRatio'] == 40.5
    assert section['speedKmh'] == 20
    assert section['reports'] == 101 and section['days'] == 2


def test_crossing_streets_and_distant_parallel_roads_are_unknown():
    index = TrafficIndex([report()])
    crossing = route([[38.729, -9.1475], [38.731, -9.1475]])
    parallel = route([[38.731, -9.15], [38.731, -9.145]])
    for candidate in (crossing, parallel):
        result = index.route(candidate)
        assert result['matchedMeters'] == 0
        assert all(s['speedRatio'] is None for s in result['sections'])


def test_long_shape_edges_split_into_known_and_unknown_sections():
    result = TrafficIndex([report()]).route(route([[38.73, -9.155], [38.73, -9.14]]))
    assert 0 < result['matchedMeters'] < result['totalMeters']
    assert result['sections'][0]['speedRatio'] is None
    assert result['sections'][-1]['speedRatio'] is None
    assert any(s['speedRatio'] == 10.5 for s in result['sections'])


def test_no_data_and_stop_fallback_stay_unknown():
    assert TrafficIndex([]).route(route())['matchedMeters'] == 0
    assert TrafficIndex([report()]).route(route(shape_id='stops-0'))['matchedMeters'] == 0
    index = TrafficIndex([report(intensity='unrecognized', reports=7)])
    assert index.ignored_reports == 7
    assert index.route(route())['matchedMeters'] == 0


def test_duplicate_points_and_absent_speed_are_safe():
    result = TrafficIndex([report(speed=None)]).route(route([[38.73, -9.15], [38.73, -9.15], [38.73, -9.145]]))
    assert result['sections'][0]['speedKmh'] is None
    assert result['sections'][0]['speedRatio'] == 10.5


def test_missing_speed_values_do_not_inflate_speed_weight():
    first = dict(report(reports=100, speed=5), speed_reports=1)
    second = dict(report(intensity='80% a 61% da velocidade de fluxo livre', speed=35), speed_reports=1)
    section = TrafficIndex([first, second]).route(route())['sections'][0]
    assert section['speedKmh'] == 20
    assert section['reports'] == 101
