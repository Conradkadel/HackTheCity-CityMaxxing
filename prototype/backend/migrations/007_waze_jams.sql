CREATE TABLE IF NOT EXISTS waze_import_files (
  source_file text PRIMARY KEY,
  checksum text NOT NULL,
  bytes bigint NOT NULL,
  rows_read bigint NOT NULL,
  rows_inserted bigint NOT NULL,
  rows_skipped bigint NOT NULL,
  imported_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS waze_jams (
  source_key text PRIMARY KEY,
  observed_at timestamptz NOT NULL,
  operational_date date NOT NULL,
  zone text NOT NULL,
  geohash_6 text NOT NULL,
  dicofre text,
  street text,
  city text,
  intensity text NOT NULL,
  speed_mps double precision,
  speed_kmh double precision,
  delay_seconds integer,
  length_meters integer,
  latitude double precision NOT NULL CHECK(latitude BETWEEN -90 AND 90),
  longitude double precision NOT NULL CHECK(longitude BETWEEN -180 AND 180),
  geometry_wkt text NOT NULL,
  source_file text NOT NULL
);

CREATE INDEX IF NOT EXISTS waze_jams_time
  ON waze_jams(observed_at);

CREATE INDEX IF NOT EXISTS waze_jams_date_time
  ON waze_jams(operational_date, observed_at);

CREATE INDEX IF NOT EXISTS waze_jams_geohash_time
  ON waze_jams(geohash_6, observed_at);

CREATE INDEX IF NOT EXISTS waze_jams_location
  ON waze_jams(latitude, longitude);
