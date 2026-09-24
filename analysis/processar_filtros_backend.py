import duckdb

con = duckdb.connect("hackthecity.db")

print("⚡ A criar tabelas e views filtradas para o Backend...")

# =========================================================
# 1. CRIAR TABELA COM LISTA DE LINHAS PERMITIDAS
# =========================================================
con.execute("""
    CREATE OR REPLACE TEMP TABLE linhas_interesse (linha_id VARCHAR);
    
    INSERT INTO linhas_interesse VALUES 
    -- Carris Metropolitana
    ('1218'), ('1219'), ('1715'), ('1709'), ('1710'), ('1711'),
    ('3103'), ('3512'), ('3116'), ('3118'), ('3505'), ('3508'), ('3527'), ('3535'), ('3536'), ('3605'),
    ('3201'), ('3202'), ('3203'), ('3204'), ('3205'), ('3206'), ('3207'), ('3208'), ('3209'), ('3210'),
    ('3211'), ('3212'), ('3213'), ('3221'), ('3223'), ('3544'), ('3549'), ('3625'), ('3635'), ('3642'),
    ('3650'), ('3721'), ('4643'),
    -- Carris
    ('702'), ('703'), ('708'), ('714'), ('717'), ('718'), ('723'), ('726'), ('727'), ('728'), ('729'),
    ('734'), ('736'), ('742'), ('747'), ('750'), ('751'), ('755'), ('756'), ('758'), ('759'), ('760'),
    ('765'), ('767'), ('773'), ('774'), ('796'), ('12E'), ('15E'), ('28E'),
    -- Cascais
    ('M02'), ('M13'), ('M14'), ('M16'), ('M22'), ('M27'), ('M30'), ('M31'), ('M32'), ('M35');
""")

# =========================================================
# 2. CARREGAR CALENDÁRIO (XLSX) PARA A DB
# =========================================================
try:
    import pandas as pd
    df_cal = pd.read_excel('calendario.xlsx')
    con.execute("CREATE OR REPLACE TABLE tb_calendario AS SELECT * FROM df_cal")
    print("✅ Ficheiro 'calendario.xlsx' importado para a tabela 'tb_calendario'.")
except Exception as e:
    print(f"⚠️ Nota ao carregar calendário: {e}")

# =========================================================
# 3. FILTRAR DADOS DE GPS POR GEOHASH E POR ROUTE/TRIP
# =========================================================
print("🔍 A filtrar registos GPS pelas zonas de Geohash e Linhas selecionadas...")

con.execute("""
    CREATE OR REPLACE TABLE tb_gps_filtrado AS
    SELECT 
        g._id,
        g.agency_id,
        g.vehicle_id,
        g.trip_id,
        g.stop_id,
        g.latitude,
        g.longitude,
        g.operational_date,
        g.timestamp_criado,
        g.geohash_5,
        t.route_id,
        r.route_short_name
    FROM gps_pings g
    LEFT JOIN gtfs_trips t ON g.trip_id = t.trip_id
    LEFT JOIN gtfs_routes r ON t.route_id = r.route_id
    WHERE 
        -- Filtro por Geohash Nível 5 ou 6
        (
            SUBSTR(g.geohash_5, 1, 5) IN (
                'eyckp', 'eyckr', 'eyckx', 'eyckq', 'eycs8', 'eycs9', 'eyckj', 'eyckn',
                'eycks', 'eyckt', 'eyckm', 'eyckk', 'eyck1', 'eyck3', 'eyck6', 'eyck4',
                'eycs2', 'eyckw', 'eyc7w', 'eyce8', 'eyceb', 'eyc7z', 'eycdb', 'eycd8'
            )
            OR SUBSTR(g.geohash_5, 1, 6) IN (
                'eyckpy', 'eyckpw', 'eycs26', 'eyckpq', 'eyckr6', 'eyckrx', 'eyckxb', 'eyckx9', 'eyckqy'
            )
        )
        -- Filtro por Linha (se a informação da rota estiver associada)
        AND (
            r.route_short_name IN (SELECT linha_id FROM linhas_interesse)
            OR t.route_id IN (SELECT linha_id FROM linhas_interesse)
            OR r.route_short_name IS NULL  -- Mantém pings se a rota ainda for desconhecida para não perder dados GPS
        );
""")

cnt_filt = con.execute("SELECT COUNT(*) FROM tb_gps_filtrado;").fetchone()[0]
print(f"✅ Registos de GPS filtrados: {cnt_filt:,}")

# =========================================================
# 4. TABELA DE EVENTOS DE BUNCHING (Cálculo de Headway)
# =========================================================
print("📊 A calcular a tabela de eventos de Bunching para o Frontend...")

con.execute("""
    CREATE OR REPLACE TABLE tb_bunching_events AS
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
            LAG(timestamp_criado) OVER (
                PARTITION BY stop_id, COALESCE(route_short_name, route_id) 
                ORDER BY timestamp_criado
            ) AS timestamp_veiculo_anterior,
            LAG(vehicle_id) OVER (
                PARTITION BY stop_id, COALESCE(route_short_name, route_id) 
                ORDER BY timestamp_criado
            ) AS vehicle_id_anterior
        FROM tb_gps_filtrado
        WHERE stop_id IS NOT NULL AND stop_id != ''
    )
    SELECT 
        agency_id,
        linha,
        stop_id,
        vehicle_id,
        vehicle_id_anterior,
        timestamp_criado,
        date_diff('second', timestamp_veiculo_anterior, timestamp_criado) AS headway_segundos,
        CASE 
            WHEN date_diff('second', timestamp_veiculo_anterior, timestamp_criado) <= 90 THEN 'CRÍTICO'
            WHEN date_diff('second', timestamp_veiculo_anterior, timestamp_criado) <= 180 THEN 'MODERADO'
            ELSE 'NORMAL'
        END AS nivel_bunching,
        latitude,
        longitude
    FROM headway_calc
    WHERE timestamp_veiculo_anterior IS NOT NULL
      AND vehicle_id != vehicle_id_anterior
      AND date_diff('second', timestamp_veiculo_anterior, timestamp_criado) <= 300; -- Foco nos eventos até 5min de intervalo
""")

cnt_bunch = con.execute("SELECT COUNT(*) FROM tb_bunching_events;").fetchone()[0]
print(f"✅ Eventos de Bunching detetados/calculados: {cnt_bunch:,}")

con.close()
print("🎉 Tabelas prontas para consumo do Back-End!")