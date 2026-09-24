"""Build a privacy-safe, portable Challenge 7 database inside PostgreSQL."""

import argparse
import os
import re
from contextlib import closing

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from db import migrate

SOURCE_DATABASE = os.environ.get("PGDATABASE", "headway")
OPERATOR = "IA9T6"
CONFIGURED_LINES = [
    "702", "703", "708", "714", "717", "718", "723", "726", "727",
    "728", "729", "734", "736", "742", "747", "750", "751", "755",
    "756", "758", "759", "760", "765", "767", "773", "774", "796",
    "12E", "15E", "28E",
]
CHALLENGE_PARENT_AREAS = ["eyckp", "eycs2", "eyckr", "eyckx", "eyckq"]
DATABASE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def connection(database):
    return psycopg.connect(
        host=os.environ.get("PGHOST", "db"),
        port=os.environ.get("PGPORT", "5432"),
        user=os.environ.get("PGUSER", "headway"),
        password=os.environ.get("PGPASSWORD", ""),
        dbname=database,
        autocommit=True,
        row_factory=dict_row,
    )


def copy_query(source, target, table, columns, query, params=()):
    column_sql = sql.SQL(",").join(map(sql.Identifier, columns))
    output_sql = sql.SQL("COPY ({}) TO STDOUT (FORMAT BINARY)").format(
        sql.SQL(query)
    )
    input_sql = sql.SQL("COPY {} ({}) FROM STDIN (FORMAT BINARY)").format(
        sql.Identifier(table), column_sql
    )
    with source.cursor().copy(output_sql, params) as output:
        with target.cursor().copy(input_sql) as destination:
            for block in output:
                destination.write(block)
    return target.execute(
        sql.SQL("SELECT count(*) AS rows FROM {}").format(sql.Identifier(table))
    ).fetchone()["rows"]


def vehicle_predicate(mode):
    clauses = ["e.version_id=%s", "e.agency_id=%s"]
    params = []
    if mode == "configured-lines":
        clauses.append("""EXISTS (
          SELECT 1 FROM plan_packages p
          JOIN schedule_trips t ON t.package_id=p.id AND t.trip_id=e.trip_id
          JOIN schedule_routes r ON r.package_id=t.package_id AND r.route_id=t.route_id
          WHERE p.event_agency_id=e.agency_id
            AND e.operational_date BETWEEN p.active_from AND p.active_until
            AND r.line_short_name=ANY(%s))""")
        params.append(CONFIGURED_LINES)
    elif mode == "challenge-areas":
        clauses.append("e.geohash_5=ANY(%s)")
        params.append(CHALLENGE_PARENT_AREAS)
    return " AND ".join(clauses), params


def create_target(source, name, replace):
    if not DATABASE_NAME.fullmatch(name) or name == SOURCE_DATABASE:
        raise ValueError("Choose a safe target database name different from the source.")
    exists = source.execute(
        "SELECT 1 FROM pg_database WHERE datname=%s", (name,)
    ).fetchone()
    if exists and not replace:
        raise ValueError(f"Target database {name!r} already exists; use --replace.")
    if exists:
        source.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname=%s AND pid<>pg_backend_pid()",
            (name,),
        )
        source.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
    source.execute(
        sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(
            sql.Identifier(name)
        )
    )


