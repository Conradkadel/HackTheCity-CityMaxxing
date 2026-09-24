from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

import app
import db
import analyze_bunching
import bunching_heatmap as heatmap
import bunching_heatmap_api as api
from bunching_analysis import DEFAULT_PARAMETERS, group_candidates
from test_bunching_analysis import candidate
from test_integration import database


STOPS = [dict(stop_id=key, name=key.upper(), stop_sequence=i+1, lat=38.73, lon=-9.15+i*0.002)
         for i, key in enumerate(('a', 'b', 'c'))]
SHAPE = [[s['lat'], s['lon']] for s in STOPS]


def evidence(episode=1, minute=480, day=date(2026, 9, 1), first='a', last='b', direction='0'):
    stamp = datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(minutes=minute-60)
    return dict(episode_id=episode, operational_date=day, direction_id=direction,
                from_stop_id=first, to_stop_id=last, first_reported_at=stamp, second_reported_at=stamp)


def test_distinct_events_per_section_and_bin_not_per_report():
    rows = [evidence(), evidence(), evidence(minute=510), evidence(first='b', last='c'), evidence(episode=2)]
    sections, mapped = heatmap.build_sections(STOPS, SHAPE, '0', {'analyzedDays': 2}, rows, True)
    assert mapped == {1, 2}
    assert sections[0]['episodeCount'] == 2
    assert sections[0]['episodesPerAnalyzedDay'] == 1
    assert sections[0]['cells'][16]['episodeCount'] == 2
    assert sections[0]['cells'][17]['episodeCount'] == 1
    assert sections[1]['episodeCount'] == 1
    assert sections[0]['cells'][0]['episodeCount'] == 0
    assert len(sections[0]['cells']) == 48
    assert sections[0]['points'][0] == SHAPE[0]


def test_unknown_history_is_not_zero_and_missing_geometry_keeps_counts():
    sections, _ = heatmap.build_sections(STOPS, [], '0', {'analyzedDays': 0}, [], True)
    assert sections[0]['episodeCount'] is None
    assert sections[0]['cells'][0]['episodeCount'] is None
    assert sections[0]['status'] == 'not_analyzed'
    sections, _ = heatmap.build_sections(STOPS, [], '0', {'analyzedDays': 1}, [evidence()], False)
    assert sections[0]['episodeCount'] == 1 and not sections[0]['geometryAvailable']


def test_wrong_direction_gaps_and_ambiguous_loop_pairs_do_not_spread_events():
    rows = [evidence(direction='1'), evidence(first='a', last='c')]
    sections, mapped = heatmap.build_sections(STOPS, SHAPE, '0', {'analyzedDays': 1}, rows, False)
    assert not mapped and all(s['episodeCount'] == 0 for s in sections)
    loop = [*STOPS, dict(STOPS[0], stop_sequence=4), dict(STOPS[1], stop_sequence=5)]
    sections, _ = heatmap.build_sections(loop, [], '0', {'analyzedDays': 1}, [evidence()], True)
    assert sections[0]['status'] == 'ambiguous_stop_pair'
    assert sections[0]['episodeCount'] is None


def test_detection_midpoint_local_time_and_midnight():
    row = evidence()
    row['first_reported_at'] = datetime(2026, 9, 1, 22, 59, tzinfo=timezone.utc)
    row['second_reported_at'] = datetime(2026, 9, 1, 23, 1, tzinfo=timezone.utc)
    assert heatmap.time_bucket(row) == 0
    row['first_reported_at'] = row['second_reported_at'] = datetime(2026, 1, 1, 8, 5, tzinfo=timezone.utc)
    assert heatmap.time_bucket(row) == 480


