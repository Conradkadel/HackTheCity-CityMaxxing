"""Combine data/vehicles/<area>/<YYYYMMDD>/*.csv into one database per day.

Run all days: python analytics/data_inspection.py
Run one day: python analytics/data_inspection.py --date 20260906
Outputs: data/vehicle_databases/<day>.db (DuckDB format).
"""

from __future__ import annotations

import argparse
import csv
import shutil
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import duckdb
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "vehicles"
DATABASE_DIR = ROOT / "data" / "vehicle_databases"
COLUMNS = (
    "_id", "agency_id", "created_at", "driver_id", "latitude", "longitude",
    "operational_date", "received_at", "stop_id", "trip_id", "vehicle_id", "geohash_5",
)
NUMERIC_COLUMNS = ("latitude", "longitude", "created_at", "received_at")


def valid_date(value: str) -> bool:
    try:
        return len(value) == 8 and datetime.strptime(value, "%Y%m%d").strftime("%Y%m%d") == value
    except ValueError:
        return False


def discover_days(data_dir: Path = DATA_DIR, date: str | None = None) -> dict[str, list[Path]]:
    """Group file paths by folder date without reading any CSV contents."""
    if date is not None and not valid_date(date):
        raise ValueError("--date must be a valid date in YYYYMMDD format")
    days: dict[str, list[Path]] = {}
    for folder in sorted(Path(data_dir).glob("*/*")):
        if not folder.is_dir() or not valid_date(folder.name):
            continue
        if date is not None and folder.name != date:
            continue
        paths = sorted(folder.glob("*.csv"))
        if paths:
            days.setdefault(folder.name, []).extend(paths)
    if not days:
        raise ValueError(f"No CSVs found under {data_dir}/<area>/{date or '<YYYYMMDD>'}/")
    return dict(sorted(days.items()))


def build_day_database(
    day: str, paths: list[Path], database_dir: Path = DATABASE_DIR,
    memory_limit: str = "1GB",
) -> Path:
    """Read only this day's files; preserve every row and the original string IDs."""
    if not valid_date(day):
        raise ValueError(f"Invalid folder date: {day}")
    headers = {}
    for path in paths:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            header = next(csv.reader(handle), [])
        if len(header) != len(COLUMNS) or set(header) != set(COLUMNS):
            raise ValueError(f"Incompatible CSV header in {path}: {header}")
        headers[path] = header

    database_dir = Path(database_dir)
    database_dir.mkdir(parents=True, exist_ok=True)
    target = database_dir / f"{day}.db"
    # Replace an existing day only after a successful build; never append on rerun.
    with TemporaryDirectory(prefix=f".building-{day}-", dir=database_dir) as temp:
        temporary_db = Path(temp) / target.name
        with duckdb.connect(str(temporary_db)) as connection:
            connection.execute("SET memory_limit = ?", [memory_limit])
            connection.execute("SET threads = 1")
            connection.execute("SET preserve_insertion_order = false")
            schema = ", ".join(f'"{name}" VARCHAR' for name in (*COLUMNS, "source_file"))
            connection.execute(f"CREATE TABLE vehicles ({schema})")
            projection = ", ".join(
                f'nullif(trim("{name}"), \'\') AS "{name}"' for name in COLUMNS
            )
            for index, path in enumerate(paths, 1):
                print(f"  [{index}/{len(paths)}] {path.parent.parent.name}/{day}/{path.name}", flush=True)
                # Explicit string types avoid guessing IDs or reading other days.
                # Each file's header order is used, then normalized by name.
                source = connection.read_csv(
                    str(path.resolve()), columns={name: "VARCHAR" for name in headers[path]},
                    auto_detect=False, header=True, delimiter=",", quotechar='"',
                    escapechar='"', filename=True, strict_mode=True,
                    na_values=["", "NA", "N/A", "NaN", "NULL", "null", "None"],
                ).project(projection + ", filename AS source_file")
                source.insert_into("vehicles")
            count = connection.sql("SELECT count(*) FROM vehicles").fetchone()[0]
        # TemporaryDirectory uses a private Windows ACL. Moving its database
        # directly would retain that ACL and deny access to the user's account.
        # A fresh file in database_dir inherits the destination permissions.
        publish_path = database_dir / f".{day}-{uuid4().hex}.db"
        try:
            shutil.copyfile(temporary_db, publish_path)
            publish_path.replace(target)
        finally:
            publish_path.unlink(missing_ok=True)
    print(f"Saved {day}: {count:,} rows in {target}", flush=True)
    return target


