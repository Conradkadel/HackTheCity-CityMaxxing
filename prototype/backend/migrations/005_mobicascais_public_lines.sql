UPDATE schedule_routes r
SET line_short_name=split_part(r.route_id,'_',1)
FROM plan_packages p
WHERE p.id=r.package_id AND p.event_agency_id='HF16N' AND r.route_id ~ '^M[0-9]{2}_';
