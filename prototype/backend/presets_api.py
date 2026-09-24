from datetime import date

from fastapi import APIRouter, Query

from analysis_config import load_config, parent_cells, preset_geohashes
from db import connect
from domain import OPERATORS

router = APIRouter(prefix='/api')


@router.get('/analysis-presets')
def analysis_presets(date_value: date = Query(..., alias='date')):
    config = load_config()
    with connect() as conn:
        packages = conn.execute('''SELECT id,source_name,event_agency_id,external_plan_id,active_from,active_until
          FROM plan_packages WHERE event_agency_id IS NOT NULL AND %s BETWEEN active_from AND active_until
          ORDER BY event_agency_id,id DESC''', (date_value,)).fetchall()
        routes = conn.execute('''SELECT p.id AS package_id,p.event_agency_id,r.route_id,r.line_short_name,r.route_long_name,r.route_color,
          array_agg(DISTINCT t.direction_id ORDER BY t.direction_id) AS directions
          FROM plan_packages p JOIN schedule_routes r ON r.package_id=p.id
          LEFT JOIN schedule_trips t ON t.package_id=r.package_id AND t.route_id=r.route_id
          WHERE p.event_agency_id IS NOT NULL AND %s BETWEEN p.active_from AND p.active_until
          GROUP BY p.id,p.event_agency_id,r.route_id,r.line_short_name,r.route_long_name,r.route_color
          ORDER BY p.event_agency_id,r.line_short_name,r.route_id''', (date_value,)).fetchall()
    by_agency = {}
    for package in packages:
        by_agency.setdefault(package['event_agency_id'], []).append(package)
    output = []
    for preset in config['presets']:
        wanted = set(preset['lines'])
        resolved = [{**r, 'mode': preset.get('lineModes', {}).get(r['line_short_name'], 'bus')}
                    for r in routes if r['event_agency_id'] in preset['operatorAgencyIds'] and r['line_short_name'] in wanted]
        found = {r['line_short_name'] for r in resolved}
        warnings = []
        missing_plans = [a for a in preset['operatorAgencyIds'] if a not in by_agency]
        if missing_plans:
            warnings.append(f"No imported plan valid on {date_value.isoformat()} for {', '.join(missing_plans)}")
        missing_lines = sorted(wanted - found)
        if missing_lines:
            warnings.append(f"No route variant resolved for {', '.join(missing_lines)}")
        output.append({**preset,
                       'operators': [{'id': a, 'name': OPERATORS[a]} for a in preset['operatorAgencyIds']],
                       'geohashes': preset_geohashes(preset),
                       'queryAreas': parent_cells(preset_geohashes(preset)),
                       'resolvedRoutes': resolved,
                       'planCoverageWarnings': warnings})
    return {'version': config['version'], 'date': date_value.isoformat(),
            'defaultPresetId': config['defaultPresetId'],
            'includeContextByDefault': config['includeContextByDefault'], 'presets': output}
