"""In analytics/ ablegen und vom Repository aus ausfuehren.

python analytics/build_bus_database.py
Optional: --source PATH --gtfs-root PATH --calendar PATH --output PATH --all-gps
--create-indexes erstellt zusaetzlich die drei GPS-Indizes (hoher Platzbedarf).
Standard: alle YYYYMMDD.db in data/vehicle_databases/ zusammenfuehren.
--source akzeptiert ein Verzeichnis oder eine einzelne Datenbank.
Ausgabe: data/hackthecity.db mit den zehn Tabellen der CarolinaPipeline.
gps_pings enthaelt standardmaessig die exakt zugeordneten Bus-Signale.
--all-gps uebernimmt stattdessen alle GPS-Signale wie CarolinaPipeline.
Koordinaten werden FLOAT, Unix-Millisekunden werden TIMESTAMP (UTC).
GTFS-Dateien und calendario.xlsx werden importiert; Filter und Bunching
verwenden die gemeinsamen Definitionen in CarolinaPipeline.
Nur exakte ID-Zuordnung; keine Pruefung von Fahrplan-Gueltigkeit oder
Servicekalendern. Wiederholte Eingangssignale bleiben erhalten.
"""
import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import duckdb

# Auch beim direkten Aufruf aus analytics/ das gemeinsame Modul finden.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from CarolinaPipeline.processar_filtros_backend import build_backend_tables

# Zuordnung der Fahrzeug-API zu den vier besprochenen GTFS-Verzeichnissen.
PLANS = {
    "20251002_41_YEAR_03_47_02": "LA77N",
    "2025922_42_YEAR_03.03.55": "BNA17",
    "20250924_43_YEAR_04_05_01": "YA15B",
    "20250930_44_YEAR_04_20_01": "A2L1N",
}
GTFS_TABLES = ("calendar_dates", "routes", "shapes", "stop_times", "stops", "trips")
EXPECTED_TABLES = {"gps_pings", "tb_calendario", "tb_gps_filtrado", "tb_bunching_events"} | {
    f"gtfs_{name}" for name in GTFS_TABLES
}


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def identifier(value):
    return '"' + value.replace('"', '""') + '"'


def read_csv(path, required):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = set(required) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path}: Spalten fehlen: {sorted(missing)}")
        return list(reader)


def discover_sources(source):
    source = Path(source).resolve()
    if source.is_file():
        return [source]
    if not source.is_dir():
        raise FileNotFoundError(source)
    sources = []
    for path in sorted(source.glob("????????.db")):
        if not path.is_file() or not path.stem.isdigit():
            continue
        try:
            datetime.strptime(path.stem, "%Y%m%d")
        except ValueError:
            continue
        sources.append(path.resolve())
    if not sources:
        raise FileNotFoundError(f"Keine Tagesdatenbanken (YYYYMMDD.db) in {source}")
    return sources


def append_source(con, source, first, all_gps=False):
    # Immer nur eine Tagesdatenbank gleichzeitig lesend oeffnen.
    con.execute(f"ATTACH {literal(source)} AS src (READ_ONLY)")
    try:
        columns = {row[0]: row[1] for row in con.execute("DESCRIBE src.main.vehicles").fetchall()}
        required = {"_id", "vehicle_id", "trip_id", "agency_id", "latitude", "longitude",
                    "driver_id", "stop_id", "operational_date", "received_at", "geohash_5"}
        if required - columns.keys():
            raise ValueError(f"{source}: vehicles: Spalten fehlen: {sorted(required - columns.keys())}")
        timestamp = next((c for c in ("timestamp_criado", "created_at") if c in columns), None)
        if timestamp is None:
            raise ValueError(f"{source}: vehicles: timestamp_criado oder created_at erforderlich.")
        def as_timestamp(name):
            value = f"g.{identifier(name)}"
            if columns[name].startswith("TIMESTAMP"):
                return f"CAST({value} AS TIMESTAMP)"
            return f"epoch_ms(CAST(NULLIF(TRIM(CAST({value} AS VARCHAR)), '') AS BIGINT))"

        print(f"{source.name}: {timestamp} -> timestamp_criado (TIMESTAMP)")
        con.execute("BEGIN TRANSACTION")
        try:
            con.execute(f"""INSERT INTO coverage_by_source
                SELECT {literal(source.name)}, CAST(g.agency_id AS VARCHAR),
                       COUNT(*), COUNT(m.trip_id),
                       COUNT(*) FILTER (WHERE g.trip_id IS NULL OR
                           TRIM(CAST(g.trip_id AS VARCHAR)) = '')
                FROM src.main.vehicles g LEFT JOIN mapping m
                  ON CAST(g.trip_id AS VARCHAR) = m.trip_id
                 AND CAST(g.agency_id AS VARCHAR) = m.agency_id
                GROUP BY g.agency_id""")
            statement = ("CREATE TABLE result.main.gps_pings AS" if first else
                         "INSERT INTO result.main.gps_pings BY NAME")
            join = "" if all_gps else """INNER JOIN mapping m
                  ON CAST(g.trip_id AS VARCHAR) = m.trip_id
                 AND CAST(g.agency_id AS VARCHAR) = m.agency_id"""
            con.execute(f"""{statement}
                SELECT CAST(g._id AS VARCHAR) AS _id,
                       CAST(g.agency_id AS VARCHAR) AS agency_id,
                       CAST(g.driver_id AS VARCHAR) AS driver_id,
                       CAST(g.vehicle_id AS VARCHAR) AS vehicle_id,
                       CAST(g.trip_id AS VARCHAR) AS trip_id,
                       CAST(g.stop_id AS VARCHAR) AS stop_id,
                       CAST(NULLIF(TRIM(CAST(g.latitude AS VARCHAR)), '') AS FLOAT) AS latitude,
                       CAST(NULLIF(TRIM(CAST(g.longitude AS VARCHAR)), '') AS FLOAT) AS longitude,
                       CAST(g.operational_date AS VARCHAR) AS operational_date,
                       {as_timestamp(timestamp)} AS timestamp_criado,
                       {as_timestamp('received_at')} AS timestamp_recebido,
                       CAST(g.geohash_5 AS VARCHAR) AS geohash_5
                FROM src.main.vehicles g {join}""")
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    finally:
        con.execute("DETACH src")


