"""Describe the combined bus database without changing it.

Run: python analytics/analyse_bus_database.py
Optional: --database PATH --table NAME --output PATH
Writes one CSV row per variable and prints statistics and daily signal counts.
NA means SQL NULL, blank text, or NA/N/A/NaN/NULL/None (case insensitive).
Numeric statistics exclude missing, unparseable and non-finite values.
SQL timestamps are analysed as Unix milliseconds; dates are shown in UTC.
"""

import argparse
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd


NUMERIC_COLUMNS = {"latitude", "longitude", "timestamp_criado", "timestamp_recebido", "direction_id"}


def analyse(con, table="gps_pings"):
    relation = '"' + table.replace('"', '""') + '"'
    total = con.execute(f"SELECT COUNT(*) FROM {relation}").fetchone()[0]
    rows = []
    for name, dtype, *_ in con.execute(f"DESCRIBE {relation}").fetchall():
        column = '"' + name.replace('"', '""') + '"'
        missing = f"({column} IS NULL OR LOWER(TRIM(CAST({column} AS VARCHAR))) IN ('', 'na', 'n/a', 'nan', 'null', 'none'))"
        numeric = name in NUMERIC_COLUMNS
        value = (f"epoch_ms({column})" if dtype.startswith("TIMESTAMP") and numeric
                 else f"TRY_CAST({column} AS DOUBLE)" if numeric else column)
        # Preserve categorical IDs as text, even when they contain only digits.
        clean = f"CASE WHEN NOT {missing} THEN {value} END"
        numeric_stats = ""
        if numeric:
            clean = f"CASE WHEN isfinite({clean}) THEN {clean} END"
            numeric_stats = f""", AVG({clean}) AS mean,
                STDDEV_SAMP({clean}) AS stddev, MEDIAN({clean}) AS median,
                COUNT(*) FILTER (WHERE NOT {missing} AND ({clean}) IS NULL)
                    AS invalid_numeric"""
        stats = con.execute(f"""
            SELECT COUNT(*) FILTER (WHERE {column} IS NULL) AS sql_nulls,
                   COUNT(*) FILTER (WHERE {missing}) AS na_count,
                   COUNT(DISTINCT {clean}) AS distinct_count,
                   MIN({clean}) AS minimum, MAX({clean}) AS maximum
                   {numeric_stats}
            FROM {relation}
        """).fetchdf().iloc[0].to_dict()
        rows.append({
            "variable": name, "stored_type": dtype, "rows": total,
            "na_percent": 100 * stats["na_count"] / total if total else 0,
            "mean": None, "stddev": None, "median": None, "invalid_numeric": None,
            **stats,
        })
    return pd.DataFrame(rows)


def main():
    project = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path,
                        default=project / "data/hackthecity.db")
    parser.add_argument("--table", default="gps_pings",
                        help="Table to describe; use bus_signals for the previous database")
    parser.add_argument("--output", type=Path,
                        default=project / "reports/bus_database_summary.csv")
    args = parser.parse_args()
    if args.database.resolve() == args.output.resolve():
        parser.error("The report output must differ from the database path.")
    with duckdb.connect(str(args.database), read_only=True) as con:
        summary = analyse(con, args.table)
        print("\nVARIABLES AND MISSING VALUES (distinct counts exclude NA/invalid numeric values)")
        print(summary[["variable", "stored_type", "rows", "sql_nulls", "na_count",
                       "na_percent", "distinct_count", "invalid_numeric"]].to_string(index=False, na_rep="-"))
        print("\nNUMERIC STATISTICS (timestamp_criado is Unix milliseconds)")
        print(summary.loc[summary.variable.isin(NUMERIC_COLUMNS),
                          ["variable", "minimum", "maximum", "mean", "stddev", "median"]]
              .to_string(index=False, na_rep="-"))
        if "timestamp_criado" in summary.variable.values:
            timestamps = summary.loc[summary.variable == "timestamp_criado"].iloc[0]
            for label in ("minimum", "maximum"):
                if pd.notna(timestamps[label]):
                    print(f"Timestamp {label} (UTC): "
                          f"{datetime.fromtimestamp(float(timestamps[label]) / 1000, timezone.utc).isoformat()}")
        group = next((name for name in ("operational_date", "source_file")
                      if name in summary.variable.values), None)
        if group:
            relation = '"' + args.table.replace('"', '""') + '"'
            print(f"\nSIGNALS PER {group.upper()}")
            print(con.execute(f"SELECT {group}, COUNT(*) AS signals FROM {relation} "
                              f"GROUP BY {group} ORDER BY {group}").fetchdf().to_string(index=False))
        print("\nTABLES: " + ", ".join(row[0] for row in con.execute("SHOW TABLES").fetchall()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(args.output, index=False)
    print(f"\nFull summary (including categorical min/max): {args.output}")


if __name__ == "__main__":
    main()
