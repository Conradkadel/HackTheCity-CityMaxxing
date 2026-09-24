CREATE TABLE IF NOT EXISTS analysis_runs (
  id bigserial PRIMARY KEY,
  dataset_version bigint NOT NULL REFERENCES dataset_versions(id),
  operational_date date NOT NULL,
  operator_id text NOT NULL,
  detector_version text NOT NULL,
  scope text NOT NULL CHECK(scope IN ('all_observed_lines','selected_lines')),
  selected_lines text[] NOT NULL,
  parameters jsonb NOT NULL,
  status text NOT NULL CHECK(status IN ('running','completed','failed')),
  started_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  counts jsonb NOT NULL DEFAULT '{}'::jsonb,
  error_message text
);

CREATE INDEX IF NOT EXISTS analysis_runs_scope
ON analysis_runs(dataset_version,operational_date,operator_id,detector_version,status,completed_at DESC);

-- Keep this migration repeatable for development databases that applied an
-- earlier draft before run scope was added.
ALTER TABLE analysis_runs ADD COLUMN IF NOT EXISTS scope text;
ALTER TABLE analysis_runs ADD COLUMN IF NOT EXISTS selected_lines text[];
UPDATE analysis_runs SET scope='selected_lines' WHERE scope IS NULL;
UPDATE analysis_runs SET selected_lines=ARRAY[]::text[] WHERE selected_lines IS NULL;
ALTER TABLE analysis_runs ALTER COLUMN scope SET NOT NULL;
ALTER TABLE analysis_runs ALTER COLUMN selected_lines SET NOT NULL;
DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid='analysis_runs'::regclass
      AND conname='analysis_runs_scope_check'
  ) THEN
    ALTER TABLE analysis_runs ADD CONSTRAINT analysis_runs_scope_check
      CHECK(scope IN ('all_observed_lines','selected_lines'));
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS bunching_episodes (
  id bigserial PRIMARY KEY,
  analysis_run_id bigint NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
  operator_id text NOT NULL,
  public_line text NOT NULL,
  package_id bigint NOT NULL,
  route_id text NOT NULL,
  direction_id text NOT NULL,
  vehicle_a_id text NOT NULL,
  trip_a_id text NOT NULL,
  vehicle_b_id text NOT NULL,
  trip_b_id text NOT NULL,
  started_at timestamptz NOT NULL,
  ended_at timestamptz NOT NULL,
  first_stop_id text NOT NULL,
  first_stop_name text NOT NULL,
  last_stop_id text NOT NULL,
  last_stop_name text NOT NULL,
  evidence_count integer NOT NULL CHECK(evidence_count > 0),
  distinct_stop_count integer NOT NULL CHECK(distinct_stop_count > 0),
  minimum_observed_gap_seconds integer NOT NULL CHECK(minimum_observed_gap_seconds >= 0),
  maximum_planned_gap_seconds integer NOT NULL CHECK(maximum_planned_gap_seconds >= 0),
  classification text NOT NULL CHECK(classification IN ('single_point','multi_stop_candidate')),
  latitude double precision CHECK(latitude BETWEEN -90 AND 90),
  longitude double precision CHECK(longitude BETWEEN -180 AND 180),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS bunching_episodes_scope
ON bunching_episodes(analysis_run_id,public_line,direction_id,started_at);
CREATE INDEX IF NOT EXISTS bunching_episodes_time
ON bunching_episodes(started_at,ended_at);

CREATE TABLE IF NOT EXISTS bunching_evidence (
  episode_id bigint NOT NULL REFERENCES bunching_episodes(id) ON DELETE CASCADE,
  evidence_sequence integer NOT NULL,
  stop_id text NOT NULL,
  stop_name text NOT NULL,
  stop_sequence integer NOT NULL,
  first_vehicle_id text NOT NULL,
  first_trip_id text NOT NULL,
  second_vehicle_id text NOT NULL,
  second_trip_id text NOT NULL,
  first_reported_at timestamptz NOT NULL,
  second_reported_at timestamptz NOT NULL,
  first_scheduled_at timestamptz NOT NULL,
  second_scheduled_at timestamptz NOT NULL,
  observed_gap_seconds integer NOT NULL CHECK(observed_gap_seconds >= 0),
  planned_gap_seconds integer NOT NULL CHECK(planned_gap_seconds >= 0),
  latitude double precision CHECK(latitude BETWEEN -90 AND 90),
  longitude double precision CHECK(longitude BETWEEN -180 AND 180),
  PRIMARY KEY(episode_id,evidence_sequence)
);

CREATE INDEX IF NOT EXISTS bunching_evidence_stop_time
ON bunching_evidence(stop_id,first_reported_at);
