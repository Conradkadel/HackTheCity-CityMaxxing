"""API for the Findings tab: the weekly WHERE / WHEN / WHY of bunching and what to change.

GET /api/findings   models/findings.json (built by build_findings.py) with stop names and
                    positions from the operation plan valid in that week. Works without the
                    database too: stops then keep their ids and the GPS-based positions.
"""
import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

from db import connect

router = APIRouter(prefix='/api')
FINDINGS = Path(__file__).parent / 'models' / 'findings.json'
_cache = {}

STOPS_SQL = """
SELECT DISTINCT ON (data->>'stop_id') data->>'stop_id' AS stop_id, data->>'stop_name' AS name,
       NULLIF(data->>'stop_lat', '')::float AS lat, NULLIF(data->>'stop_lon', '')::float AS lon
FROM plan_records
WHERE table_name = 'stops' AND data->>'stop_id' = ANY(%s)
  AND package_id IN (SELECT id FROM plan_packages WHERE event_agency_id = %s
                     AND %s::date BETWEEN active_from AND active_until)
ORDER BY data->>'stop_id', package_id DESC
"""


def stop_refs(findings):
    """Every dict in the findings that points at a stop."""
    for p in findings.get('problems', []):
        if p.get('terminal'):
            yield p['terminal']
        yield from p.get('stretch', [])
        yield from p.get('profile', [])
    yield from findings.get('hotspots', [])
    for c in findings.get('corridors', []):
        yield from c.get('sharedStops', [])
    for area in findings.get('areas', []):
        yield from area.get('stops', [])


def stop_details(ids, day, agency='IA9T6'):
    try:
        with connect() as conn:
            with conn.transaction():
                conn.execute("SET LOCAL statement_timeout='20s'")
                return {r['stop_id']: r for r in conn.execute(STOPS_SQL, (sorted(ids), agency, day))}
    except Exception as exc:  # the view must still work without the database
        logging.getLogger('headway').warning('Findings: stop names unavailable (%s)', type(exc).__name__)
        return None


def enrich(findings, details):
    for ref in stop_refs(findings):
        info = (details or {}).get(ref['stop_id'])
        ref['name'] = info['name'] if info and info.get('name') else None
        if info and info.get('lat') is not None and info.get('lon') is not None:
            ref['lat'], ref['lon'] = round(info['lat'], 6), round(info['lon'], 6)
    findings['stopNames'] = details is not None
    return findings


@router.get('/findings')
def findings():
    if not FINDINGS.exists():
        raise HTTPException(503, 'Findings not built yet. Run backend/build_findings.py (see docs/FINDINGS.md).')
    mtime = FINDINGS.stat().st_mtime
    cached = _cache.get('findings')
    if cached and cached[0] == mtime:
        return cached[1]
    data = json.loads(FINDINGS.read_text())
    ids = {ref['stop_id'] for ref in stop_refs(data) if ref.get('stop_id')}
    details = stop_details(ids, data['source']['from'])
    data = enrich(data, details)
    if details is not None:          # retry the database on the next request if it was down
        _cache['findings'] = (mtime, data)
    return data
