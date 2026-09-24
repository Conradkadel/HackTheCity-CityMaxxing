from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query

from analysis_config import load_config, parent_cells, preset_geohashes
from db import connect

LISBON = ZoneInfo('Europe/Lisbon')
router = APIRouter(prefix='/api/schedule')


def ensure_operator_packages(conn):
    """Retained for startup compatibility; plan selection is now date-aware."""


def service_timestamp(service_day, clock):
    if not clock:
        return None
    try:
        h, m, s = (int(x) for x in clock.split(':'))
        if m > 59 or s > 59 or h < 0:
            raise ValueError
        return datetime(service_day.year, service_day.month, service_day.day, tzinfo=LISBON) + timedelta(hours=h, minutes=m, seconds=s)
    except (ValueError, TypeError):
        return None


def _route_presets(agency, line):
    return [p for p in load_config()['presets'] if agency in p['operatorAgencyIds'] and line in p['lines']]


@router.get('/routes')
def routes(date_value: Optional[date] = Query(None, alias='date'), include_other: bool = False):
    day = date_value or date(2026, 9, 1)
    with connect() as conn:
        rows = conn.execute('''SELECT p.event_agency_id AS agency_id,r.package_id,r.route_id,r.line_short_name,r.route_long_name,r.route_color,
          array_agg(DISTINCT t.direction_id ORDER BY t.direction_id) AS directions
          FROM plan_packages p JOIN schedule_routes r ON r.package_id=p.id
          JOIN schedule_trips t ON t.package_id=r.package_id AND t.route_id=r.route_id
          WHERE p.event_agency_id IS NOT NULL AND %s BETWEEN p.active_from AND p.active_until
          GROUP BY p.event_agency_id,r.package_id,r.route_id,r.line_short_name,r.route_long_name,r.route_color
          ORDER BY r.line_short_name,r.route_id''', (day,)).fetchall()
    out = []
    for row in rows:
        matches = _route_presets(row['agency_id'], row['line_short_name'])
        if not include_other and not matches:
            continue
        preset = matches[0] if matches else None
        out.append({**row, 'target': bool(matches), 'presetIds': [p['id'] for p in matches],
                    'corridor': preset['name'] if preset else 'Other imported route',
                    'areas': parent_cells(preset_geohashes(preset)) if preset else []})
    return out


@router.get('/directions')
def directions(operator: str, route_id: str, date_value: Optional[date] = Query(None, alias='date')):
    day = date_value or date(2026, 9, 1)
    with connect() as conn:
        rows = conn.execute('''SELECT DISTINCT t.direction_id,t.shape_id FROM plan_packages p
          JOIN schedule_trips t ON t.package_id=p.id
          WHERE p.event_agency_id=%s AND %s BETWEEN p.active_from AND p.active_until AND t.route_id=%s
          ORDER BY t.direction_id,t.shape_id''', (operator, day, route_id)).fetchall()
    if not rows:
        raise HTTPException(404, 'No valid schedule route for this operator and date.')
    return rows
