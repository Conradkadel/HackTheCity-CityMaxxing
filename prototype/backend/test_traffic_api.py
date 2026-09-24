from contextlib import nullcontext
from datetime import date

import pytest
from fastapi.testclient import TestClient

import app
import db
import traffic_api
from test_integration import database  # shared isolated PostgreSQL schema fixture
from test_traffic import ROAD, report, route


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0]


class Connection:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def transaction(self):
        return nullcontext()

    def execute(self, query, params=None):
        if 'first_date' in query:
            return Result([dict(first_date=date(2026, 9, 1) if self.rows else None,
                                last_date=date(2026, 9, 1) if self.rows else None,
                                days=1 if self.rows else 0, reports=len(self.rows))])
        return Result(self.rows)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(traffic_api, 'connect', lambda: Connection([report()]))
    monkeypatch.setattr(traffic_api, 'fetch_routes_geometry', lambda conn, keys: [route()])
    return TestClient(app.app)


def test_traffic_response(client):
    response = client.post('/api/traffic/routes', json={'route_keys': ['1:bus', '1:bus']})
    assert response.status_code == 200
    value = response.json()
    assert value['period']['start'] == '2026-09-01'
    assert value['method'] == 'daily-mean-reported-speed-band-v1'
    assert len(value['routes']) == 1
    assert value['routes'][0]['sections'][0]['speedRatio'] == 10.5


@pytest.mark.parametrize('keys', [[], ['invalid'], [':x'], ['1:'], ['x:y'], ['1:x'] * 101])
def test_invalid_requests(client, keys):
    assert client.post('/api/traffic/routes', json={'route_keys': keys}).status_code == 422


def test_empty_import(client, monkeypatch):
    monkeypatch.setattr(traffic_api, 'connect', lambda: Connection([]))
    value = client.post('/api/traffic/routes', json={'route_keys': ['1:bus']}).json()
    assert value['period']['reports'] == 0 and value['period']['start'] is None
    assert value['routes'][0]['sections'][0]['speedRatio'] is None


def test_missing_routes_and_large_history_are_explicit(client, monkeypatch):
    monkeypatch.setattr(traffic_api, 'MAX_GROUPS', 0)
    assert client.post('/api/traffic/routes', json={'route_keys': ['1:bus']}).status_code == 413
    monkeypatch.setattr(traffic_api, 'fetch_routes_geometry', lambda conn, keys: [])
    assert client.post('/api/traffic/routes', json={'route_keys': ['1:missing']}).status_code == 404


def test_database_aggregation(database, monkeypatch):
    with database() as conn:
        db.migrate(conn)
        for day, intensity in [('2026-09-01', '20% a 1% da velocidade de fluxo livre'),
                               ('2026-09-02', '80% a 61% da velocidade de fluxo livre')]:
            conn.execute('''INSERT INTO waze_jams
                (source_key, observed_at, operational_date, zone, geohash_6, intensity,
                 speed_kmh, latitude, longitude, geometry_wkt, source_file)
                VALUES (%s,%s,%s,'test','eyckp0',%s,10,38.73,-9.15,%s,'test.csv')''',
                (day, day + ' 08:00:00+01', day, intensity, ROAD))
    monkeypatch.setattr(traffic_api, 'connect', database)
    monkeypatch.setattr(traffic_api, 'fetch_routes_geometry', lambda conn, keys: [route()])
    response = TestClient(app.app).post('/api/traffic/routes', json={'route_keys': ['1:bus']})
    assert response.status_code == 200
    value = response.json()
    assert value['period']['days'] == 2
    assert value['routes'][0]['sections'][0]['speedRatio'] == 40.5
