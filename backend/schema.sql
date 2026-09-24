-- =====================================================================
-- Tables the API reads (Postgres).  This mirrors the team database:
--
--   gps_pings, gtfs_calendar_dates, gtfs_routes, gtfs_shapes, gtfs_stop_times,
--   gtfs_stops, gtfs_trips, tb_bunching_events, tb_calendario, tb_gps_filtrado
--
-- The API only uses the ones below (and only the columns listed). The real DB
-- may have MORE columns (GTFS tables are loaded with all columns as text) –
-- that is fine, nothing here breaks.
--
-- Safe to run on the real DB: only CREATE ... IF NOT EXISTS (never drops).
-- Running it there is actually useful: it adds the indexes the API needs.
--
-- Where the tables come from:
--   gps_pings / gtfs_*      analysis/processar_dados.py        (raw CSV + GTFS)
--   tb_gps_filtrado         analysis/processar_filtros_backend.py step 3
--   tb_bunching_events      analysis/processar_filtros_backend.py step 4
--                           (Postgres copy of that SQL: backend/bunching_events.sql)
--   fake versions           backend/mock_data.py
-- =====================================================================

-- ---------- GPS pings, filtered to the corridor geohashes + lines -------
-- One row per GPS ping. stop_id = the NEXT stop the bus is heading to
-- (NULL = layover at a terminal, e.g. Carris).
CREATE TABLE IF NOT EXISTS tb_gps_filtrado (
    _id              VARCHAR,
    agency_id        VARCHAR,
    vehicle_id       BIGINT,
    trip_id          VARCHAR,
    stop_id          VARCHAR,           -- string on purpose (leading zeros!)
    latitude         FLOAT,
    longitude        FLOAT,
    operational_date BIGINT,            -- 20260901 (day runs 05:00–04:59 Lisbon)
    timestamp_criado TIMESTAMP,         -- GPS time, UTC, no time zone
    geohash_5        VARCHAR,
    route_id         VARCHAR,           -- from gtfs_trips (NULL if trip unknown)
    route_short_name VARCHAR            -- public line number, e.g. '1715', 'M22'
);

-- ---------- ping-level bunching "events" ---------------------------------
-- Built from tb_gps_filtrado: for each ping at a stop, the previous ping of a
-- DIFFERENT bus of the SAME line at that stop, if it came <= 300 s earlier.
--   nivel_bunching:  'CRÍTICO' (<= 90 s)  'MODERADO' (<= 180 s)  'NORMAL' (<= 300 s)
CREATE TABLE IF NOT EXISTS tb_bunching_events (
    agency_id           VARCHAR,
    linha               VARCHAR,        -- COALESCE(route_short_name, route_id, 'Desconhecida')
    stop_id             VARCHAR,
    vehicle_id          BIGINT,         -- the follower (arrives second)
    vehicle_id_anterior BIGINT,         -- the leader (arrived first)
    timestamp_criado    TIMESTAMP,      -- when the follower pinged (UTC)
    headway_segundos    BIGINT,
    nivel_bunching      VARCHAR,
    latitude            FLOAT,
    longitude           FLOAT
);

-- ---------- GTFS (all text, like the team DB) -----------------------------
CREATE TABLE IF NOT EXISTS gtfs_routes (
    route_id         VARCHAR,
    route_short_name VARCHAR,
    route_long_name  VARCHAR,
    route_color      VARCHAR            -- hex without '#'
);

CREATE TABLE IF NOT EXISTS gtfs_trips (
    route_id     VARCHAR,
    service_id   VARCHAR,
    trip_id      VARCHAR,
    direction_id VARCHAR,
    shape_id     VARCHAR
);

CREATE TABLE IF NOT EXISTS gtfs_shapes (
    shape_id          VARCHAR,
    shape_pt_lat      VARCHAR,
    shape_pt_lon      VARCHAR,
    shape_pt_sequence VARCHAR
);

CREATE TABLE IF NOT EXISTS gtfs_stops (
    stop_id   VARCHAR,
    stop_name VARCHAR,
    stop_lat  VARCHAR,
    stop_lon  VARCHAR
);

CREATE TABLE IF NOT EXISTS gtfs_stop_times (
    trip_id        VARCHAR,
    arrival_time   VARCHAR,
    departure_time VARCHAR,
    stop_id        VARCHAR,
    stop_sequence  VARCHAR
);

-- ---------- indexes the API needs (cheap to create, big speed-up) ---------
CREATE INDEX IF NOT EXISTS idx_gps_time    ON tb_gps_filtrado (timestamp_criado);
CREATE INDEX IF NOT EXISTS idx_gps_vehicle ON tb_gps_filtrado (vehicle_id, timestamp_criado);
CREATE INDEX IF NOT EXISTS idx_gps_date    ON tb_gps_filtrado (operational_date);
CREATE INDEX IF NOT EXISTS idx_ev_time     ON tb_bunching_events (timestamp_criado);
CREATE INDEX IF NOT EXISTS idx_ev_vehicle  ON tb_bunching_events (vehicle_id, stop_id, timestamp_criado);
CREATE INDEX IF NOT EXISTS idx_trips_route ON gtfs_trips (route_id);
CREATE INDEX IF NOT EXISTS idx_st_trip     ON gtfs_stop_times (trip_id);
CREATE INDEX IF NOT EXISTS idx_shapes_id   ON gtfs_shapes (shape_id);