def inspect_database(database: Path, memory_limit: str = "1GB") -> dict[str, pd.DataFrame]:
    """Return exact daily statistics, including outliers outside 1.5*IQR fences."""
    with duckdb.connect(str(database), read_only=True) as connection:
        connection.execute("SET memory_limit = ?", [memory_limit])
        connection.execute("SET threads = 1")
        connection.execute("SET preserve_insertion_order = false")
        overview = connection.sql('''
            SELECT count(*) AS rows, count(DISTINCT source_file) AS nonempty_files,
                   count(DISTINCT vehicle_id) AS unique_vehicle_ids,
                   count(DISTINCT agency_id) AS unique_agencies
            FROM vehicles
        ''').df()
        total = int(overview.iloc[0]["rows"])
        counts = connection.sql(
            "SELECT " + ", ".join(f'count("{name}")' for name in COLUMNS) + " FROM vehicles"
        ).fetchone()
        columns = pd.DataFrame([
            {"column": name, "non_null": count, "missing": total - count,
             "missing_pct": 100 * (total - count) / total if total else 0.0}
            for name, count in zip(COLUMNS, counts)
        ]).set_index("column")

        numeric_rows = []
        outlier_rows = []
        for name in NUMERIC_COLUMNS:
            print(f"  Calculating {name} statistics...", flush=True)
            frame = connection.sql(f'''
                WITH parsed AS (
                    SELECT {name} AS raw, try_cast({name} AS DOUBLE) AS value FROM vehicles
                ), finite AS (
                    SELECT raw, CASE WHEN isfinite(value) THEN value END AS value FROM parsed
                )
                SELECT count(value) AS valid_count,
                       count(*) FILTER (WHERE raw IS NOT NULL AND value IS NULL) AS invalid_count,
                       avg(value) AS mean, stddev_samp(value) AS std,
                       min(value) AS min, max(value) AS max, max(value) - min(value) AS range,
                       quantile_cont(value, [0.25, 0.5, 0.75]) AS quantiles
                FROM finite
            ''').df()
            quantiles = frame.pop("quantiles").iloc[0]
            for index, label in enumerate(("q25", "median", "q75")):
                frame[label] = quantiles[index] if hasattr(quantiles, "__len__") else float("nan")
            frame["iqr"] = frame["q75"] - frame["q25"]
            stats = frame.iloc[0]
            lower = float(stats["q25"] - 1.5 * stats["iqr"])
            upper = float(stats["q75"] + 1.5 * stats["iqr"])
            below = above = 0
            if stats["valid_count"]:
                # A second scan counts exact outliers without collecting rows
                # into Python. Null, malformed and infinite values are excluded.
                below, above = connection.execute(f'''
                    WITH parsed AS (
                        SELECT try_cast({name} AS DOUBLE) AS value FROM vehicles
                    )
                    SELECT count(*) FILTER (WHERE value < ?),
                           count(*) FILTER (WHERE value > ?)
                    FROM parsed WHERE isfinite(value)
                ''', [lower, upper]).fetchone()
            outlier_rows.append({
                "column": name, "lower_fence": lower, "upper_fence": upper,
                "below_fence": below, "above_fence": above,
                "outlier_count": below + above,
                "outlier_pct": (
                    100 * (below + above) / stats["valid_count"]
                    if stats["valid_count"] else float("nan")
                ),
            })
            frame.insert(0, "column", name)
            numeric_rows.append(frame)

        date_rows = []
        for name in ("created_at", "received_at", "operational_date"):
            expression = (
                f"try_strptime({name}, '%Y%m%d')" if name == "operational_date"
                else f"TRY(epoch_ms(try_cast({name} AS BIGINT)))"
            )
            frame = connection.sql(f'''
                WITH parsed AS (SELECT {name} AS raw, {expression} AS value FROM vehicles)
                SELECT count(value) AS valid_count,
                       count(*) FILTER (WHERE raw IS NOT NULL AND value IS NULL) AS invalid_count,
                       min(value) AS earliest, max(value) AS latest,
                       max(value) - min(value) AS range FROM parsed
            ''').df()
            frame.insert(0, "column", name)
            date_rows.append(frame)
        by_file = connection.sql('''
            SELECT source_file, count(*) AS rows FROM vehicles
            GROUP BY source_file ORDER BY source_file
        ''').df()
    return {
        "overview": overview, "columns": columns,
        "numeric": pd.concat(numeric_rows, ignore_index=True).set_index("column"),
        "outliers": pd.DataFrame(outlier_rows).set_index("column"),
        "dates": pd.concat(date_rows, ignore_index=True).set_index("column"),
        "by_file": by_file,
    }


