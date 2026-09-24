CREATE TABLE IF NOT EXISTS plan_packages (
 id bigserial PRIMARY KEY, source_name text NOT NULL, checksum text NOT NULL,
 agency jsonb NOT NULL, feed jsonb NOT NULL, counts jsonb NOT NULL,
 imported_at timestamptz NOT NULL DEFAULT now(), UNIQUE(source_name,checksum)
);
CREATE TABLE IF NOT EXISTS plan_records (
 package_id bigint NOT NULL REFERENCES plan_packages(id), table_name text NOT NULL,
 row_number integer NOT NULL, data jsonb NOT NULL,
 PRIMARY KEY(package_id,table_name,row_number)
);
CREATE INDEX IF NOT EXISTS plan_routes ON plan_records(package_id,(data->>'route_id')) WHERE table_name IN ('routes','trips');
CREATE INDEX IF NOT EXISTS plan_trips ON plan_records(package_id,table_name,(data->>'trip_id')) WHERE table_name IN ('trips','stop_times');
CREATE INDEX IF NOT EXISTS plan_stops ON plan_records(package_id,(data->>'stop_id')) WHERE table_name='stops';
CREATE INDEX IF NOT EXISTS plan_shapes ON plan_records(package_id,(data->>'shape_id')) WHERE table_name='shapes';
