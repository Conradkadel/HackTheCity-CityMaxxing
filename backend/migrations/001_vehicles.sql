CREATE TABLE IF NOT EXISTS dataset_versions (
  id bigserial PRIMARY KEY,
  inventory_hash text NOT NULL,
  status text NOT NULL CHECK(status IN ('loading','ready')) DEFAULT 'loading',
  created_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  source_root text NOT NULL
);
CREATE TABLE IF NOT EXISTS active_dataset (
  singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
  version_id bigint NOT NULL REFERENCES dataset_versions(id)
);
CREATE TABLE IF NOT EXISTS import_files (
  version_id bigint REFERENCES dataset_versions(id),
  path text NOT NULL,
  checksum text NOT NULL,
  bytes bigint NOT NULL,
  counts jsonb NOT NULL,
  elapsed_seconds double precision NOT NULL,
  PRIMARY KEY(version_id,path)
);
CREATE TABLE IF NOT EXISTS vehicle_events (
  version_id bigint NOT NULL REFERENCES dataset_versions(id),
  observation_key text NOT NULL,
  event_id text NOT NULL,
  agency_id text NOT NULL,
  vehicle_id text NOT NULL,
  driver_id text NOT NULL,
  trip_id text NOT NULL,
  stop_id text NOT NULL,
  created_at timestamptz NOT NULL,
  received_at timestamptz NOT NULL,
  operational_date date NOT NULL,
  latitude double precision NOT NULL CHECK(latitude BETWEEN -90 AND 90),
  longitude double precision NOT NULL CHECK(longitude BETWEEN -180 AND 180),
  geohash_5 text NOT NULL,
  PRIMARY KEY(version_id,observation_key)
);
CREATE INDEX IF NOT EXISTS events_area_time ON vehicle_events(version_id,geohash_5,created_at);
CREATE INDEX IF NOT EXISTS events_operator_time ON vehicle_events(version_id,agency_id,created_at);
CREATE INDEX IF NOT EXISTS events_vehicle_time ON vehicle_events(version_id,agency_id,vehicle_id,created_at);
CREATE TABLE IF NOT EXISTS event_sources (
  version_id bigint NOT NULL,
  observation_key text NOT NULL,
  source_file text NOT NULL,
  source_event_id text NOT NULL,
  source_driver_id text NOT NULL,
  source_geohash text NOT NULL,
  source_received_at timestamptz NOT NULL,
  PRIMARY KEY(version_id,observation_key,source_file,source_event_id),
  FOREIGN KEY(version_id,observation_key) REFERENCES vehicle_events(version_id,observation_key)
);
CREATE TABLE IF NOT EXISTS availability (
  version_id bigint NOT NULL REFERENCES dataset_versions(id),
  geohash_5 text NOT NULL,
  calendar_date date NOT NULL,
  agency_id text NOT NULL,
  observations bigint NOT NULL,
  first_event timestamptz NOT NULL,
  last_event timestamptz NOT NULL,
  PRIMARY KEY(version_id,geohash_5,calendar_date,agency_id)
);
