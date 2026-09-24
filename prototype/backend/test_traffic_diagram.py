from datetime import date
import json

import pytest
from fastapi.testclient import TestClient

import app
import db
import traffic_diagram as traffic
from test_integration import database
from test_traffic import report


SHAPE = [[38.73, -9.15], [38.73, -9.145], [38.735, -9.145]]
STOPS = [dict(stop_id='a', stop_sequence=1, name='A', lat=38.73, lon=-9.15),
         dict(stop_id='b', stop_sequence=2, name='B', lat=38.735, lon=-9.145)]


def timed(minute=480, **kwargs):
    return dict(report(**kwargs), minute=minute)


def test_time_bands_and_equal_day_weighting():
    rows = [timed(reports=100), timed(day=date(2026, 9, 2),
            intensity='40% a 21% da velocidade de fluxo livre'),
            timed(minute=1080, intensity='80% a 61% da velocidade de fluxo livre')]
    sections, ignored = traffic.diagram_sections(STOPS, SHAPE, rows)
    morning, evening = sections[0]['cells']
    assert ignored == 0
    assert morning['minute'] == 480 and morning['speedRatio'] == 20.5
    assert morning['days'] == 2 and morning['reports'] == 101
    assert 0 < morning['coverage'] < 1
    assert evening['minute'] == 1080 and evening['speedRatio'] == 70.5
    # Long matched geometry must not multiply report counts at every 25m piece.
    assert evening['reports'] == 1


def test_matches_bent_road_instead_of_chord_between_stops():
    row = timed(geometry='LINESTRING(-9.145 38.731, -9.145 38.734)')
    sections, _ = traffic.diagram_sections(STOPS, SHAPE, [row])
    assert sections[0]['cells'][0]['speedRatio'] == 10.5
    assert sections[0]['lengthMeters'] > 900


def test_missing_geometry_coordinates_and_history_remain_unknown():
    assert traffic.diagram_sections(STOPS, [], [timed()])[0][0]['geometryAvailable'] is False
    stops = [dict(STOPS[0], lat=None), STOPS[1]]
    assert traffic.diagram_sections(stops, SHAPE, [timed()])[0][0]['cells'] == []
    assert traffic.diagram_sections(STOPS, SHAPE, [])[0][0]['cells'] == []


def test_closed_loop_stop_returns_to_end_of_shape():
    shape = [*SHAPE, [38.735, -9.15], SHAPE[0]]
    stops = [STOPS[0], STOPS[1], dict(STOPS[0], stop_sequence=3)]
    paths = traffic.stop_paths(stops, shape)
    assert len(paths) == 2 and all(paths)
    assert sum(p[2] for p in paths[1]) > 900


@pytest.mark.parametrize('extra', [{'package_id': 1}, {'trip_id': 't'}, {'package_id': -1, 'trip_id': 't'}])
def test_invalid_exact_trip_request(extra):
    response = TestClient(app.app).post('/api/traffic/diagram', json={
        'date': '2026-09-01', 'agency': 'IA9T6', 'line': '755', 'direction': '0', **extra})
    assert response.status_code == 422


def test_database_timezones_shape_and_exact_trip(database, monkeypatch):
    with database() as conn:
        db.migrate(conn)
        pid = conn.execute('''INSERT INTO plan_packages
            (source_name,checksum,agency,feed,counts,event_agency_id,active_from,active_until)
            VALUES ('test','test','[]','{}','{}','test','2026-01-01','2026-12-31') RETURNING id''').fetchone()['id']
        conn.execute("INSERT INTO schedule_routes VALUES (%s,'r','755','test','')", (pid,))
        conn.execute("INSERT INTO schedule_trips VALUES (%s,'t','r','shape','0','s')", (pid,))
        for stop in STOPS:
            conn.execute("INSERT INTO schedule_stop_visits VALUES (%s,'t',%s,%s,'08:00:00','08:00:00')",
                         (pid, stop['stop_id'], stop['stop_sequence']))
            conn.execute("INSERT INTO plan_records VALUES (%s,'stops',%s,%s::jsonb)",
                         (pid, stop['stop_sequence'], json.dumps(dict(stop_id=stop['stop_id'],
                            stop_name=stop['name'], stop_lat=stop['lat'], stop_lon=stop['lon']))))
        for i, point in enumerate(SHAPE):
            conn.execute("INSERT INTO plan_records VALUES (%s,'shapes',%s,%s::jsonb)",
                         (pid, i, json.dumps(dict(shape_id='shape', shape_pt_sequence=i,
                            shape_pt_lat=point[0], shape_pt_lon=point[1]))))
        for key, stamp, intensity in [('morning', '2026-09-01 07:10:00+00', '20% a 1% da velocidade de fluxo livre'),
                                      ('evening', '2026-09-01 17:10:00+00', '80% a 61% da velocidade de fluxo livre'),
                                      ('midnight', '2026-08-31 23:10:00+00', '20% a 1% da velocidade de fluxo livre')]:
            conn.execute('''INSERT INTO waze_jams
                (source_key,observed_at,operational_date,zone,geohash_6,intensity,latitude,longitude,geometry_wkt,source_file)
                VALUES (%s,%s,'2026-09-01','test','eyckp0',%s,38.73,-9.15,%s,'test')''',
                (key, stamp, intensity, report()['geometry_wkt']))
    monkeypatch.setattr(traffic, 'connect', database)
    client = TestClient(app.app)
    body = dict(date='2026-09-01', agency='test', line='755', direction='0')
    response = client.post('/api/traffic/diagram', json=body)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['referenceTripId'] == 't'
    assert [c['minute'] for c in value['sections'][0]['cells']] == [0, 480, 1080]
    assert value['sections'][0]['cells'][-1]['speedRatio'] == 70.5
    assert client.post('/api/traffic/diagram', json={**body, 'package_id': pid, 'trip_id': 't'}).status_code == 200
    assert client.post('/api/traffic/diagram', json={**body, 'direction': '1'}).status_code == 404
    assert client.post('/api/traffic/diagram', json={**body, 'date': '2027-01-01'}).status_code == 404
    monkeypatch.setattr(traffic, 'MAX_GROUPS', 0)
    assert client.post('/api/traffic/diagram', json=body).status_code == 413