def build(source, root, output, calendar=None, all_gps=False, create_indexes=False):
    root, output = [Path(p).resolve() for p in (root, output)]
    sources = discover_sources(source)
    if output in sources or output.exists():
        raise FileExistsError(f"Zieldatei existiert bereits: {output}. Anderen Namen waehlen.")
    calendar = Path(calendar) if calendar is not None else root.parent / "calendario.xlsx"
    if not calendar.is_file():
        raise FileNotFoundError(calendar)
    print(f"{len(sources)} Quelldatenbank(en) -> {output}")

    mappings = []
    for folder, agency in PLANS.items():
        plan = root / folder
        # Alternative Schreibweise des bekannten Ordnernamens zulassen.
        if not plan.exists() and folder == "2025922_42_YEAR_03.03.55":
            plan = root / "20250922_42_YEAR_03.03.55"
        routes = read_csv(plan / "routes.txt", ["route_id", "route_type", "route_short_name"])
        route_map = {}
        for r in routes:
            rid = r["route_id"]
            if rid in route_map and route_map[rid] != r:
                raise ValueError(f"Mehrdeutige route_id {rid} in {plan}")
            route_map[rid] = r
        trips = read_csv(plan / "trips.txt", ["trip_id", "route_id", "direction_id"])
        count = 0
        for t in trips:
            r = route_map.get(t["route_id"])
            if r is None:
                continue
            # GTFS Bus, Trolleybus und erweiterte Bus-Typen.
            try:
                rt = int(r["route_type"])
            except (ValueError, TypeError):
                continue
            if not (rt in (3, 11) or 700 <= rt <= 799):
                continue
            direction = (t["direction_id"] or "").strip()
            if not t["trip_id"].strip() or not t["route_id"].strip() or direction not in ("0", "1"):
                continue
            mappings.append((agency, t["trip_id"], t["route_id"],
                             r["route_short_name"] or None, int(direction), plan.name))
            count += 1
        print(f"{plan.name}: {count:,} verwendbare GTFS-Zeilen ({agency})")
    if not mappings:
        raise ValueError("Keine verwendbaren Bus-Trips gefunden.")

    # GTFS-Zuordnung einmal laden; Signale tageweise auf Platte schreiben.
    con = duckdb.connect()
    try:
        con.execute("""CREATE TEMP TABLE raw_mapping (
            agency_id VARCHAR, trip_id VARCHAR, route_id VARCHAR,
            linha VARCHAR, direction_id INTEGER, gtfs_source VARCHAR)""")
        con.execute("""INSERT INTO raw_mapping
            SELECT unnest(?), unnest(?), unnest(?), unnest(?), unnest(?), unnest(?)""",
                    list(zip(*mappings)))
        con.execute("CREATE TEMP TABLE mapping AS SELECT DISTINCT * FROM raw_mapping")
        conflicts = con.execute("""SELECT agency_id, trip_id, COUNT(*)
            FROM mapping GROUP BY 1, 2 HAVING COUNT(*) > 1 LIMIT 10""").fetchall()
        if conflicts:
            raise ValueError(f"Mehrdeutige GTFS-Zuordnungen, Abbruch: {conflicts}")

        output.parent.mkdir(parents=True, exist_ok=True)
        # Erst die vollstaendige Datenbank veroeffentlichen, auch bei spaeten Fehlern.
        with TemporaryDirectory(prefix=".bus-build-", dir=output.parent) as staging:
            staged_output = Path(staging) / output.name
            con.execute(f"ATTACH {literal(staged_output)} AS result")
            try:
                con.execute("""CREATE TEMP TABLE coverage_by_source (
                    source_file VARCHAR, agency_id VARCHAR, input_signals BIGINT,
                    matched_signals BIGINT, missing_trip_id BIGINT)""")
                for index, daily_source in enumerate(sources):
                    append_source(con, daily_source, first=index == 0, all_gps=all_gps)
                con.execute("""CREATE TEMP TABLE coverage AS
                    SELECT agency_id, SUM(input_signals) AS input_signals,
                           SUM(matched_signals) AS matched_signals,
                           SUM(missing_trip_id) AS missing_trip_id
                    FROM coverage_by_source GROUP BY agency_id""")
                count_column = "input_signals" if all_gps else "matched_signals"
                total = con.execute(f"SELECT SUM({count_column}) FROM coverage").fetchone()[0] or 0
                if total == 0:
                    raise ValueError("Keine passenden Signale gefunden; keine Ausgabedatenbank erstellt.")
                actual = con.execute("SELECT COUNT(*) FROM result.main.gps_pings").fetchone()[0]
                if actual != total:
                    raise RuntimeError("Zeilenzahl stimmt nicht mit Zuordnungsstatistik ueberein.")
                coverage = con.execute(
                    "SELECT * FROM coverage ORDER BY input_signals DESC").fetchall()
                for table in GTFS_TABLES:
                    files = sorted(root.glob(f"*/{table}.txt"))
                    if not files:
                        raise FileNotFoundError(f"Keine GTFS-Dateien fuer {table} in {root}")
                    paths = ", ".join(literal(path) for path in files)
                    con.execute(f"""CREATE TABLE result.main.gtfs_{table} AS
                        SELECT * FROM read_csv_auto([{paths}], header=true,
                            all_varchar=true, union_by_name=true)""")
                    print(f"gtfs_{table}: importiert")
                con.execute("USE result")
                build_backend_tables(con, calendar)
                if create_indexes:
                    for name in ("trip", "vehicle", "stop"):
                        con.execute(f"CREATE INDEX idx_gps_{name} ON gps_pings({name}_id, timestamp_criado)")
                        print(f"idx_gps_{name}: erstellt")
                tables = {row[0] for row in con.execute("""SELECT table_name FROM information_schema.tables
                    WHERE table_catalog = 'result' AND table_schema = 'main' AND table_type = 'BASE TABLE'""").fetchall()}
                if tables != EXPECTED_TABLES:
                    raise RuntimeError(f"Unerwartete Tabellen: {tables ^ EXPECTED_TABLES}")
            finally:
                con.execute("USE memory")
                con.execute("DETACH result")
            staged_output.rename(output)
        print("\nABDECKUNG PRO AGENCY (alle Eingangssignale inklusive fehlender trip_id)")
        for agency, n, matched, missing in coverage:
            print(f"{str(agency):8} Gesamt: {n:>10,}  GTFS-Matches: {matched:>10,}"
                  f"  ({100 * matched / n:6.2f} %)  Ohne trip_id: {missing:,}")
        print(f"\nFertig: {actual:,} Signale in {output}\nTabelle: gps_pings")
        print("Exakte ID-Zuordnung; Fahrplan-Gueltigkeit und aktive Service-Tage nicht geprueft.")
    finally:
        con.close()


def main():
    # Datei liegt in <Repository>/analytics/.
    project = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=project / "data/vehicle_databases",
                        help="Verzeichnis mit YYYYMMDD.db oder einzelne Quelldatenbank")
    parser.add_argument("--gtfs-root", type=Path, default=project / "data/operation-plans")
    parser.add_argument("--calendar", type=Path, default=project / "data/calendario.xlsx")
    parser.add_argument("--output", type=Path, default=project / "data/hackthecity.db")
    parser.add_argument("--all-gps", action="store_true",
                        help="Alle GPS-Signale wie CarolinaPipeline statt nur exakt zugeordneter Busse")
    parser.add_argument("--create-indexes", action="store_true",
                        help="Optionale GPS-Indizes erstellen (zusaetzlicher Speicherplatz erforderlich)")
    args = parser.parse_args()
    build(args.source, args.gtfs_root, args.output, args.calendar, args.all_gps, args.create_indexes)


if __name__ == "__main__":
    main()