def build(target_database, mode="all-carris", replace=False):
    if mode not in {"all-carris", "configured-lines", "challenge-areas"}:
        raise ValueError("Unknown subset mode.")
    with closing(connection(SOURCE_DATABASE)) as source:
        active = source.execute(
            "SELECT version_id FROM active_dataset WHERE singleton=true"
        ).fetchone()
        if not active:
            raise ValueError("The source database has no completed active dataset.")
        version = active["version_id"]
        create_target(source, target_database, replace)

        try:
            with closing(connection(target_database)) as target:
                migrate(target)
                counts = {}
                counts["dataset_versions"] = copy_query(
                    source,
                    target,
                    "dataset_versions",
                    [
                        "id", "inventory_hash", "status", "created_at",
                        "completed_at", "source_root",
                    ],
                    """SELECT id,inventory_hash || ':portable:' || %s,status,
                      created_at,completed_at,'portable-carris-export'
                      FROM dataset_versions WHERE id=%s""",
                    (mode, version),
                )
                counts["plan_packages"] = copy_query(
                    source,
                    target,
                    "plan_packages",
                    [
                        "id", "source_name", "checksum", "agency", "feed", "counts",
                        "imported_at", "event_agency_id", "active_from", "active_until",
                        "external_plan_id", "normalized_gtfs_id",
                    ],
                    """SELECT id,source_name,checksum,agency,feed,
                      jsonb_set(counts,'{stop_times}','0'::jsonb),imported_at,
                      event_agency_id,active_from,active_until,external_plan_id,
                      normalized_gtfs_id FROM plan_packages
                      WHERE event_agency_id=%s""",
                    (OPERATOR,),
                )
                package_ids = [
                    row["id"]
                    for row in source.execute(
                        "SELECT id FROM plan_packages WHERE event_agency_id=%s",
                        (OPERATOR,),
                    )
                ]
                if not package_ids:
                    raise ValueError("No CARRIS plan package is registered in the source.")
                counts["plan_records"] = copy_query(
                    source,
                    target,
                    "plan_records",
                    ["package_id", "table_name", "row_number", "data"],
                    """SELECT package_id,table_name,row_number,data FROM plan_records
                      WHERE package_id=ANY(%s) AND table_name<>'stop_times'""",
                    (package_ids,),
                )
                for table, columns in (
                    (
                        "schedule_routes",
                        ["package_id", "route_id", "line_short_name", "route_long_name", "route_color"],
                    ),
                    (
                        "schedule_trips",
                        ["package_id", "trip_id", "route_id", "shape_id", "direction_id", "service_id"],
                    ),
                    (
                        "schedule_stop_visits",
                        ["package_id", "trip_id", "stop_id", "stop_sequence", "arrival_time", "departure_time"],
                    ),
                ):
                    counts[table] = copy_query(
                        source,
                        target,
                        table,
                        columns,
                        f"SELECT {','.join(columns)} FROM {table} WHERE package_id=ANY(%s)",
                        (package_ids,),
                    )

                predicate, extra_params = vehicle_predicate(mode)
                vehicle_columns = [
                    "version_id", "observation_key", "event_id", "agency_id",
                    "vehicle_id", "driver_id", "trip_id", "stop_id", "created_at",
                    "received_at", "operational_date", "latitude", "longitude", "geohash_5",
                ]
                counts["vehicle_events"] = copy_query(
                    source,
                    target,
                    "vehicle_events",
                    vehicle_columns,
                    f"""SELECT version_id,observation_key,event_id,agency_id,vehicle_id,
                      'redacted'::text,trip_id,stop_id,created_at,received_at,
                      operational_date,latitude,longitude,geohash_5
                      FROM vehicle_events e WHERE {predicate}""",
                    (version, OPERATOR, *extra_params),
                )
                target.execute(
                    """INSERT INTO availability
                      SELECT version_id,geohash_5,
                        (created_at AT TIME ZONE 'Europe/Lisbon')::date,
                        agency_id,count(*),min(created_at),max(created_at)
                      FROM vehicle_events GROUP BY 1,2,3,4"""
                )
                target.execute(
                    "INSERT INTO active_dataset(singleton,version_id) VALUES(true,%s)",
                    (version,),
                )
                target.execute(
                    "SELECT setval(pg_get_serial_sequence('dataset_versions','id'),%s,true)",
                    (version,),
                )
                target.execute(
                    "SELECT setval(pg_get_serial_sequence('plan_packages','id'),%s,true)",
                    (max(package_ids),),
                )
                target.execute("ANALYZE")
                size = target.execute(
                    "SELECT pg_database_size(current_database()) AS bytes"
                ).fetchone()["bytes"]
                return {"database": target_database, "mode": mode, "bytes": size, "counts": counts}
        except Exception:
            with closing(connection(SOURCE_DATABASE)) as cleanup:
                cleanup.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname=%s AND pid<>pg_backend_pid()",
                    (target_database,),
                )
                cleanup.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {}").format(
                        sql.Identifier(target_database)
                    )
                )
            raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-database", default="headway_carris_export")
    parser.add_argument(
        "--mode",
        choices=("all-carris", "configured-lines", "challenge-areas"),
        default="all-carris",
    )
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    print(build(args.target_database, args.mode, args.replace))
