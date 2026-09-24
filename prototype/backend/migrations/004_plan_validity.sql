ALTER TABLE plan_packages ADD COLUMN IF NOT EXISTS event_agency_id text;
ALTER TABLE plan_packages ADD COLUMN IF NOT EXISTS active_from date;
ALTER TABLE plan_packages ADD COLUMN IF NOT EXISTS active_until date;
ALTER TABLE plan_packages ADD COLUMN IF NOT EXISTS external_plan_id text;
ALTER TABLE plan_packages ADD COLUMN IF NOT EXISTS normalized_gtfs_id text;

CREATE INDEX IF NOT EXISTS plan_packages_agency_validity
ON plan_packages(event_agency_id, active_from, active_until);

CREATE INDEX IF NOT EXISTS events_route_resolution
ON vehicle_events(version_id, agency_id, operational_date, trip_id, created_at);