@pytest.fixture
def history(database, monkeypatch):
    with database() as conn:
        db.migrate(conn)
        version = conn.execute("INSERT INTO dataset_versions (inventory_hash,status,source_root) VALUES ('test','ready','test') RETURNING id").fetchone()['id']
        conn.execute('INSERT INTO active_dataset VALUES (true,%s)', (version,))
        pid = conn.execute('''INSERT INTO plan_packages
            (source_name,checksum,agency,feed,counts,event_agency_id,active_from,active_until)
            VALUES ('test','test','[]','{}','{}','test','2026-01-01','2026-12-31') RETURNING id''').fetchone()['id']
        conn.execute("INSERT INTO schedule_routes VALUES (%s,'118_0','755','test','')", (pid,))
        for trip in ('trip-a', 'trip-b'):
            conn.execute("INSERT INTO schedule_trips VALUES (%s,%s,'118_0','shape','0','s')", (pid, trip))
            for s in STOPS:
                conn.execute("INSERT INTO schedule_stop_visits VALUES (%s,%s,%s,%s,'08:00:00','08:10:00')",
                             (pid, trip, s['stop_id'], s['stop_sequence']))
        for s in STOPS:
            conn.execute("INSERT INTO plan_records VALUES (%s,'stops',%s,%s)",
                         (pid, s['stop_sequence'], Jsonb(dict(stop_id=s['stop_id'], stop_name=s['name'], stop_lat=s['lat'], stop_lon=s['lon']))))
            conn.execute("INSERT INTO plan_records VALUES (%s,'shapes',%s,%s)",
                         (pid, s['stop_sequence'], Jsonb(dict(shape_id='shape', shape_pt_sequence=s['stop_sequence'], shape_pt_lat=s['lat'], shape_pt_lon=s['lon']))))
        for day in ('2026-09-01', '2026-09-02'):
            conn.execute('''INSERT INTO vehicle_events VALUES
                (%s,%s,%s,'test','bus','private','trip-a','b',%s,%s,%s,38.73,-9.15,'eyckp')''',
                (version, day, day, day+' 08:00+01', day+' 08:00+01', day))
    monkeypatch.setattr(api, 'connect', database)
    return database, version, pid


def add_run(conn, version, pid, day='2026-09-01', lines=None, status='completed',
            parameters=None, detector='stop-headway-v1', episodes=1, scope='selected_lines'):
    run = conn.execute('''INSERT INTO analysis_runs
        (dataset_version,operational_date,operator_id,detector_version,scope,selected_lines,parameters,status,completed_at)
        VALUES (%s,%s,'test',%s,%s,%s,%s,%s,now()) RETURNING id''',
        (version, day, detector, scope, ['755'] if lines is None else lines,
         Jsonb(DEFAULT_PARAMETERS if parameters is None else parameters), status)).fetchone()['id']
    for i in range(episodes):
        stamp = int(datetime.fromisoformat(day+'T07:10:00+00:00').timestamp()*1000) + i*60000
        candidates = [dict(candidate(stop, seq, stamp+seq*60000, first_trip='trip-a'), packageId=pid)
                      for stop, seq in [('b', 2), ('c', 3)]]
        episode = group_candidates(candidates)[0]
        analyze_bunching.insert_episode(conn, run, 'test', '755', episode)
    return run


def test_latest_compatible_run_and_coverage_query(history):
    database, version, pid = history
    with database() as conn:
        add_run(conn, version, pid, episodes=3)
        chosen = add_run(conn, version, pid, episodes=1)
        add_run(conn, version, pid, status='failed', episodes=4)
        add_run(conn, version, pid, lines=['728'], episodes=4)
        add_run(conn, version, pid, parameters={**DEFAULT_PARAMETERS, 'maximumEvidenceGapSeconds': 600}, episodes=4)
        add_run(conn, version, pid, detector='future-v2', episodes=4)
        coverage, rows = heatmap.load_history(conn, version, 'test', '755')
    assert coverage['analysisRunIds'] == [chosen]
    assert coverage['analyzedDays'] == 1 and len(coverage['missingDates']) == 1
    assert len({r['episode_id'] for r in rows}) == 1
    assert {r['from_stop_id'] for r in rows} == {'a', 'b'}


