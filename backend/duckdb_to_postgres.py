"""
Copy the team DuckDB file (hackthecity.db, built by analysis/processar_dados.py +
analysis/processar_filtros_backend.py) into Postgres, table by table, same names + columns.

    python -m backend.duckdb_to_postgres path/to/hackthecity.db            (run from code/)
    python -m backend.duckdb_to_postgres path/to/hackthecity.db --with-raw  (also gps_pings, ~35M rows – slow)

Target = DATABASE_URL (backend/.env). Existing tables with the same name are REPLACED.
Afterwards schema.sql is run to add the indexes the API needs.
Plain Python (DuckDB -> psycopg COPY), no DuckDB extensions needed.
"""
import sys
from pathlib import Path

import duckdb
import psycopg

from backend.services import DATABASE_URL

# gps_pings is the raw table – the API doesn't use it, so it is skipped by default
TABLES = ["tb_gps_filtrado", "tb_bunching_events", "tb_calendario",
          "gtfs_routes", "gtfs_trips", "gtfs_shapes", "gtfs_stops", "gtfs_stop_times", "gtfs_calendar_dates"]

# DuckDB type -> Postgres type. Anything else is copied as TEXT.
TYPES = {"VARCHAR": "TEXT", "BIGINT": "BIGINT", "INTEGER": "INTEGER", "SMALLINT": "SMALLINT",
         "FLOAT": "REAL", "DOUBLE": "DOUBLE PRECISION", "BOOLEAN": "BOOLEAN", "DATE": "DATE",
         "TIMESTAMP": "TIMESTAMP", "TIMESTAMP_NS": "TIMESTAMP", "TIMESTAMP WITH TIME ZONE": "TIMESTAMPTZ"}
BATCH = 50_000


def copy_table(duck, pg, table: str) -> None:
    cols = duck.execute(f'DESCRIBE "{table}"').fetchall()          # (name, type, ...)
    pg_cols, select = [], []
    for name, typ, *_ in cols:
        pg_type = TYPES.get(typ, "TEXT")
        pg_cols.append(f'"{name}" {pg_type}')
        select.append(f'"{name}"' if typ in TYPES else f'CAST("{name}" AS VARCHAR)')

    pg.execute(f'DROP TABLE IF EXISTS "{table}"')
    pg.execute(f'CREATE TABLE "{table}" ({", ".join(pg_cols)})')

    result = duck.execute(f'SELECT {", ".join(select)} FROM "{table}"')
    n = 0
    with pg.cursor().copy(f'COPY "{table}" FROM STDIN') as copy:
        while rows := result.fetchmany(BATCH):
            for row in rows:
                copy.write_row(row)
            n += len(rows)
            print(f"\r  {table:<22} {n:,} rows", end="", flush=True)
    print(f"\r  {table:<22} {n:,} rows")


def main(duckdb_path: str, with_raw: bool = False) -> None:
    duck = duckdb.connect(duckdb_path, read_only=True)
    existing = {r[0] for r in duck.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    with psycopg.connect(DATABASE_URL) as pg:
        for t in TABLES + (["gps_pings"] if with_raw else []):
            if t in existing:
                copy_table(duck, pg, t)
                pg.commit()                                         # keep finished tables if a later one fails
            else:
                print(f"  ! {t} not in {duckdb_path} – skipped")
        # indexes (schema.sql only uses CREATE ... IF NOT EXISTS -> safe)
        pg.execute((Path(__file__).parent / "schema.sql").read_text())
    duck.close()
    print("done.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    main(sys.argv[1], with_raw="--with-raw" in sys.argv)
