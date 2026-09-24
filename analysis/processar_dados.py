import duckdb
import os

DB_PATH = "hackthecity.db"

# Se existir uma DB antiga, remove para recriar sem erros
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

print("🚀 A inicializar e a criar a base de dados DuckDB (hackthecity.db)...")
con = duckdb.connect(DB_PATH)

# Otimização de desempenho
con.execute("PRAGMA threads=4;")

# =========================================================
# 1. CARREGAR DADOS GPS DE VEÍCULOS (vehicles*)
# =========================================================
print("📦 A carregar 35M+ de registos de GPS...")

con.execute("""
    CREATE TABLE gps_pings AS 
    SELECT 
        _id,
        agency_id,
        driver_id,
        vehicle_id,
        trip_id,
        stop_id,
        latitude::FLOAT AS latitude,
        longitude::FLOAT AS longitude,
        operational_date,
        epoch_ms(created_at::BIGINT) AS timestamp_criado,
        epoch_ms(received_at::BIGINT) AS timestamp_recebido,
        geohash_5
    FROM read_csv_auto('vehicles*/*/*/*.csv', ignore_errors=true, header=true);
""")

print("⚡ A criar índices de pesquisa para o GPS...")
con.execute("CREATE INDEX idx_gps_trip ON gps_pings(trip_id, timestamp_criado);")
con.execute("CREATE INDEX idx_gps_vehicle ON gps_pings(vehicle_id, timestamp_criado);")
con.execute("CREATE INDEX idx_gps_stop ON gps_pings(stop_id, timestamp_criado);")

cnt_gps = con.execute("SELECT COUNT(*) FROM gps_pings;").fetchone()[0]
print(f"✅ Registos GPS carregados com sucesso: {cnt_gps:,}")


# =========================================================
# 2. CARREGAR DADOS DE OPERAÇÃO (GTFS) COM union_by_name
# =========================================================
print("📅 A carregar horários, viagens e paragens (operation-plans)...")

gtfs_tables = ['stop_times', 'trips', 'stops', 'routes', 'calendar_dates', 'shapes']

for table_name in gtfs_tables:
    file_pattern = f"operation-plans/*/{table_name}.txt"
    try:
        # union_by_name=true resolve a variação de colunas entre pastas
        con.execute(f"""
            CREATE TABLE gtfs_{table_name} AS 
            SELECT * FROM read_csv_auto('{file_pattern}', ignore_errors=true, header=true, all_varchar=true, union_by_name=true);
        """)
        cnt = con.execute(f"SELECT COUNT(*) FROM gtfs_{table_name};").fetchone()[0]
        print(f"   ↳ Tabela 'gtfs_{table_name}' criada com sucesso ({cnt:,} linhas).")
    except Exception as e:
        print(f"   ⚠️ Erro ao carregar {table_name}: {e}")

print("\n🎉 Tudo pronto! A tua base de dados 'hackthecity.db' está 100% operacional.")
con.close()