def test_routes_and_diagram_contract_zero_unknown_and_active_dataset(history):
    database, version, pid = history
    client = TestClient(app.app)
    body = dict(date='2026-09-01', agency='test', line='755', direction='0')
    value = client.post('/api/bunching/heatmap/diagram', json=body).json()
    assert value['sections'][0]['episodeCount'] is None
    with database() as conn:
        add_run(conn, version, pid)
        # A complete operator run covering no observed lines is a genuine zero day.
        add_run(conn, version, pid, day='2026-09-02', lines=[], episodes=0, scope='all_observed_lines')
    response = client.post('/api/bunching/heatmap/diagram', json=body)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['coverage']['complete'] and value['episodeCount'] == 1
    assert value['sections'][0]['episodeCount'] == 1
    assert value['sections'][0]['episodesPerAnalyzedDay'] == 0.5
    assert value['sections'][0]['cells'][16]['episodeCount'] == 1
    assert value['sections'][0]['cells'][0]['episodeCount'] == 0
    response = client.post('/api/bunching/heatmap/routes', json={'route_keys': [f'{pid}:118_0']})
    assert response.status_code == 200, response.text
    value = response.json()['routes'][0]
    assert value['mappedEpisodeCount'] == 1
    assert value['shapes'][0]['sections'][0]['episodeCount'] == 1
    assert value['shapes'][0]['sections'][0]['points']
    assert 'private' not in response.text
    with database() as conn:
        other = conn.execute("INSERT INTO dataset_versions (inventory_hash,status,source_root) VALUES ('other','ready','other') RETURNING id").fetchone()['id']
        conn.execute('UPDATE active_dataset SET version_id=%s', (other,))
    value = client.post('/api/bunching/heatmap/diagram', json=body).json()
    assert value['episodeCount'] is None and value['coverage']['analyzedDays'] == 0


def test_limits_validation_and_resume(history, monkeypatch):
    database, version, pid = history
    client = TestClient(app.app)
    for keys in ([], ['bad'], ['x:y'], ['1:'], ['9'*30+':r'], ['1:r']*51):
        assert client.post('/api/bunching/heatmap/routes', json={'route_keys': keys}).status_code == 422
    assert client.post('/api/bunching/heatmap/routes', json={'route_keys': ['999:r']}).status_code == 404
    with database() as conn:
        assert not analyze_bunching.analysis_is_complete(conn, date(2026, 9, 1), 'test', ['755'])
        add_run(conn, version, pid)
        assert analyze_bunching.analysis_is_complete(conn, date(2026, 9, 1), 'test', ['755'])
        assert not analyze_bunching.analysis_is_complete(conn, date(2026, 9, 1), 'test', None)
    monkeypatch.setattr(heatmap, 'MAX_EVIDENCE', 0)
    assert client.post('/api/bunching/heatmap/routes', json={'route_keys': [f'{pid}:118_0']}).status_code == 413


def test_all_dates_command_uses_operational_dates_and_resumes(history, monkeypatch):
    database, version, pid = history
    with database() as conn:
        add_run(conn, version, pid)
    called = []
    monkeypatch.setattr(analyze_bunching, 'connect', database)
    monkeypatch.setattr(analyze_bunching, 'analyze_operator', lambda conn, day, operator, lines, detector: called.append((day, operator, lines)))
    monkeypatch.setattr('sys.argv', ['analyze_bunching.py', '--all-dates', '--operator', 'test', '--line', '755', '--skip-completed'])
    analyze_bunching.main()
    assert called == [(date(2026, 9, 2), 'test', ['755'])]


def test_single_point_candidates_are_excluded(history):
    database, version, pid = history
    with database() as conn:
        add_run(conn, version, pid)
        conn.execute("UPDATE bunching_episodes SET classification='single_point'")
        coverage, rows = heatmap.load_history(conn, version, 'test', '755')
    assert coverage['analyzedDays'] == 1 and rows == []
