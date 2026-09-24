"""Uses an isolated temporary schema; set TEST_DATABASE_URL to run against PostgreSQL."""
import os
import shutil
import uuid
from pathlib import Path
import pytest
import psycopg
from psycopg import sql
from fastapi.testclient import TestClient
import db
import app as api
import import_vehicles as importer
import import_plans
import plans_api

def test_partial_preview_committed_only(database,tmp_path):
    source=tmp_path/'source';shutil.copytree(Path(__file__).parent/'fixtures',source)
    result=importer.run(source,batch_size=1);version=result['version']
    with database() as conn:
        conn.execute('DELETE FROM active_dataset')
        conn.execute("UPDATE dataset_versions SET status='loading' WHERE id=%s",(version,))
    params={'date':'2026-09-01','start':'07:00','end':'09:00','area':'eycs2','operator':'IA9T6','preview':'true','dataset_version':version}
    with TestClient(api.app) as client, database() as writer:
        assert client.get('/api/availability').status_code==503
        a=client.get('/api/availability?preview=true').json()
        assert a['partialPreview'] and a['importProgress']['completedFiles']==2
        assert a['dates']==['2026-09-01']
        writer.execute('BEGIN')
        writer.execute("UPDATE vehicle_events SET vehicle_id='uncommitted' WHERE version_id=%s",(version,))
        d=client.get('/api/observations',params=params).json()
        assert d['metadata']['partialPreview'] and len(d['observations'])==2
        assert all(o['vehicleId']=='001' for o in d['observations'])
        writer.execute('ROLLBACK')
        assert client.get('/api/observations',params={**params,'dataset_version':999999}).status_code==503
        assert client.get('/api/observations',params={**params,'start':'10:00','end':'11:00'}).json()['observations']==[]
        with database() as conn:
            assert db.active_version(conn) is None
            conn.execute("UPDATE dataset_versions SET status='ready' WHERE id=%s",(version,))
            conn.execute('INSERT INTO active_dataset VALUES(true,%s)',(version,))
        assert client.get('/api/availability').status_code==200
        assert client.get('/api/observations',params=params).json()['metadata']['partialPreview']

@pytest.fixture
def database(monkeypatch):
    url=os.environ.get('TEST_DATABASE_URL')
    if not url:pytest.skip('TEST_DATABASE_URL not set; PostgreSQL integration requires a running database')
    schema='test_vehicle_'+uuid.uuid4().hex
    # Test schemas need an independent importer mutex while the real import runs.
    monkeypatch.setattr(importer,'IMPORT_LOCK',int(uuid.uuid4().hex[:14],16))
    with psycopg.connect(url,autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        original=db.connect
        monkeypatch.setenv('DATABASE_URL',url)
        def connect():
            conn=original();conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)));return conn
        monkeypatch.setattr(api,'connect',connect);monkeypatch.setattr(importer,'connect',connect)
        monkeypatch.setattr(import_plans,'connect',connect);monkeypatch.setattr(plans_api,'connect',connect)
        try:yield connect
        finally:admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))

