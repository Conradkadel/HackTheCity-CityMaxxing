from datetime import timedelta
import pytest
from domain import parse_row,selection_window,response_payload,schedule_reference

def row(**changes):
    return dict(_id='00001',agency_id='LTP61',vehicle_id='001',driver_id='private',trip_id='0007',stop_id='0002',created_at='1788242400000',received_at='1788242401000',operational_date='20260901',latitude='38.7',longitude='-9.1',geohash_5='eycs2',**changes)

def test_identifiers_and_duplicates():
    a=row();b={**a,'_id':'other','received_at':'1788242402000','driver_id':'other'}
    values=parse_row(a)
    assert values[2:7]==('LTP61','001','private','0007','0002')
    assert values[0]==parse_row(b)[0]
    assert values[0]!=parse_row({**a,'agency_id':'IA9T6'})[0]

@pytest.mark.parametrize('changes,reason',[({'latitude':'nan'},'coordinates'),({'longitude':'181'},'coordinates'),({'vehicle_id':''},'identifier'),({'created_at':'x'},'timestamp_or_date'),({'geohash_5':'bad'},'geohash')])
def test_rejections(changes,reason):
    with pytest.raises(ValueError,match=reason):parse_row({**row(),**changes})

def test_lisbon_and_midnight():
    a,b=selection_window('2026-09-01','07:00','09:00')
    assert a.isoformat()=='2026-09-01T06:00:00+00:00'
    assert b-a==timedelta(hours=2)
    a,b=selection_window('2026-09-01','23:00','01:00')
    assert b.day==2 and b-a==timedelta(hours=2)
    assert selection_window('2026-01-01','07:00','09:00')[0].hour==7

@pytest.mark.parametrize('day,start,end',[('bad','07:00','09:00'),('2026-09-01','07:00','12:00'),('2026-09-01','07:00','07:00'),('2026-09-01','25:00','01:00'),('2026-10-25','01:30','02:30'),('2026-03-29','01:30','02:30')])
def test_invalid_windows(day,start,end):
    with pytest.raises(ValueError):selection_window(day,start,end)

def test_empty_payload():
    a,b=selection_window('2026-09-01','07:00','09:00')
    d=response_payload([],1,['eycs2'],['LTP61'],a,b)
    assert d['observations']==[] and not d['metadata']['synthetic']
    assert d['metadata']['calendarDate']=='2026-09-01'

def test_schedule_reference_uses_lisbon_service_day_and_extended_clock():
    a,_=selection_window('2026-09-02','01:00','02:00')
    value=schedule_reference(a,'25:10:00')
    assert value.isoformat()=='2026-09-02T01:10:00+01:00'
