from datetime import date

from fastapi import APIRouter, HTTPException, Query

from analysis_config import load_config, preset_geohashes
from db import active_version, connect
from domain import AREAS, OPERATORS
from plans_api import get_routes_catalog

router = APIRouter(prefix='/api')


@router.get('/workspace-catalog')
def workspace_catalog(date_value: date = Query(..., alias='date')):
    config = load_config()
    configured_lines = sorted({line for preset in config['presets'] for line in preset['lines']})
    with connect() as conn:
        version = active_version(conn)
        if version is None:
            raise HTTPException(503, 'No completed vehicle dataset is available.')
        coverage = conn.execute('''SELECT geohash_5,agency_id,sum(observations)::bigint AS observations
          FROM availability WHERE version_id=%s AND calendar_date=%s
          GROUP BY geohash_5,agency_id ORDER BY geohash_5,agency_id''', (version, date_value)).fetchall()
        dates = [row['calendar_date'].isoformat() for row in conn.execute(
            'SELECT DISTINCT calendar_date FROM availability WHERE version_id=%s ORDER BY calendar_date', (version,))]
        route_catalog = get_routes_catalog(conn, date_value)
        vehicle_lines = conn.execute('''SELECT DISTINCT p.event_agency_id AS agency_id,r.line_short_name
          FROM plan_packages p JOIN schedule_routes r ON r.package_id=p.id
          WHERE p.event_agency_id IS NOT NULL AND %s BETWEEN p.active_from AND p.active_until
            AND r.line_short_name=ANY(%s) AND EXISTS (
              SELECT 1 FROM schedule_trips t JOIN vehicle_events e
                ON e.version_id=%s AND e.agency_id=p.event_agency_id
                AND e.operational_date=%s AND e.trip_id=t.trip_id
              WHERE t.package_id=p.id AND t.route_id=r.route_id)''',
          (date_value, configured_lines, version, date_value)).fetchall() if configured_lines else []

    area_counts = {}
    operator_counts = {}
    for row in coverage:
        area_counts[row['geohash_5']] = area_counts.get(row['geohash_5'], 0) + row['observations']
        operator_counts[row['agency_id']] = operator_counts.get(row['agency_id'], 0) + row['observations']
    routes = route_catalog['routes']
    plan_pairs = {(route['agency_id'], route['line_short_name']) for route in routes}
    vehicle_pairs = {(row['agency_id'], row['line_short_name']) for row in vehicle_lines}

    presets = []
    for preset in config['presets']:
        lines = []
        for code in preset['lines']:
            variants = [route['key'] for route in routes
                        if route['agency_id'] in preset['operatorAgencyIds'] and route['line_short_name'] == code]
            lines.append({
                'code': code,
                'mode': preset.get('lineModes', {}).get(code, 'bus'),
                'planAvailable': any((agency, code) in plan_pairs for agency in preset['operatorAgencyIds']),
                'vehicleAvailable': any((agency, code) in vehicle_pairs for agency in preset['operatorAgencyIds']),
                'routeKeys': variants,
            })
        missing_plans = [line['code'] for line in lines if not line['planAvailable']]
        missing_vehicles = [line['code'] for line in lines if line['planAvailable'] and not line['vehicleAvailable']]
        warnings = []
        if missing_plans:
            warnings.append(f"No date-valid plan routes for {', '.join(missing_plans)}")
        if missing_vehicles:
            warnings.append(f"No vehicle observations on this date for {', '.join(missing_vehicles)}")
        presets.append({
            **preset,
            'geohashes': preset_geohashes(preset),
            'lines': lines,
            'operators': [{'id': agency, 'name': OPERATORS.get(agency, agency),
                           'available': agency in operator_counts} for agency in preset['operatorAgencyIds']],
            'warnings': warnings,
        })

    return {
        'version': 1,
        'datasetVersion': version,
        'date': date_value.isoformat(),
        'dates': dates,
        'defaultPresetId': config['defaultPresetId'],
        'areas': [{'id': area, 'name': AREAS.get(area, area), 'observations': count}
                  for area, count in sorted(area_counts.items())],
        'operators': [{'id': agency, 'name': OPERATORS.get(agency, agency), 'observations': count}
                      for agency, count in sorted(operator_counts.items())],
        'presets': presets,
        'routes': routes,
        'referenceZones': [{'presetId': preset['id'], 'presetName': preset['name'],
                            'zoneId': zone['id'], 'name': zone['name'], 'geohashes': zone['geohashes']}
                           for preset in config['presets'] for zone in preset['zones']],
        'limits': {'maxWindowHours': 4, 'maxObservations': 200000},
    }
