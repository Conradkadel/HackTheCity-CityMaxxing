"""Build one vehicle database per operational day and inspect each separately.

Run: python src/data_inspection.py
Install dependencies first: python -m pip install -r requirements.txt

CSV files are read in chunks, preserving string IDs such as stop ID 020003.
Each daily DuckDB file contains a vehicles table, including source_file.
Statistics are exact by default; --approximate reduces their memory needs.
All observations are retained, including duplicate records.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
COLUMNS = (
    "_id", "agency_id", "created_at", "driver_id", "latitude", "longitude",
    "operational_date", "received_at", "stop_id", "trip_id", "vehicle_id",
    "geohash_5",
)
NUMERIC_COLUMNS = ("latitude", "longitude", "created_at", "received_at")
NA_VALUES = ["", "NA", "N/A", "NaN", "NULL", "null", "None"]


def validate_schemas(data_dir: Path) -> list[Path]:
    """Check every header before loading; reject missing/extra/repeated columns."""
    paths = sorted(data_dir.rglob("*.csv"))
    if not paths:
        raise ValueError(f"No vehicle CSV files found in {data_dir}")
    problems = []
    for path in paths:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            header = next(csv.reader(handle), [])
        if len(header) != len(COLUMNS) or set(header) != set(COLUMNS):
            problems.append(f"{path}: {header}")
    if problems:
        raise ValueError("Incompatible CSV headers:\n" + "\n".join(problems))
    return paths


def summarize(
    connection: duckdb.DuckDBPyConnection, *, exact_statistics: bool = False,
) -> dict[str, pd.DataFrame]:
    """Return profiles of the combined `vehicles` table, without dropping rows."""
    column_rows = []
    unique_column = "unique_non_null" if exact_statistics else "unique_non_null_estimate"
    # HyperLogLog and T-Digest avoid retaining every distinct ID/numeric value.
    def distinct(expression: str) -> str:
        if exact_statistics:
            return f"count(DISTINCT {expression})"
        return f"approx_count_distinct({expression})"

    suffix = "" if exact_statistics else "_estimate"
    missing_condition = " OR ".join(f'"{name}" IS NULL' for name in COLUMNS)
    base_expressions = [
        "count(*) AS total",
        "count(DISTINCT source_file) AS files",
        f"count(*) FILTER (WHERE {missing_condition}) AS rows_with_missing_values",
    ]
    if not exact_statistics:
        # Small aggregate states can share one scan of the multi-GB CSV input.
        for name in COLUMNS:
            base_expressions.extend([
                f'count("{name}") AS "{name}_count"',
                f'{distinct(name)} AS "{name}_unique"',
            ])
    print("Counting rows, missing values and distinct values...", flush=True)
    base = connection.sql(
        "SELECT " + ", ".join(base_expressions) + " FROM vehicles"
    ).df().iloc[0]
    total = int(base["total"])
    for name in COLUMNS:
        if exact_statistics:
            print(f"Profiling {name} exactly...", flush=True)
            non_null, unique = connection.sql(f'''
                SELECT count("{name}"), {distinct(name)} FROM vehicles
            ''').fetchone()
        else:
            non_null = int(base[f"{name}_count"])
            unique = int(base[f"{name}_unique"])
        column_rows.append({
            "column": name,
            "non_null": non_null,
            "missing": total - non_null,
            "missing_pct": 100 * (total - non_null) / total if total else 0.0,
            unique_column: unique,
        })
    columns = pd.DataFrame(column_rows).set_index("column")

    numeric_rows = []
    # Exact quantiles retain input values: run those columns separately. The
    # default sketches can all share a scan without accumulating the input.
    batches = [(name,) for name in NUMERIC_COLUMNS] if exact_statistics else [NUMERIC_COLUMNS]
    quantile = "quantile_cont" if exact_statistics else "approx_quantile"
    for batch in batches:
        print(f"Numeric statistics for {', '.join(batch)}...", flush=True)
        parsed, finite, aggregates = [], [], []
        for name in batch:
            value = f"{name}_value"
            parsed.append(f'try_cast("{name}" AS DOUBLE) AS {value}')
            finite.append(f"CASE WHEN isfinite({value}) THEN {value} END AS {value}")
            aggregates.append(f'''struct_pack(
                valid_count := count({value}),
                invalid_count := count(*) FILTER (WHERE "{name}" IS NOT NULL AND {value} IS NULL),
                mean := avg({value}), std := stddev_samp({value}),
                min := min({value}), max := max({value}),
                range := max({value}) - min({value}),
                quantiles := {quantile}({value}, [0.25, 0.5, 0.75])
            )''')
        # Keep source NAs separate from malformed and non-finite numbers.
        values = connection.sql(f'''
            WITH parsed AS (
                SELECT {', '.join(batch)}, {', '.join(parsed)} FROM vehicles
            ), finite AS (
                SELECT {', '.join(batch)}, {', '.join(finite)} FROM parsed
            )
            SELECT {', '.join(aggregates)} FROM finite
        ''').fetchone()
        for name, row in zip(batch, values):
            quantiles = row.pop("quantiles")
            for i, label in enumerate(("q25", "median", "q75")):
                row[label + suffix] = quantiles[i] if quantiles is not None else float("nan")
            numeric_rows.append({"column": name, **row})
    numeric = pd.DataFrame(numeric_rows).set_index("column")

    print("Date statistics...", flush=True)
    date_names = ("created_at", "received_at", "operational_date")
    parsed, aggregates = [], []
    for name in date_names:
        expression = (
            f"try_strptime({name}, '%Y%m%d')" if name == "operational_date"
            else f"TRY(epoch_ms(try_cast({name} AS BIGINT)))"
        )
        value = f"{name}_value"
        parsed.append(f"{expression} AS {value}")
        aggregates.append(f'''struct_pack(
            valid_count := count({value}),
            invalid_count := count(*) FILTER (WHERE {name} IS NOT NULL AND {value} IS NULL),
            earliest := min({value}), latest := max({value}),
            range := max({value}) - min({value})
        )''')
    date_values = connection.sql(f'''
        WITH parsed AS (
            SELECT {', '.join(date_names)}, {', '.join(parsed)} FROM vehicles
        )
        SELECT {', '.join(aggregates)} FROM parsed
    ''').fetchone()
    dates = pd.DataFrame([
        {"column": name, **row} for name, row in zip(date_names, date_values)
    ]).set_index("column")

    print("Building overview and grouped reports...", flush=True)
    overview = pd.DataFrame([{
        "rows": total,
        "columns": len(COLUMNS),
        "files": int(base["files"]),
        "statistics_mode": "exact" if exact_statistics else "bounded_memory",
        "unique_vehicles" + suffix: int(columns.loc["vehicle_id", unique_column]),
        "unique_agencies" + suffix: int(columns.loc["agency_id", unique_column]),
        "rows_with_missing_values": int(base["rows_with_missing_values"]),
        # Subtracting estimated cardinality can invent duplicates. Never do it.
        "repeated_id_rows": (
            int(columns.loc["_id", "non_null"] - columns.loc["_id", unique_column])
            if exact_statistics else pd.NA
        ),
        "duplicate_check": "exact" if exact_statistics else "not_computed",
    }])

    return {
        "overview": overview,
        "columns": columns,
        "numeric": numeric,
        "dates": dates,
        "by_file": connection.sql('''
            SELECT source_file, count(*) AS rows FROM vehicles
            GROUP BY source_file ORDER BY source_file
        ''').df(),
        "by_day": connection.sql(f'''
            SELECT operational_date, count(*) AS rows,
                   {distinct('vehicle_id')} AS unique_vehicles{suffix}
            FROM vehicles GROUP BY operational_date ORDER BY operational_date
        ''').df(),
        "by_agency": connection.sql(f'''
            SELECT agency_id, count(*) AS rows,
                   {distinct('vehicle_id')} AS unique_vehicles{suffix}
            FROM vehicles GROUP BY agency_id ORDER BY rows DESC
        ''').df(),
        "by_vehicle": connection.sql(f'''
            SELECT agency_id, vehicle_id, count(*) AS rows,
                   {distinct('operational_date')} AS operational_days{suffix},
                   {distinct('trip_id')} AS unique_trips{suffix}
            FROM vehicles GROUP BY agency_id, vehicle_id ORDER BY rows DESC
        ''').df(),
    }


def build_daily_databases(
    data_dir: Path = PROJECT_ROOT / "data" / "vehicles",
    database_dir: Path = PROJECT_ROOT / "data" / "vehicle_databases",
    *,
    memory_limit: str = "1GB",
    date: str | None = None,
    chunk_size: int = 100_000,
) -> dict[str, Path]:
    """Stream CSVs into daily databases, using row dates rather than folder names.

    Missing or invalid dates go into unknown_date.duckdb. All source CSVs are
    scanned even with date filtering, since a file can contain multiple days.
    Existing daily files are replaced only after successful ingestion, so reruns
    do not append duplicate rows. Only one database connection stays open.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if date is not None:
        if len(date) != 8 or not date.isdigit() or pd.isna(
            pd.to_datetime(date, format="%Y%m%d", errors="coerce")
        ):
            raise ValueError("--date must be a valid date in YYYYMMDD format")
    paths = validate_schemas(Path(data_dir))
    size_gb = sum(path.stat().st_size for path in paths) / 1e9
    print(f"Validated {len(paths)} CSV headers ({size_gb:.2f} GB).", flush=True)
    database_dir = Path(database_dir)
    database_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    connection = None
    active_day = None
    with TemporaryDirectory(prefix=".building-", dir=database_dir) as temp:
        try:
            for index, path in enumerate(paths, 1):
                print(f"Loading [{index}/{len(paths)}] {path.relative_to(data_dir)}...", flush=True)
                with pd.read_csv(
                    path, dtype="string", chunksize=chunk_size,
                    keep_default_na=False, na_values=NA_VALUES, encoding="utf-8-sig",
                ) as reader:
                    for chunk in reader:
                        chunk = chunk.loc[:, list(COLUMNS)]
                        for name in COLUMNS:
                            chunk[name] = chunk[name].str.strip().replace("", pd.NA)
                        raw_dates = chunk["operational_date"]
                        valid = raw_dates.str.fullmatch(r"\d{8}", na=False) & pd.to_datetime(
                            raw_dates, format="%Y%m%d", errors="coerce",
                        ).notna()
                        days = raw_dates.where(valid, "unknown_date")
                        chunk["source_file"] = str(path.resolve())
                        for day, batch in chunk.groupby(days, sort=True):
                            if date is not None and day != date:
                                continue
                            if active_day != day:
                                if connection is not None:
                                    connection.close()
                                    connection = None
                                connection = duckdb.connect(str(Path(temp) / f"{day}.duckdb"))
                                connection.execute("SET memory_limit = ?", [memory_limit])
                                connection.execute("SET threads = 1")
                                connection.execute("SET preserve_insertion_order = false")
                                active_day = day
                            connection.register("batch", batch)
                            try:
                                connection.execute(
                                    "CREATE TABLE IF NOT EXISTS vehicles AS SELECT * FROM batch LIMIT 0"
                                )
                                connection.execute("INSERT INTO vehicles BY NAME SELECT * FROM batch")
                            finally:
                                connection.unregister("batch")
                            counts[day] = counts.get(day, 0) + len(batch)
        finally:
            if connection is not None:
                connection.close()
        if date is not None and not counts:
            raise ValueError(f"No vehicle rows found for {date}")
        databases = {}
        for day in sorted(counts):
            target = database_dir / f"{day}.duckdb"
            (Path(temp) / target.name).replace(target)
            databases[day] = target
            print(f"Saved {day}: {counts[day]:,} rows to {target}", flush=True)
    return databases


