from analysis_config import geohash_bounds

OBSERVATIONS_SQL = '''SELECT e.created_at,e.received_at,e.agency_id,e.vehicle_id,e.trip_id,e.stop_id,e.latitude,e.longitude,e.geohash_5,
 p.id AS package_id,t.route_id,t.direction_id,r.line_short_name,r.route_long_name,
 sv.stop_sequence,sv.arrival_time,sv.departure_time
 FROM vehicle_events e
 LEFT JOIN LATERAL (SELECT pp.id FROM plan_packages pp WHERE pp.event_agency_id=e.agency_id
   AND e.operational_date BETWEEN pp.active_from AND pp.active_until ORDER BY pp.id DESC LIMIT 1) p ON true
 LEFT JOIN schedule_trips t ON t.package_id=p.id AND t.trip_id=e.trip_id
 LEFT JOIN schedule_routes r ON r.package_id=t.package_id AND r.route_id=t.route_id
 LEFT JOIN LATERAL (SELECT s.stop_sequence,s.arrival_time,s.departure_time FROM schedule_stop_visits s
   WHERE s.package_id=t.package_id AND s.trip_id=t.trip_id AND s.stop_id=e.stop_id ORDER BY s.stop_sequence LIMIT 1) sv ON true
 WHERE e.version_id=%s AND e.geohash_5=ANY(%s) AND e.agency_id=ANY(%s)
 AND e.created_at >= %s AND e.created_at <= %s AND {geofence}
 AND (%s::text IS NULL OR t.route_id=%s) AND (%s::text IS NULL OR t.direction_id=%s)
 AND (%s::boolean OR r.line_short_name=ANY(%s))
 ORDER BY e.created_at,e.agency_id,e.vehicle_id,e.received_at,e.latitude,e.longitude,e.trip_id,e.stop_id,e.observation_key
 LIMIT %s'''


def geofence_clause(geohashes, params):
    clauses = []
    for value in geohashes:
        if len(value) == 5:
            clauses.append('e.geohash_5=%s')
            params.append(value)
        else:
            south, north, west, east = geohash_bounds(value)
            clauses.append('(e.geohash_5=%s AND e.latitude >= %s AND e.latitude <= %s AND e.longitude >= %s AND e.longitude <= %s)')
            params.extend((value[:5], south, north, west, east))
    return '(' + ' OR '.join(clauses) + ')' if clauses else 'TRUE'


def build_observation_query(version, areas, operators, start, end, geohashes, route_id,
                            direction_id, allow_all_lines, lines, limit):
    geofence_params = []
    geofence = geofence_clause(geohashes, geofence_params)
    params = [version, areas, operators, start, end, *geofence_params,
              route_id, route_id, direction_id, direction_id, allow_all_lines, lines, limit]
    return OBSERVATIONS_SQL.format(geofence=geofence), params
