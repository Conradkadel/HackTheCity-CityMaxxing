from contextlib import nullcontext
from datetime import date

import workspace_api


class Result:
    def __init__(self, rows): self.rows=rows
    def __iter__(self): return iter(self.rows)
    def fetchone(self): return self.rows[0] if self.rows else None
    def fetchall(self): return self.rows


class Connection:
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def execute(self,query,params=None):
        if 'FROM active_dataset' in query: return Result([{'version_id':4}])
        if 'sum(observations)' in query: return Result([{'geohash_5':'eyckp','agency_id':'IA9T6','observations':12}])
        if 'DISTINCT calendar_date' in query: return Result([{'calendar_date':date(2026,9,1)}])
        if 'AS agency_id' in query and 'vehicle_events' in query: return Result([{'agency_id':'IA9T6','line_short_name':'755'}])
        if 'FROM schedule_routes r' in query:
            return Result([{'package_id':8,'route_id':'118_0','line_short_name':'755','route_long_name':'Poço Bispo - Sete Rios','route_color':'ED1C24','source_name':'carris','event_agency_id':'IA9T6','agency_name':'Carris','directions':['0','1'],'trip_count':20}])
        return Result([])


def test_workspace_catalog_keeps_missing_config_visible(monkeypatch):
    monkeypatch.setattr(workspace_api,'connect',lambda:Connection())
    value=workspace_api.workspace_catalog(date(2026,9,1))
    assert value['defaultPresetId']=='carris_lisbon'
    assert value['areas']==[{'id':'eyckp','name':'Ponte 25 de Abril / Cais do Sodré / Alcântara','observations':12}]
    carris=next(p for p in value['presets'] if p['id']=='carris_lisbon')
    assert next(line for line in carris['lines'] if line['code']=='755')['vehicleAvailable']
    missing=next(line for line in carris['lines'] if line['code']=='702')
    assert not missing['planAvailable'] and not missing['vehicleAvailable']
    assert value['routes'][0]['key']=='8:118_0'
