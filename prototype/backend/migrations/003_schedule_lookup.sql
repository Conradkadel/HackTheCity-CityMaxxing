CREATE TABLE IF NOT EXISTS schedule_operator_packages (
 agency_id text PRIMARY KEY,
 package_id bigint NOT NULL REFERENCES plan_packages(id)
);
CREATE TABLE IF NOT EXISTS schedule_routes (
 package_id bigint NOT NULL REFERENCES plan_packages(id), route_id text NOT NULL,
 line_short_name text NOT NULL, route_long_name text NOT NULL, route_color text NOT NULL DEFAULT '',
 PRIMARY KEY(package_id,route_id)
);
CREATE TABLE IF NOT EXISTS schedule_trips (
 package_id bigint NOT NULL REFERENCES plan_packages(id), trip_id text NOT NULL, route_id text NOT NULL,
 shape_id text NOT NULL, direction_id text NOT NULL, service_id text NOT NULL,
 PRIMARY KEY(package_id,trip_id)
);
CREATE TABLE IF NOT EXISTS schedule_stop_visits (
 package_id bigint NOT NULL REFERENCES plan_packages(id), trip_id text NOT NULL, stop_id text NOT NULL,
 stop_sequence integer NOT NULL, arrival_time text NOT NULL, departure_time text NOT NULL,
 PRIMARY KEY(package_id,trip_id,stop_id,stop_sequence)
);
CREATE INDEX IF NOT EXISTS schedule_trips_route ON schedule_trips(package_id,route_id,direction_id);
CREATE INDEX IF NOT EXISTS schedule_visits_trip_stop ON schedule_stop_visits(package_id,trip_id,stop_id);

INSERT INTO schedule_routes(package_id,route_id,line_short_name,route_long_name,route_color)
SELECT package_id,data->>'route_id',COALESCE(NULLIF(data->>'route_short_name',''),data->>'line_id',data->>'route_id'),COALESCE(data->>'route_long_name',''),COALESCE(data->>'route_color','')
FROM plan_records WHERE table_name='routes' AND NOT EXISTS (SELECT 1 FROM schedule_routes LIMIT 1)
ON CONFLICT(package_id,route_id) DO NOTHING;
INSERT INTO schedule_trips(package_id,trip_id,route_id,shape_id,direction_id,service_id)
SELECT package_id,data->>'trip_id',data->>'route_id',COALESCE(data->>'shape_id',''),COALESCE(data->>'direction_id',''),COALESCE(data->>'service_id','')
FROM plan_records WHERE table_name='trips' AND NOT EXISTS (SELECT 1 FROM schedule_trips LIMIT 1)
ON CONFLICT(package_id,trip_id) DO NOTHING;
INSERT INTO schedule_stop_visits(package_id,trip_id,stop_id,stop_sequence,arrival_time,departure_time)
SELECT package_id,data->>'trip_id',data->>'stop_id',(data->>'stop_sequence')::integer,COALESCE(data->>'arrival_time',''),COALESCE(data->>'departure_time','')
FROM plan_records WHERE table_name='stop_times' AND NOT EXISTS (SELECT 1 FROM schedule_stop_visits LIMIT 1)
ON CONFLICT(package_id,trip_id,stop_id,stop_sequence) DO NOTHING;
