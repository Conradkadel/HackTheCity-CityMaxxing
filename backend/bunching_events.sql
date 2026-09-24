-- =====================================================================
-- Build tb_bunching_events from tb_gps_filtrado  (Postgres version).
--
-- COPIED from analysis/processar_filtros_backend.py (step 4, DuckDB) and
-- translated to Postgres: date_diff('second', a, b) -> EXTRACT(EPOCH FROM b - a).
-- Logic is unchanged on purpose, so both give the same table:
--
--   For every ping with a stop_id, take the previous ping at the same stop
--   and line (any bus). If it is a DIFFERENT bus and <= 300 s earlier -> row.
--   <= 90 s 'CRÍTICO', <= 180 s 'MODERADO', else 'NORMAL'.
--
-- Known limits (see DATASET_DESIGN.md §1/§5): this is PING level, so one real
-- episode produces many rows, and the window has no date partition.
-- Used by mock_data.py; on the real DB the table already exists.
-- =====================================================================
DROP TABLE IF EXISTS tb_bunching_events;

CREATE TABLE tb_bunching_events AS
WITH headway_calc AS (
    SELECT
        agency_id,
        COALESCE(route_short_name, route_id, 'Desconhecida') AS linha,
        stop_id,
        vehicle_id,
        trip_id,
        latitude,
        longitude,
        timestamp_criado,
        LAG(timestamp_criado) OVER w AS timestamp_veiculo_anterior,
        LAG(vehicle_id)       OVER w AS vehicle_id_anterior
    FROM tb_gps_filtrado
    WHERE stop_id IS NOT NULL AND stop_id <> ''
    WINDOW w AS (PARTITION BY stop_id, COALESCE(route_short_name, route_id) ORDER BY timestamp_criado)
),
with_headway AS (
    SELECT *, EXTRACT(EPOCH FROM timestamp_criado - timestamp_veiculo_anterior)::BIGINT AS headway_segundos
    FROM headway_calc
    WHERE timestamp_veiculo_anterior IS NOT NULL
)
SELECT
    agency_id,
    linha,
    stop_id,
    vehicle_id,
    vehicle_id_anterior,
    timestamp_criado,
    headway_segundos,
    CASE
        WHEN headway_segundos <= 90  THEN 'CRÍTICO'
        WHEN headway_segundos <= 180 THEN 'MODERADO'
        ELSE 'NORMAL'
    END AS nivel_bunching,
    latitude,
    longitude
FROM with_headway
WHERE vehicle_id <> vehicle_id_anterior
  AND headway_segundos <= 300;   -- only gaps up to 5 min

CREATE INDEX IF NOT EXISTS idx_ev_time    ON tb_bunching_events (timestamp_criado);
CREATE INDEX IF NOT EXISTS idx_ev_vehicle ON tb_bunching_events (vehicle_id, stop_id, timestamp_criado);
