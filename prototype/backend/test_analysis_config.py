import csv
from datetime import date
from pathlib import Path

from analysis_config import geohash_bounds, load_config, parent_cells, preset_by_id

PLAN_ROOT = Path(__file__).parents[2] / 'raw-data' / 'datasets' / 'TML' / 'operation-plans'


def test_config_is_valid_and_carris_is_default():
    config = load_config()
    assert config['version'] == 1
    assert config['defaultPresetId'] == 'carris_lisbon'
    assert config['includeContextByDefault'] is False
    carris = preset_by_id('carris_lisbon')
    assert carris['operatorAgencyIds'] == ['IA9T6']
    assert {'755', '12E', '15E', '28E'} <= set(carris['lines'])
    assert all(len(g) == 6 for zone in carris['zones'] for g in zone['geohashes'])
    assert set(parent_cells([g for z in carris['zones'] for g in z['geohashes']])) == {'eyckp', 'eycs2', 'eyckr', 'eyckx', 'eyckq'}


def test_plan_validity_selects_area_2_transition():
    plans = [p for p in load_config()['planSources'].values() if p['eventAgencyId'] == 'BNA17']
    def plan_on(day):
        return next(p['planId'] for p in plans if date.fromisoformat(p['activeFrom']) <= day <= date.fromisoformat(p['activeUntil']))
    assert plan_on(date(2026, 8, 31)) == '0277F'
    assert plan_on(date(2026, 9, 1)) == 'JU98X'


def test_carris_public_lines_and_exact_trip_resolve_in_official_plan():
    package = PLAN_ROOT / '20260715_IA9T6_CARRIS_82YP2'
    with (package / 'routes.txt').open(encoding='utf-8-sig', newline='') as stream:
        mappings = {row['route_short_name']: row['route_id'] for row in csv.DictReader(stream)}
    assert mappings['755'] == '118_0'
    assert mappings['12E'] == '77_0'
    assert mappings['15E'] == '76_0'
    assert mappings['28E'] == '75_0'
    with (package / 'trips.txt').open(encoding='utf-8-sig', newline='') as stream:
        trip = next(row for row in csv.DictReader(stream) if row['trip_id'] == '6656_20260606_118_0_2')
    assert trip['route_id'] == '118_0'


def test_six_character_geohash_bounds_are_inside_parent():
    child = geohash_bounds('eyckpy')
    parent = geohash_bounds('eyckp')
    assert parent[0] <= child[0] < child[1] <= parent[1]
    assert parent[2] <= child[2] < child[3] <= parent[3]
    assert not (child[0] <= parent[0] <= child[1] and child[2] <= parent[2] <= child[3])
