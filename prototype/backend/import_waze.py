"""Import Waze jam CSV files into PostgreSQL.

The importer is explicit and safe to rerun. Each CSV row receives a
deterministic source_key, so duplicates are ignored. A source file whose
checksum was already imported is skipped.
"""

import argparse
import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from db import connect, migrate

IMPORT_LOCK = 717003
LISBON = ZoneInfo("Europe/Lisbon")

REQUIRED_COLUMNS = {
    "zona",
    "geohash6",
    "data",
    "Hora",
    "Minuto",
    "localizacao_dicofre",
    "rua",
    "cidade",
    "nivel_de_intensidade",
    "velocidade",
    "velocidade_kmh",
    "atraso",
    "comprimento",
    "latitude",
    "longitude",
    "geowkt",
    "geo",
}


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def optional_float(value):
    value = (value or "").strip()
    return float(value) if value else None


def optional_int(value):
    value = (value or "").strip()
    return int(float(value)) if value else None


def parse_timestamp(row):
    local_time = datetime.strptime(
        f"{row['data']} {int(row['Hora']):02d}:{int(row['Minuto']):02d}",
        "%Y-%m-%d %H:%M",
    )
    return local_time.replace(tzinfo=LISBON)


def row_key(row, observed_at):
    canonical = "|".join(
        [
            observed_at.isoformat(),
            (row.get("zona") or "").strip(),
            (row.get("geohash6") or "").strip(),
            (row.get("localizacao_dicofre") or "").strip(),
            (row.get("rua") or "").strip(),
            (row.get("cidade") or "").strip(),
            (row.get("nivel_de_intensidade") or "").strip(),
            (row.get("velocidade") or "").strip(),
            (row.get("velocidade_kmh") or "").strip(),
            (row.get("atraso") or "").strip(),
            (row.get("comprimento") or "").strip(),
            (row.get("latitude") or "").strip(),
            (row.get("longitude") or "").strip(),
            (row.get("geo") or row.get("geowkt") or "").strip(),
        ]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_row(row, source_file):
    observed_at = parse_timestamp(row)
    latitude = float(row["latitude"])
    longitude = float(row["longitude"])

    if not -90 <= latitude <= 90:
        raise ValueError("latitude out of range")
    if not -180 <= longitude <= 180:
        raise ValueError("longitude out of range")

    geometry = (row.get("geo") or row.get("geowkt") or "").strip()
    if not geometry:
        raise ValueError("missing geometry")

    zone = (row.get("zona") or "").strip()
    geohash_6 = (row.get("geohash6") or "").strip()
    intensity = (row.get("nivel_de_intensidade") or "").strip()

    if not zone:
        raise ValueError("missing zone")
    if not geohash_6:
        raise ValueError("missing geohash6")
    if not intensity:
        raise ValueError("missing traffic intensity")

    return (
        row_key(row, observed_at),
        observed_at,
        observed_at.astimezone(LISBON).date(),
        zone,
        geohash_6,
        (row.get("localizacao_dicofre") or "").strip() or None,
        (row.get("rua") or "").strip() or None,
        (row.get("cidade") or "").strip() or None,
        intensity,
        optional_float(row.get("velocidade")),
        optional_float(row.get("velocidade_kmh")),
        optional_int(row.get("atraso")),
        optional_int(row.get("comprimento")),
        latitude,
        longitude,
        geometry,
        source_file,
    )


def import_file(conn, path: Path, source_file: str, batch_size=5000):
    path = path.resolve()
    file_checksum = checksum(path)

    existing = conn.execute(
        "SELECT checksum FROM waze_import_files WHERE source_file=%s",
        (source_file,),
    ).fetchone()

    if existing and existing["checksum"] == file_checksum:
        return {
            "sourceFile": source_file,
            "unchanged": True,
            "checksum": file_checksum,
        }

    if existing and existing["checksum"] != file_checksum:
        raise ValueError(
            f"{source_file} was imported before but its contents changed. "
            "Rename the file or remove the previous import explicitly before retrying."
        )

    rows_read = 0
    rows_inserted = 0
    rows_skipped = 0

    with conn.transaction():
        conn.execute(
            """
            INSERT INTO waze_import_files(
              source_file, checksum, bytes, rows_read, rows_inserted, rows_skipped
            )
            VALUES(%s,%s,%s,0,0,0)
            """,
            (source_file, file_checksum, path.stat().st_size),
        )

        conn.execute(
            """
            CREATE TEMP TABLE waze_stage
            (LIKE waze_jams INCLUDING DEFAULTS)
            ON COMMIT DROP
            """
        )

        with path.open(encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)

            fieldnames = reader.fieldnames or []
            missing = REQUIRED_COLUMNS - set(fieldnames)
            if missing:
                raise ValueError(
                    f"{source_file}: missing required CSV columns: "
                    + ", ".join(sorted(missing))
                )

            batch = []

            def flush():
                nonlocal rows_inserted, rows_skipped, batch
                if not batch:
                    return

                with conn.cursor().copy(
                    """
                    COPY waze_stage (
                      source_key, observed_at, operational_date, zone, geohash_6,
                      dicofre, street, city, intensity, speed_mps, speed_kmh,
                      delay_seconds, length_meters, latitude, longitude,
                      geometry_wkt, source_file
                    )
                    FROM STDIN
                    """
                ) as copy:
                    for values in batch:
                        copy.write_row(values)

                result = conn.execute(
                    """
                    WITH applied AS (
                      INSERT INTO waze_jams
                      SELECT DISTINCT ON (source_key) *
                      FROM waze_stage
                      ORDER BY source_key
                      ON CONFLICT(source_key) DO NOTHING
                      RETURNING 1
                    )
                    SELECT count(*) AS inserted FROM applied
                    """
                ).fetchone()

                inserted = result["inserted"]
                rows_inserted += inserted
                rows_skipped += len(batch) - inserted

                conn.execute("TRUNCATE waze_stage")
                batch = []

            for row in reader:
                rows_read += 1
                try:
                    batch.append(parse_row(row, source_file))
                except (ValueError, TypeError):
                    rows_skipped += 1
                    continue

                if len(batch) >= batch_size:
                    flush()

            flush()

        conn.execute(
            """
            UPDATE waze_import_files
            SET rows_read=%s,
                rows_inserted=%s,
                rows_skipped=%s,
                imported_at=now()
            WHERE source_file=%s
            """,
            (rows_read, rows_inserted, rows_skipped, source_file),
        )

    conn.execute("ANALYZE waze_jams")

    return {
        "sourceFile": source_file,
        "checksum": file_checksum,
        "rowsRead": rows_read,
        "rowsInserted": rows_inserted,
        "rowsSkipped": rows_skipped,
    }


def run(source: Path, batch_size=5000):
    source = source.resolve()

    if source.is_file():
        files = [(source, source.name)]
    elif source.is_dir():
        paths = sorted(source.rglob("*.csv"))
        files = [(path, str(path.relative_to(source))) for path in paths]
    else:
        raise ValueError("Source must be a Waze CSV file or directory.")

    if not files:
        raise ValueError("No CSV files found.")

    with connect() as conn:
        migrate(conn)

        locked = conn.execute(
            "SELECT pg_try_advisory_lock(%s) AS locked",
            (IMPORT_LOCK,),
        ).fetchone()["locked"]

        if not locked:
            raise ValueError("Another Waze import is already running.")

        try:
            results = [
                import_file(conn, path, source_file, batch_size)
                for path, source_file in files
            ]

            coverage = conn.execute(
                """
                SELECT
                  count(*) AS observations,
                  min(observed_at) AS first_observation,
                  max(observed_at) AS last_observation,
                  count(DISTINCT operational_date) AS days,
                  count(DISTINCT zone) AS zones
                FROM waze_jams
                """
            ).fetchone()

            return {
                "files": results,
                "coverage": {
                    "observations": coverage["observations"],
                    "firstObservation": (
                        coverage["first_observation"].isoformat()
                        if coverage["first_observation"]
                        else None
                    ),
                    "lastObservation": (
                        coverage["last_observation"].isoformat()
                        if coverage["last_observation"]
                        else None
                    ),
                    "days": coverage["days"],
                    "zones": coverage["zones"],
                },
            }
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (IMPORT_LOCK,))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        required=True,
        help="Waze CSV file or directory containing Waze CSV files.",
    )
    parser.add_argument("--batch-size", type=int, default=5000)
    args = parser.parse_args()

    try:
        print(json.dumps(run(args.source, args.batch_size), indent=2))
    except Exception as exc:
        parser.exit(1, f"Import stopped: {exc}\n")