def print_reports(reports: dict[str, pd.DataFrame]) -> None:
    """Print readable tables with metrics down the page, without truncation."""
    def show(title: str, frame: pd.DataFrame, *, index: bool = True) -> None:
        print(f"\n{'-' * 60}\n{title}\n{'-' * 60}")
        print(frame.to_string(
            index=index, na_rep="N/A",
            float_format=lambda value: f"{value:,.6f}".rstrip("0").rstrip("."),
        ))

    show("OVERVIEW", reports["overview"].T.rename(columns={0: "value"}))
    show("MISSING VALUES (ALL VARIABLES)", reports["columns"])
    metrics = {
        "valid_count": "Valid numeric values", "invalid_count": "Invalid numeric values",
        "min": "Minimum", "max": "Maximum", "range": "Range (max - min)",
        "mean": "Mean", "std": "Standard deviation (sample)",
        "q25": "Q1 (25%)", "median": "Median / Q2 (50%)", "q75": "Q3 (75%)",
        "iqr": "IQR (Q3 - Q1)",
    }
    show("NUMERIC STATISTICS", reports["numeric"][list(metrics)].T.rename(index=metrics))
    print("Latitude/longitude are degrees; created_at/received_at are Unix milliseconds.")
    print("IDs are categorical; numeric means and quartiles are not calculated for them.")
    show("OUTLIERS (1.5 x IQR RULE)", reports["outliers"].T.rename(index={
        "lower_fence": "Lower fence (Q1 - 1.5*IQR)",
        "upper_fence": "Upper fence (Q3 + 1.5*IQR)",
        "below_fence": "Count below lower fence", "above_fence": "Count above upper fence",
        "outlier_count": "Total outliers", "outlier_pct": "% of valid numeric values",
    }))
    print("Values strictly outside the fences are flagged; no rows are removed.")
    print("Outlier flags indicate unusual values, not necessarily incorrect data.")
    show("DATE COVERAGE (UTC)", reports["dates"].T)
    files = reports["by_file"].copy()
    files["source_file"] = files["source_file"].map(lambda value: "/".join(Path(value).parts[-3:]))
    show("ROWS BY SOURCE FILE", files, index=False)


def load_day_dataframe(day: str, database_dir: Path = DATABASE_DIR) -> pd.DataFrame:
    """Load one saved day's rows into pandas (requires enough RAM for that day)."""
    if not valid_date(day):
        raise ValueError(f"Invalid date: {day}")
    with duckdb.connect(str(Path(database_dir) / f"{day}.db"), read_only=True) as connection:
        return connection.sql("SELECT * FROM vehicles").df()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--database-dir", type=Path, default=DATABASE_DIR)
    parser.add_argument("--date", help="Process only this YYYYMMDD date")
    parser.add_argument("--memory-limit", default="1GB")

    args = parser.parse_args()

    try:
        # Find all available days from the raw CSV folders
        days = discover_days(args.data_dir, args.date)

        print(f"Days to process: {', '.join(days)}", flush=True)

        for day, paths in days.items():

            print(f"\n{'=' * 60}")
            print(f"Processing {day}")
            print(f"{'=' * 60}")

            database = args.database_dir / f"{day}.db"

            # --------------------------------------------------
            # 1. Build database only if it does not exist
            # --------------------------------------------------

            if database.exists():
                print(f"Database already exists: {database}")
                print("Skipping database creation.")

            else:
                print(f"Database does not exist.")
                print(f"Building database from {len(paths)} CSV files...")

                database = build_day_database(
                    day,
                    paths,
                    args.database_dir,
                    args.memory_limit,
                )

            # --------------------------------------------------
            # 2. Analyse database
            # --------------------------------------------------

            print("\nRunning analysis...")

            reports = inspect_database(
                database,
                args.memory_limit,
            )

            # --------------------------------------------------
            # 3. Print results to terminal
            # --------------------------------------------------

            print_reports(reports)

        print(f"\n{'=' * 60}")
        print("Analysis finished.")
        print(f"{'=' * 60}")

    except (ValueError, OSError, duckdb.Error) as exc:
        parser.exit(
            1,
            f"Inspection failed: {exc}\n"
        )

if __name__ == "__main__":
    main()
