"""In analytics/ ablegen und vom Repository aus ausfuehren.

python analytics/build_bus_database.py
Optional: --source PATH --gtfs-root PATH --output PATH
Nur exakte ID-Zuordnung; keine Pruefung von Fahrplan-Gueltigkeit oder
Servicekalendern. Originalsignale bleiben unveraendert, auch Wiederholungen.
"""
import argparse
import csv
from pathlib import Path
import duckdb

# Zuordnung der Fahrzeug-API zu den vier besprochenen GTFS-Verzeichnissen.
PLANS = {
    "20251002_41_YEAR_03_47_02": "LA77N",
    "2025922_42_YEAR_03.03.55": "BNA17",
    "20250924_43_YEAR_04_05_01": "YA15B",
    "20250930_44_YEAR_04_20_01": "A2L1N",
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


def build(source, root, output):
    source, root, output = [Path(p).resolve() for p in (source, root, output)]
    if not source.is_file():
        raise FileNotFoundError(source)
    if source == output or output.exists():
        raise FileExistsError(f"Zieldatei existiert bereits: {output}. Anderen Namen waehlen.")

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

    # Aufbau zuerst im Arbeitsspeicher; Quelle ausschliesslich lesend oeffnen.
    con = duckdb.connect()
    try:
        con.execute(f"ATTACH {literal(source)} AS src (READ_ONLY)")
        columns = {row[0] for row in con.execute("DESCRIBE src.main.vehicles").fetchall()}
        required = {"_id", "vehicle_id", "trip_id", "agency_id", "latitude", "longitude"}
        if required - columns:
            raise ValueError(f"vehicles: Spalten fehlen: {sorted(required - columns)}")
        # Den gewaehlten Zeitstempel unveraendert uebernehmen, nicht umrechnen.
        timestamp = next((c for c in ("timestamp_criado", "created_at") if c in columns), None)
        if timestamp is None:
            raise ValueError("vehicles: timestamp_criado oder created_at erforderlich.")
        print(f"Zeitstempelquelle: {timestamp} -> timestamp_criado (unveraendert)")
        con.execute("""CREATE TEMP TABLE raw_mapping (
            agency_id VARCHAR, trip_id VARCHAR, route_id VARCHAR,
            linha VARCHAR, direction_id INTEGER, gtfs_source VARCHAR)""")
        con.executemany("INSERT INTO raw_mapping VALUES (?, ?, ?, ?, ?, ?)", mappings)
        con.execute("CREATE TEMP TABLE mapping AS SELECT DISTINCT * FROM raw_mapping")
        conflicts = con.execute("""SELECT agency_id, trip_id, COUNT(*)
            FROM mapping GROUP BY 1, 2 HAVING COUNT(*) > 1 LIMIT 10""").fetchall()
        if conflicts:
            raise ValueError(f"Mehrdeutige GTFS-Zuordnungen, Abbruch: {conflicts}")

        # Pro Eingangssignal maximal eine Zuordnung; keine Signale deduplizieren.
        con.execute("""CREATE TEMP TABLE coverage AS
            SELECT CAST(g.agency_id AS VARCHAR) AS agency_id,
                   COUNT(*) AS input_signals,
                   COUNT(m.trip_id) AS matched_signals,
                   COUNT(*) FILTER (WHERE g.trip_id IS NULL OR
                       TRIM(CAST(g.trip_id AS VARCHAR)) = '') AS missing_trip_id
            FROM src.main.vehicles g LEFT JOIN mapping m
              ON CAST(g.trip_id AS VARCHAR) = m.trip_id
             AND CAST(g.agency_id AS VARCHAR) = m.agency_id
            GROUP BY 1""")
        total = con.execute("SELECT SUM(matched_signals) FROM coverage").fetchone()[0] or 0
        if total == 0:
            raise ValueError("Keine passenden Signale gefunden; keine Ausgabedatenbank erstellt.")

        output.parent.mkdir(parents=True, exist_ok=True)
        con.execute(f"ATTACH {literal(output)} AS result")
        con.execute("BEGIN TRANSACTION")
        try:
            con.execute(f"""CREATE TABLE result.main.bus_signals AS
                SELECT g._id, g.vehicle_id, g.trip_id, g.latitude, g.longitude,
                       g.{identifier(timestamp)} AS timestamp_criado,
                       m.route_id, m.linha, m.direction_id,
                       g.agency_id, m.gtfs_source
                FROM src.main.vehicles g INNER JOIN mapping m
                  ON CAST(g.trip_id AS VARCHAR) = m.trip_id
                 AND CAST(g.agency_id AS VARCHAR) = m.agency_id""")
            actual = con.execute("SELECT COUNT(*) FROM result.main.bus_signals").fetchone()[0]
            if actual != total:
                raise RuntimeError("Zeilenzahl stimmt nicht mit Zuordnungsstatistik ueberein.")
            con.execute("CREATE TABLE result.main.mapping_coverage AS SELECT * FROM coverage")
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        print("\nABDECKUNG PRO AGENCY (alle Eingangssignale inklusive fehlender trip_id)")
        for agency, n, matched, missing in con.execute(
                "SELECT * FROM coverage ORDER BY input_signals DESC").fetchall():
            print(f"{str(agency):8} Gesamt: {n:>10,}  Uebernommen: {matched:>10,}"
                  f"  ({100 * matched / n:6.2f} %)  Ohne trip_id: {missing:,}")
        print(f"\nFertig: {actual:,} Signale in {output}\nTabelle: bus_signals")
        print("Exakte ID-Zuordnung; Fahrplan-Gueltigkeit und aktive Service-Tage nicht geprueft.")
    finally:
        con.close()


def main():
    # Datei liegt in <Repository>/analytics/.
    project = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=project / "data/vehicle_databases/20260831.db")
    parser.add_argument("--gtfs-root", type=Path, default=project / "data/operation-plans")
    parser.add_argument("--output", type=Path, default=project / "data/vehicle_databases/20260831_bus_matched.duckdb")
    args = parser.parse_args()
    build(args.source, args.gtfs_root, args.output)


if __name__ == "__main__":
    main()
