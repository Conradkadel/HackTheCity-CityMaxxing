import json
import re
from datetime import date
from functools import lru_cache
from pathlib import Path

from domain import OPERATORS

CONFIG_PATH = Path(__file__).parent / 'config' / 'analysis_presets.json'
GEOHASH_RE = re.compile(r'^[0123456789bcdefghjkmnpqrstuvwxyz]{5,6}$')
GEOHASH_ALPHABET = '0123456789bcdefghjkmnpqrstuvwxyz'


def _validate(config):
    if config.get('version') != 1:
        raise ValueError('analysis preset config version must be 1')
    presets = config.get('presets')
    if not isinstance(presets, list) or not presets:
        raise ValueError('analysis preset config requires presets')
    ids = [p.get('id') for p in presets]
    if any(not value or not re.fullmatch(r'[a-z0-9_]+', value) for value in ids) or len(ids) != len(set(ids)):
        raise ValueError('analysis preset IDs must be unique snake_case values')
    if config.get('defaultPresetId') not in ids:
        raise ValueError('defaultPresetId does not name a preset')
    for preset in presets:
        agencies = preset.get('operatorAgencyIds')
        lines = preset.get('lines')
        zones = preset.get('zones')
        if not agencies or any(a not in OPERATORS for a in agencies):
            raise ValueError(f"{preset['id']}: unknown or empty operator list")
        if not lines or len(lines) != len(set(lines)) or any(not isinstance(x, str) or not x for x in lines):
            raise ValueError(f"{preset['id']}: lines must be unique nonempty strings")
        if not zones:
            raise ValueError(f"{preset['id']}: at least one zone is required")
        geohashes = [g for z in zones for g in z.get('geohashes', [])]
        if not geohashes or any(not GEOHASH_RE.fullmatch(g) for g in geohashes):
            raise ValueError(f"{preset['id']}: invalid geohash")
        unknown_modes = set(preset.get('lineModes', {})) - set(lines)
        if unknown_modes:
            raise ValueError(f"{preset['id']}: lineModes contains unknown lines")
    by_agency = {}
    for source, plan in config.get('planSources', {}).items():
        if not source or plan.get('eventAgencyId') not in OPERATORS:
            raise ValueError('planSources contains an invalid source or agency')
        start, end = date.fromisoformat(plan['activeFrom']), date.fromisoformat(plan['activeUntil'])
        if end < start:
            raise ValueError(f'{source}: invalid validity range')
        by_agency.setdefault(plan['eventAgencyId'], []).append((start, end, source))
    for agency, ranges in by_agency.items():
        ranges.sort()
        for previous, current in zip(ranges, ranges[1:]):
            if current[0] <= previous[1]:
                raise ValueError(f'{agency}: overlapping configured plan validity')
    return config


@lru_cache(maxsize=1)
def load_config():
    return _validate(json.loads(CONFIG_PATH.read_text(encoding='utf-8')))


def preset_by_id(preset_id):
    return next((p for p in load_config()['presets'] if p['id'] == preset_id), None)


def preset_geohashes(preset):
    return list(dict.fromkeys(g for zone in preset['zones'] for g in zone['geohashes']))


def parent_cells(geohashes):
    return list(dict.fromkeys(g[:5] for g in geohashes))


def geohash_bounds(value):
    lat = [-90.0, 90.0]
    lon = [-180.0, 180.0]
    even = True
    for char in value:
        number = GEOHASH_ALPHABET.index(char)
        for mask in (16, 8, 4, 2, 1):
            target = lon if even else lat
            mid = (target[0] + target[1]) / 2
            if number & mask:
                target[0] = mid
            else:
                target[1] = mid
            even = not even
    return lat[0], lat[1], lon[0], lon[1]


def plan_source(source_name):
    return load_config().get('planSources', {}).get(source_name)