def inspect_database(
    database: Path, *, memory_limit: str = "1GB", exact_statistics: bool = True,
    work_dir: Path | None = None,
) -> dict[str, pd.DataFrame]:
    """Inspect an existing daily database without reading the CSVs again."""
    if work_dir is not None:
        work_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="vehicle-inspection-", dir=work_dir) as temp:
        with duckdb.connect(str(database), read_only=True) as connection:
            connection.execute("SET memory_limit = ?", [memory_limit])
            connection.execute("SET temp_directory = ?", [temp])
            connection.execute("SET threads = 1")
            connection.execute("SET preserve_insertion_order = false")
            return summarize(connection, exact_statistics=exact_statistics)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data" / "vehicles")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "reports" / "vehicles")
    parser.add_argument("--database-dir", type=Path, default=PROJECT_ROOT / "data" / "vehicle_databases")
    parser.add_argument("--date", help="Build and inspect only this operational date (YYYYMMDD)")
    parser.add_argument("--database", type=Path, help="Inspect an existing daily DB without rebuilding")
    parser.add_argument("--memory-limit", default="1GB", help="DuckDB buffer limit (default: 1GB)")
    parser.add_argument("--work-dir", type=Path, help="Directory for temporary spill files")
    parser.add_argument("--approximate", action="store_true", help="Estimate distinct counts and quantiles to reduce memory use")
    parser.add_argument("--build-only", action="store_true", help="Create daily databases without running statistics")
    args = parser.parse_args()
    if args.database and (args.date or args.build_only):
        parser.error("--database cannot be combined with --date or --build-only")
    try:
        databases = {args.database.stem: args.database} if args.database else build_daily_databases(
            args.data_dir, args.database_dir, memory_limit=args.memory_limit, date=args.date,
        )
        if args.build_only:
            return
        for day, database in databases.items():
            print(f"\nInspecting {day}...", flush=True)
            reports = inspect_database(
                database, memory_limit=args.memory_limit, work_dir=args.work_dir,
                exact_statistics=not args.approximate,
            )
            destination = args.output_dir / day
            destination.mkdir(parents=True, exist_ok=True)
            for name, frame in reports.items():
                frame.to_csv(destination / f"{name}.csv", index=frame.index.name is not None)
                if name in ("overview", "columns", "numeric", "dates"):
                    print(f"\n{name.upper()}")
                    print(frame.to_string(index=frame.index.name is not None))
            print(f"Reports saved to {destination.resolve()}", flush=True)
        if not databases:
            print("CSV files contain no rows; no daily databases were created.")
    except (ValueError, OSError, duckdb.Error) as exc:
        parser.exit(1, f"Inspection failed: {exc}\nDaily databases already saved can be inspected using --database.\n")
    print("\nTimestamp statistics use Unix milliseconds; date bounds are UTC.")
    if not args.approximate:
        print("Repeated ID rows count occurrences after the first non-null _id; rows are retained.")
    else:
        print("Columns ending in _estimate are approximate; all other statistics are exact.")
        print("Duplicate IDs were not counted in approximate mode.")


if __name__ == "__main__":
    main()
