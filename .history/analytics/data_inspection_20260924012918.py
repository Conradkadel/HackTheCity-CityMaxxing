"""Combine data/vehicles/<area>/<YYYYMMDD>/*.csv into one database per day.

Run all days:
    python analytics/data_inspection.py

Run one day:
    python analytics/data_inspection.py --date 20260906

Outputs:
    data/vehicle_databases/<day>.db (DuckDB format).

Existing databases are reused.
Analysis is restricted to agencies that can operate buses.
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


# ============================================================
# PATHS / CONFIGURATION
# ============================================================

ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = ROOT / "data" / "vehicles"
DATABASE_DIR = ROOT / "data" / "vehicle_databases"

COLUMNS = (
    "_id",
    "agency_id",
    "created_at",
    "driver_id",
    "latitude",
    "longitude",
    "operational_date",
    "received_at",
    "stop_id",
    "trip_id",
    "vehicle_id",
    "geohash_5",
)

NUMERIC_COLUMNS = (
    "latitude",
    "longitude",
    "created_at",
    "received_at",
)


# ============================================================
# BUS OPERATORS
# ============================================================

# Only agencies that can operate buses are kept.
#
# Carris Metropolitana Areas 1-4 and MobiCascais are bus
# operators.
#
# Carris also operates trams, so IA9T6 cannot yet be assumed
# to contain buses only. It is kept because it DOES contain
# buses.
#
# Explicitly excluded:
# N18KL -> Comboios de Portugal (rail)
# 7NTB1 -> Fertagus (rail)
# IA2N9 -> Metropolitano de Lisboa (metro)
# LTP61 -> Soflusa (ferry)

BUS_AGENCIES = (
    "IA9T6",  # Carris
    "LA77N",  # Carris Metropolitana Área 1
    "BNA17",  # Carris Metropolitana Área 2
    "YA15B",  # Carris Metropolitana Área 3
    "A2L1N",  # Carris Metropolitana Área 4
    "HF16N",  # MobiCascais
)


# ============================================================
# DATE VALIDATION
# ============================================================

def valid_date(value: str) -> bool:
    """Check whether a string is a valid YYYYMMDD date."""

    try:
        return (
            len(value) == 8
            and datetime.strptime(value, "%Y%m%d").strftime("%Y%m%d")
            == value
        )
    except ValueError:
        return False


# ============================================================
# DISCOVER RAW DATA
# ============================================================

def discover_days(
    data_dir: Path = DATA_DIR,
    date: str | None = None,
) -> dict[str, list[Path]]:
    """Group CSV file paths by folder date."""

    if date is not None and not valid_date(date):
        raise ValueError(
            "--date must be a valid date in YYYYMMDD format"
        )

    days: dict[str, list[Path]] = {}

    for folder in sorted(Path(data_dir).glob("*/*")):

        if not folder.is_dir():
            continue

        if not valid_date(folder.name):
            continue

        if date is not None and folder.name != date:
            continue

        paths = sorted(folder.glob("*.csv"))

        if paths:
            days.setdefault(folder.name, []).extend(paths)

    if not days:
        raise ValueError(
            f"No CSVs found under "
            f"{data_dir}/<area>/{date or '<YYYYMMDD>'}/"
        )

    return dict(sorted(days.items()))


# ============================================================
# BUILD DATABASE
# ============================================================

def build_day_database(
    day: str,
    paths: list[Path],
    database_dir: Path = DATABASE_DIR,
    memory_limit: str = "1GB",
) -> Path:
    """Build one DuckDB database containing all records of a day."""

    if not valid_date(day):
        raise ValueError(f"Invalid folder date: {day}")

    headers = {}

    # --------------------------------------------------------
    # Validate CSV headers
    # --------------------------------------------------------

    for path in paths:

        with path.open(
            encoding="utf-8-sig",
            newline="",
        ) as handle:

            header = next(
                csv.reader(handle),
                [],
            )

        if (
            len(header) != len(COLUMNS)
            or set(header) != set(COLUMNS)
        ):
            raise ValueError(
                f"Incompatible CSV header in {path}: {header}"
            )

        headers[path] = header

    database_dir = Path(database_dir)

    database_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    target = database_dir / f"{day}.db"

    # --------------------------------------------------------
    # Build database in temporary directory
    # --------------------------------------------------------

    with TemporaryDirectory(
        prefix=f".building-{day}-",
        dir=database_dir,
    ) as temp:

        temporary_db = Path(temp) / target.name

        with duckdb.connect(
            str(temporary_db)
        ) as connection:

            connection.execute(
                "SET memory_limit = ?",
                [memory_limit],
            )

            connection.execute(
                "SET threads = 1"
            )

            connection.execute(
                "SET preserve_insertion_order = false"
            )

            schema = ", ".join(
                f'"{name}" VARCHAR'
                for name in (*COLUMNS, "source_file")
            )

            connection.execute(
                f"CREATE TABLE vehicles ({schema})"
            )

            projection = ", ".join(
                f'nullif(trim("{name}"), \'\') AS "{name}"'
                for name in COLUMNS
            )

            # ------------------------------------------------
            # Insert CSV files
            # ------------------------------------------------

            for index, path in enumerate(paths, 1):

                print(
                    f"  [{index}/{len(paths)}] "
                    f"{path.parent.parent.name}/"
                    f"{day}/{path.name}",
                    flush=True,
                )

                source = connection.read_csv(
                    str(path.resolve()),
                    columns={
                        name: "VARCHAR"
                        for name in headers[path]
                    },
                    auto_detect=False,
                    header=True,
                    delimiter=",",
                    quotechar='"',
                    escapechar='"',
                    filename=True,
                    strict_mode=True,
                    na_values=[
                        "",
                        "NA",
                        "N/A",
                        "NaN",
                        "NULL",
                        "null",
                        "None",
                    ],
                ).project(
                    projection
                    + ", filename AS source_file"
                )

                source.insert_into("vehicles")

            count = connection.sql(
                "SELECT count(*) FROM vehicles"
            ).fetchone()[0]

        # ----------------------------------------------------
        # Publish database with correct Windows permissions
        # ----------------------------------------------------

        publish_path = (
            database_dir
            / f".{day}-{uuid4().hex}.db"
        )

        try:

            shutil.copyfile(
                temporary_db,
                publish_path,
            )

            publish_path.replace(target)

        finally:

            publish_path.unlink(
                missing_ok=True
            )

    print(
        f"Saved {day}: {count:,} rows in {target}",
        flush=True,
    )

    return target


# ============================================================
# DATABASE ANALYSIS
# ============================================================

def inspect_database(
    database: Path,
    memory_limit: str = "1GB",
) -> dict[str, pd.DataFrame]:
    """
    Analyse bus-related vehicle records only.

    The original database is NOT modified.

    A temporary view called bus_vehicles is created that
    contains only agencies that can operate buses.
    """

    with duckdb.connect(
        str(database),
        read_only=True,
    ) as connection:

        connection.execute(
            "SET memory_limit = ?",
            [memory_limit],
        )

        connection.execute(
            "SET threads = 1"
        )

        connection.execute(
            "SET preserve_insertion_order = false"
        )

        # ====================================================
        # BUS FILTER
        # ====================================================

        agency_list = ", ".join(
            f"'{agency}'"
            for agency in BUS_AGENCIES
        )

        total_rows = connection.sql(
            """
            SELECT COUNT(*)
            FROM vehicles
            """
        ).fetchone()[0]

        # Temporary view:
        # database itself stays unchanged.

        connection.execute(
            f"""
            CREATE TEMP VIEW bus_vehicles AS

            SELECT *
            FROM vehicles

            WHERE agency_id IN ({agency_list})
            """
        )

        bus_rows = connection.sql(
            """
            SELECT COUNT(*)
            FROM bus_vehicles
            """
        ).fetchone()[0]

        removed_rows = total_rows - bus_rows

        removed_pct = (
            100 * removed_rows / total_rows
            if total_rows
            else 0
        )

        print("\nBUS FILTER")
        print("-" * 60)

        print(
            f"Original rows:     {total_rows:,}"
        )

        print(
            f"Bus rows kept:     {bus_rows:,}"
        )

        print(
            f"Non-bus rows:      {removed_rows:,}"
        )

        print(
            f"Rows removed:      {removed_pct:.2f}%"
        )

        # ====================================================
        # OVERVIEW
        # ====================================================

        overview = connection.sql(
            """
            SELECT

                count(*) AS rows,

                count(DISTINCT source_file)
                    AS nonempty_files,

                count(DISTINCT vehicle_id)
                    AS unique_vehicle_ids,

                count(DISTINCT agency_id)
                    AS unique_agencies

            FROM bus_vehicles
            """
        ).df()

        total = int(
            overview.iloc[0]["rows"]
        )

        # ====================================================
        # MISSING VALUES
        # ====================================================

        counts = connection.sql(

            "SELECT "
            + ", ".join(
                f'count("{name}")'
                for name in COLUMNS
            )
            + " FROM bus_vehicles"

        ).fetchone()

        columns = pd.DataFrame(
            [
                {
                    "column": name,

                    "non_null": count,

                    "missing": total - count,

                    "missing_pct": (
                        100
                        * (total - count)
                        / total
                        if total
                        else 0.0
                    ),
                }

                for name, count
                in zip(COLUMNS, counts)
            ]
        ).set_index("column")

        # ====================================================
        # NUMERIC STATISTICS + OUTLIERS
        # ====================================================

        numeric_rows = []
        outlier_rows = []

        for name in NUMERIC_COLUMNS:

            print(
                f"  Calculating {name} statistics...",
                flush=True,
            )

            frame = connection.sql(
                f"""
                WITH parsed AS (

                    SELECT
                        {name} AS raw,
                        try_cast({name} AS DOUBLE)
                            AS value

                    FROM bus_vehicles
                ),

                finite AS (

                    SELECT

                        raw,

                        CASE
                            WHEN isfinite(value)
                            THEN value
                        END AS value

                    FROM parsed
                )

                SELECT

                    count(value)
                        AS valid_count,

                    count(*)
                        FILTER (
                            WHERE raw IS NOT NULL
                            AND value IS NULL
                        )
                        AS invalid_count,

                    avg(value)
                        AS mean,

                    stddev_samp(value)
                        AS std,

                    min(value)
                        AS min,

                    max(value)
                        AS max,

                    max(value) - min(value)
                        AS range,

                    quantile_cont(
                        value,
                        [0.25, 0.5, 0.75]
                    )
                        AS quantiles

                FROM finite
                """
            ).df()

            quantiles = (
                frame.pop("quantiles").iloc[0]
            )

            for index, label in enumerate(
                ("q25", "median", "q75")
            ):

                frame[label] = (
                    quantiles[index]
                    if hasattr(
                        quantiles,
                        "__len__",
                    )
                    else float("nan")
                )

            frame["iqr"] = (
                frame["q75"]
                - frame["q25"]
            )

            stats = frame.iloc[0]

            lower = float(
                stats["q25"]
                - 1.5 * stats["iqr"]
            )

            upper = float(
                stats["q75"]
                + 1.5 * stats["iqr"]
            )

            below = 0
            above = 0

            if stats["valid_count"]:

                below, above = (
                    connection.execute(
                        f"""
                        WITH parsed AS (

                            SELECT
                                try_cast(
                                    {name}
                                    AS DOUBLE
                                ) AS value

                            FROM bus_vehicles
                        )

                        SELECT

                            count(*)
                                FILTER (
                                    WHERE value < ?
                                ),

                            count(*)
                                FILTER (
                                    WHERE value > ?
                                )

                        FROM parsed

                        WHERE isfinite(value)
                        """,
                        [lower, upper],
                    ).fetchone()
                )

            outlier_rows.append(
                {
                    "column": name,

                    "lower_fence": lower,

                    "upper_fence": upper,

                    "below_fence": below,

                    "above_fence": above,

                    "outlier_count":
                        below + above,

                    "outlier_pct": (
                        100
                        * (below + above)
                        / stats["valid_count"]
                        if stats["valid_count"]
                        else float("nan")
                    ),
                }
            )

            frame.insert(
                0,
                "column",
                name,
            )

            numeric_rows.append(frame)

        # ====================================================
        # DATE COVERAGE
        # ====================================================

        date_rows = []

        for name in (
            "created_at",
            "received_at",
            "operational_date",
        ):

            if name == "operational_date":

                expression = (
                    f"try_strptime("
                    f"{name}, '%Y%m%d'"
                    f")"
                )

            else:

                expression = (
                    f"TRY("
                    f"epoch_ms("
                    f"try_cast({name} AS BIGINT)"
                    f")"
                    f")"
                )

            frame = connection.sql(
                f"""
                WITH parsed AS (

                    SELECT

                        {name} AS raw,

                        {expression}
                            AS value

                    FROM bus_vehicles
                )

                SELECT

                    count(value)
                        AS valid_count,

                    count(*)
                        FILTER (
                            WHERE raw IS NOT NULL
                            AND value IS NULL
                        )
                        AS invalid_count,

                    min(value)
                        AS earliest,

                    max(value)
                        AS latest,

                    max(value) - min(value)
                        AS range

                FROM parsed
                """
            ).df()

            frame.insert(
                0,
                "column",
                name,
            )

            date_rows.append(frame)

        # ====================================================
        # ROWS BY SOURCE FILE
        # ====================================================

        by_file = connection.sql(
            """
            SELECT

                source_file,

                count(*) AS rows

            FROM bus_vehicles

            GROUP BY source_file

            ORDER BY source_file
            """
        ).df()

        # ====================================================
        # BUS OPERATORS
        # ====================================================

        by_agency = connection.sql(
            """
            SELECT

                agency_id,

                COUNT(*) AS rows,

                COUNT(DISTINCT vehicle_id)
                    AS vehicles,

                COUNT(DISTINCT trip_id)
                    AS trips

            FROM bus_vehicles

            GROUP BY agency_id

            ORDER BY rows DESC
            """
        ).df()

    # ========================================================
    # RETURN REPORTS
    # ========================================================

    return {

        "overview":
            overview,

        "columns":
            columns,

        "numeric":
            pd.concat(
                numeric_rows,
                ignore_index=True,
            ).set_index("column"),

        "outliers":
            pd.DataFrame(
                outlier_rows
            ).set_index("column"),

        "dates":
            pd.concat(
                date_rows,
                ignore_index=True,
            ).set_index("column"),

        "by_file":
            by_file,

        "by_agency":
            by_agency,
    }


# ============================================================
# PRINT REPORTS
# ============================================================

def print_reports(
    reports: dict[str, pd.DataFrame]
) -> None:
    """Print readable analysis tables to the terminal."""

    def show(
        title: str,
        frame: pd.DataFrame,
        *,
        index: bool = True,
    ) -> None:

        print(
            f"\n{'-' * 60}"
            f"\n{title}"
            f"\n{'-' * 60}"
        )

        print(
            frame.to_string(
                index=index,
                na_rep="N/A",
                float_format=lambda value:
                    f"{value:,.6f}"
                    .rstrip("0")
                    .rstrip("."),
            )
        )

    # --------------------------------------------------------
    # Overview
    # --------------------------------------------------------

    show(
        "OVERVIEW",
        reports["overview"]
        .T
        .rename(columns={0: "value"}),
    )

    # --------------------------------------------------------
    # Bus operators
    # --------------------------------------------------------

    show(
        "BUS OPERATORS",
        reports["by_agency"],
        index=False,
    )

    # --------------------------------------------------------
    # Missing values
    # --------------------------------------------------------

    show(
        "MISSING VALUES (ALL VARIABLES)",
        reports["columns"],
    )

    # --------------------------------------------------------
    # Numeric statistics
    # --------------------------------------------------------

    metrics = {

        "valid_count":
            "Valid numeric values",

        "invalid_count":
            "Invalid numeric values",

        "min":
            "Minimum",

        "max":
            "Maximum",

        "range":
            "Range (max - min)",

        "mean":
            "Mean",

        "std":
            "Standard deviation (sample)",

        "q25":
            "Q1 (25%)",

        "median":
            "Median / Q2 (50%)",

        "q75":
            "Q3 (75%)",

        "iqr":
            "IQR (Q3 - Q1)",
    }

    show(
        "NUMERIC STATISTICS",

        reports["numeric"][
            list(metrics)
        ]
        .T
        .rename(index=metrics),
    )

    print(
        "Latitude/longitude are degrees; "
        "created_at/received_at are Unix milliseconds."
    )

    print(
        "IDs are categorical; numeric means and "
        "quartiles are not calculated for them."
    )

    # --------------------------------------------------------
    # Outliers
    # --------------------------------------------------------

    show(
        "OUTLIERS (1.5 x IQR RULE)",

        reports["outliers"]
        .T
        .rename(
            index={
                "lower_fence":
                    "Lower fence (Q1 - 1.5*IQR)",

                "upper_fence":
                    "Upper fence (Q3 + 1.5*IQR)",

                "below_fence":
                    "Count below lower fence",

                "above_fence":
                    "Count above upper fence",

                "outlier_count":
                    "Total outliers",

                "outlier_pct":
                    "% of valid numeric values",
            }
        ),
    )

    print(
        "Values strictly outside the fences are flagged; "
        "no rows are removed."
    )

    print(
        "Outlier flags indicate unusual values, "
        "not necessarily incorrect data."
    )

    # --------------------------------------------------------
    # Date coverage
    # --------------------------------------------------------

    show(
        "DATE COVERAGE (UTC)",
        reports["dates"].T,
    )

    # --------------------------------------------------------
    # Source files
    # --------------------------------------------------------

    files = reports["by_file"].copy()

    files["source_file"] = (
        files["source_file"].map(
            lambda value:
                "/".join(
                    Path(value).parts[-3:]
                )
        )
    )

    show(
        "ROWS BY SOURCE FILE",
        files,
        index=False,
    )


# ============================================================
# LOAD ONE DAY INTO PANDAS
# ============================================================

def load_day_dataframe(
    day: str,
    database_dir: Path = DATABASE_DIR,
) -> pd.DataFrame:
    """
    Load bus records for one saved day into pandas.

    Requires enough RAM for the selected day.
    """

    if not valid_date(day):

        raise ValueError(
            f"Invalid date: {day}"
        )

    database = (
        Path(database_dir)
        / f"{day}.db"
    )

    agency_list = ", ".join(
        f"'{agency}'"
        for agency in BUS_AGENCIES
    )

    with duckdb.connect(
        str(database),
        read_only=True,
    ) as connection:

        return connection.sql(
            f"""
            SELECT *
            FROM vehicles
            WHERE agency_id IN ({agency_list})
            """
        ).df()


# ============================================================
# MAIN
# ============================================================

def main() -> None:

    parser = argparse.ArgumentParser(
        description=__doc__
    )

    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DATA_DIR,
    )

    parser.add_argument(
        "--database-dir",
        type=Path,
        default=DATABASE_DIR,
    )

    parser.add_argument(
        "--date",
        help="Process only this YYYYMMDD date",
    )

    parser.add_argument(
        "--memory-limit",
        default="1GB",
    )

    args = parser.parse_args()

    try:

        # ----------------------------------------------------
        # Discover days
        # ----------------------------------------------------

        days = discover_days(
            args.data_dir,
            args.date,
        )

        print(
            f"Days to process: "
            f"{', '.join(days)}",
            flush=True,
        )

        # ----------------------------------------------------
        # Process each day
        # ----------------------------------------------------

        for day, paths in days.items():

            print(
                f"\n{'=' * 60}"
            )

            print(
                f"Processing {day}"
            )

            print(
                f"{'=' * 60}"
            )

            database = (
                args.database_dir
                / f"{day}.db"
            )

            # ================================================
            # DATABASE
            # ================================================

            if database.exists():

                print(
                    f"Database already exists: "
                    f"{database}"
                )

                print(
                    "Skipping database creation."
                )

            else:

                print(
                    "Database does not exist."
                )

                print(
                    f"Building database from "
                    f"{len(paths)} CSV files..."
                )

                database = build_day_database(
                    day,
                    paths,
                    args.database_dir,
                    args.memory_limit,
                )

            # ================================================
            # ANALYSIS
            # ================================================

            print(
                "\nRunning bus-only analysis..."
            )

            reports = inspect_database(
                database,
                args.memory_limit,
            )

            # ================================================
            # TERMINAL OUTPUT
            # ================================================

            print_reports(reports)

        print(
            f"\n{'=' * 60}"
        )

        print(
            "Analysis finished."
        )

        print(
            f"{'=' * 60}"
        )

    except (
        ValueError,
        OSError,
        duckdb.Error,
    ) as exc:

        parser.exit(
            1,
            f"Inspection failed: {exc}\n",
        )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()