def test_import_replay_resume_and_failure(database,tmp_path,monkeypatch):
    source=tmp_path/'source';shutil.copytree(Path(__file__).parent/'fixtures',source)
    first=importer.run(source,batch_size=1)
    assert first['observations']==4
    assert importer.run(source)['unchanged']
    with database() as conn:
        event=conn.execute("SELECT * FROM vehicle_events WHERE event_id='0003'").fetchone()
        assert event['vehicle_id']=='001' and event['driver_id']=='private'
        assert conn.execute('SELECT count(*) AS n FROM event_sources').fetchone()['n']==5
        assert conn.execute("SELECT count(DISTINCT geohash_5) AS n FROM vehicle_events WHERE agency_id='IA9T6' AND vehicle_id='001'").fetchone()['n']==2
    with TestClient(api.app) as client:
        params={'date':'2026-09-01','start':'07:00','end':'09:00','area':'eycs2','operator':'IA9T6'}
        response=client.get('/api/observations',params=params);assert response.status_code==200
        data=response.json();assert len(data['observations'])==2
        assert all(o['geohash']=='eycs2' and 'driverId' not in o for o in data['observations'])
        assert data['observations'][0]['timestamp']<data['metadata']['startTimestamp']
        assert client.get('/api/observations',params={**params,'start':'10:00','end':'11:00'}).json()['observations']==[]
        assert client.get('/api/observations',params={**params,'area':'unknown'}).status_code==422
        assert client.get('/api/observations',params={**params,'end':'12:00'}).status_code==422
        monkeypatch.setattr(api,'MAX_ROWS',1)
        assert client.get('/api/observations',params=params).status_code==413
    # A second version fails in its second batch; no partially imported file commits.
    original=importer.parse_row;calls=0
    def fail(row):
        nonlocal calls
        calls+=1
        if calls==2:raise RuntimeError('injected failure after first batch')
        return original(row)
    monkeypatch.setattr(importer,'parse_row',fail)
    with pytest.raises(RuntimeError):importer.run(source,rebuild=True,batch_size=1)
    with database() as conn:
        assert db.active_version(conn)==first['version']
        assert conn.execute('SELECT count(*) AS n FROM import_files WHERE version_id<>%s',(first['version'],)).fetchone()['n']==0
    monkeypatch.setattr(importer,'parse_row',original)
    resumed=importer.run(source,batch_size=1);assert resumed['observations']==4
    def fail_second_file(row):
        if row['_id']=='0004':raise RuntimeError('second file failure')
        return original(row)
    monkeypatch.setattr(importer,'parse_row',fail_second_file)
    with pytest.raises(RuntimeError):importer.run(source,rebuild=True,batch_size=1)
    with database() as conn:
        assert db.active_version(conn)==resumed['version']
        assert conn.execute('SELECT count(*) AS n FROM import_files WHERE version_id=(SELECT max(id) FROM dataset_versions)').fetchone()['n']==1
    monkeypatch.setattr(importer,'parse_row',original)
    assert importer.run(source,batch_size=1)['observations']==4
    # Inventory changes cannot implicitly replace a usable version.
    shutil.copy(source/'a.csv',source/'extra.csv')
    with pytest.raises(ValueError,match='rebuild'):importer.run(source)
    assert importer.run(source,rebuild=True)['observations']==4

def test_operation_plans(database,tmp_path):
    source=tmp_path/'plans';p=source/'synthetic';p.mkdir(parents=True)
    files={
      'agency':'agency_id,agency_name\n43,Synthetic operator\n',
      'feed_info':'feed_start_date,feed_end_date,feed_version\n20251001,20251031,test\n',
      'routes':'route_id,route_long_name\n0001,Synthetic route\n',
      'trips':'trip_id,route_id,shape_id,direction_id,service_id\n0002,0001,s,0,weekday\n',
      'stops':'stop_id,stop_name,stop_lat,stop_lon\n0003,Synthetic stop,38.7,-9.1\n',
      'shapes':'shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence\ns,38.8,-9.2,10\ns,38.7,-9.1,2\n',
      'stop_times':'trip_id,stop_id,stop_sequence,arrival_time,departure_time\n0002,0003,10,25:10:00,25:11:00\n0002,missing,2,24:10:00,24:11:00\n',
      'calendar_dates':'service_id,date,exception_type\nweekday,20251001,1\n'}
    for name,content in files.items():(p/(name+'.txt')).write_text(content)
    import_plans.run(source);import_plans.run(source)
    with TestClient(api.app) as client:
        packages=client.get('/api/plans/packages').json();assert len(packages)==1
        pid=packages[0]['id']
        assert packages[0]['counts']['calendar_dates']==1
        assert client.get(f'/api/plans/{pid}/routes').json()[0]['route_id']=='0001'
        assert len(client.get(f'/api/plans/{pid}/trips',params={'route_id':'0001'}).json())==1
        d=client.get(f'/api/plans/{pid}/trip',params={'trip_id':'0002'}).json()
        assert d['shape']==[[38.7,-9.1],[38.8,-9.2]]
        assert d['stops'][0]['stop'] is None
        assert d['stops'][1]['stop']['stop_id']=='0003'
        assert d['stops'][1]['visit']['arrival_time']=='25:10:00'
        assert client.get(f'/api/plans/{pid}/trip',params={'trip_id':"' OR 1=1"}).status_code==404
        assert client.get('/api/plans/999999/routes').status_code==404
    # Invalid replacement is atomic; the earlier valid package remains available.
    (p/'stops.txt').write_text(files['stops'].replace('38.7','999'))
    with pytest.raises(ValueError):import_plans.run(source)
    with database() as conn:assert conn.execute('SELECT count(*) AS n FROM plan_packages').fetchone()['n']==1
