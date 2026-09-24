"""Findings view: the precomputed file is served, and stop names come from the plan when available."""
import json

import pytest
from fastapi.testclient import TestClient

import app as api
import findings_api

SAMPLE = {
    'source': {'from': '2026-08-31'},
    'problems': [{'line': '742', 'terminal': {'stop_id': 'T1', 'lat': 1.0, 'lon': 2.0},
                  'stretch': [{'stop_id': 'S1', 'lat': None, 'lon': None}], 'profile': [{'stop_id': 'S1'}]}],
    'hotspots': [{'stop_id': 'S1', 'lat': None, 'lon': None}],
    'corridors': [{'pair': '714 & 727', 'sharedStops': [{'stop_id': 'S2', 'lat': 3.0, 'lon': 4.0}]}],
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    path = tmp_path / 'findings.json'
    path.write_text(json.dumps(SAMPLE))
    monkeypatch.setattr(findings_api, 'FINDINGS', path)
    monkeypatch.setattr(findings_api, '_cache', {})
    return TestClient(api.app)


def test_findings_get_stop_names_and_plan_positions(client, monkeypatch):
    seen = {}

    def details(ids, day, agency='IA9T6'):
        seen.update(ids=ids, day=day)
        return {'S1': {'stop_id': 'S1', 'name': 'Praça X', 'lat': 38.7, 'lon': -9.1}}
    monkeypatch.setattr(findings_api, 'stop_details', details)
    body = client.get('/api/findings').json()
    assert seen == {'ids': {'T1', 'S1', 'S2'}, 'day': '2026-08-31'}
    assert body['stopNames'] is True
    assert body['hotspots'][0] == {'stop_id': 'S1', 'lat': 38.7, 'lon': -9.1, 'name': 'Praça X'}
    assert body['problems'][0]['terminal'] == {'stop_id': 'T1', 'lat': 1.0, 'lon': 2.0, 'name': None}


def test_findings_still_work_without_the_database(client, monkeypatch):
    monkeypatch.setattr(findings_api, 'stop_details', lambda ids, day, agency='IA9T6': None)
    body = client.get('/api/findings').json()
    assert body['stopNames'] is False
    assert body['corridors'][0]['sharedStops'][0] == {'stop_id': 'S2', 'lat': 3.0, 'lon': 4.0, 'name': None}
    assert findings_api._cache == {}           # the database is tried again next time


def test_missing_findings_file_explains_how_to_build_it(client, monkeypatch, tmp_path):
    monkeypatch.setattr(findings_api, 'FINDINGS', tmp_path / 'nope.json')
    response = client.get('/api/findings')
    assert response.status_code == 503 and 'build_findings.py' in response.json()['detail']
