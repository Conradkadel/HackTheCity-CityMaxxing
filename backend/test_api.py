"""HTTP contract tests with a fake connection; real SQL is covered separately."""
from contextlib import nullcontext
from datetime import timedelta
from fastapi.testclient import TestClient
import pytest
import app as api
from domain import selection_window

class Result:
    def __init__(self,rows):self.rows=rows
    def __iter__(self):return iter(self.rows)
    def fetchall(self):return self.rows
    def fetchone(self):return self.rows[0] if self.rows else None

class Connection:
    def __init__(self,rows):self.rows=rows;self.params=None
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def transaction(self):return nullcontext()
    def execute(self,query,params=None):
        if 'FROM active_dataset' in query:return Result([{'version_id':1}])
        if 'DISTINCT geohash_5' in query:return Result([{'geohash_5':'eycs2'}])
        if 'DISTINCT agency_id' in query:return Result([{'agency_id':'IA9T6'}])
        if query==api.OBSERVATIONS_SQL:self.params=params;return Result(self.rows)
        return Result([])

@pytest.fixture
def setup(monkeypatch):
    a,b=selection_window('2026-09-01','07:00','09:00')
    conn=Connection([dict(created_at=a-timedelta(seconds=120),received_at=a,agency_id='IA9T6',vehicle_id='001',trip_id='0002',stop_id='003',latitude=38.7,longitude=-9.1,geohash_5='eycs2',driver_id='never return')])
    monkeypatch.setattr(api,'connect',lambda:conn)
    # Not entering TestClient deliberately avoids startup migration in this unit test.
    return TestClient(api.app),conn,dict(date='2026-09-01',start='07:00',end='09:00',area='eycs2',operator='IA9T6')

def test_http_contract(setup):
    client,conn,params=setup
    result=client.get('/api/observations',params=params)
    assert result.status_code==200
    d=result.json();o=d['observations'][0]
    assert o['vehicleId']=='001' and o['geohash']=='eycs2'
    assert 'driver' not in result.text and 'never return' not in result.text
    assert conn.params[3]==selection_window(params['date'],params['start'],params['end'])[0]-timedelta(seconds=120)
    conn.rows=[]
    assert client.get('/api/observations',params=params).json()['observations']==[]

def test_limits_and_invalid_queries(setup,monkeypatch):
    client,conn,params=setup
    for changes in ({'area':'unknown'},{'date':'nonsense'},{'end':'14:00'},{'operator':'x'},{'start':'07:00:00'}):
        assert client.get('/api/observations',params={**params,**changes}).status_code==422
    assert client.get('/api/observations').status_code==422
    monkeypatch.setattr(api,'MAX_ROWS',0)
    assert client.get('/api/observations',params=params).status_code==413

def test_schedule_requires_route_and_completed_data(setup):
    client,_,params=setup
    assert client.get('/api/observations',params={**params,'schedule_mode':'true'}).status_code==422
    assert client.get('/api/observations',params={**params,'schedule_mode':'true','route_id':'1218','preview':'true'}).status_code==422
