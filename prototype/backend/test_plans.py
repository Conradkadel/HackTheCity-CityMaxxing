import pytest
from import_plans import validate_row,records

def test_stop_validation():
    validate_row('stops',{'stop_id':'0001','stop_lat':'38.7','stop_lon':'-9.1'})
    validate_row('stops',{'stop_id':'0001','stop_lat':'','stop_lon':''})
    with pytest.raises(ValueError):validate_row('stops',{'stop_id':'0001','stop_lat':'nan','stop_lon':'-9.1'})
    with pytest.raises(ValueError):validate_row('shapes',{'shape_id':'s','shape_pt_lat':'38','shape_pt_lon':'-9','shape_pt_sequence':'1.5'})

def test_headers_and_leading_zeros(tmp_path):
    p=tmp_path/'routes.txt';p.write_text('route_id,route_long_name\n0001,Example\n')
    assert list(records(p))[0]['route_id']=='0001'
    p.write_text('wrong_header\nvalue\n')
    with pytest.raises(ValueError):list(records(p))
