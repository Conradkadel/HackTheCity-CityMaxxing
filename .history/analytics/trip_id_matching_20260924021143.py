from pathlib import Path

import duckdb
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]

DB_FILE = ROOT / "data" / "vehicle_databases" / "20260831.db"
OPERATION_PLANS_DIR = ROOT / "data" / "operation-plans"


# ---------------------------------------------------------
# 1. Find all trips.txt files
# ---------------------------------------------------------

trip_files = sorted(OPERATION_PLANS_DIR.glob("*/trips.txt"))

print("\nGTFS FILES FOUND")
print("=" * 60)

for file in trip_files:
    print(file.parent.name)

print(f"\nTotal trips.txt files: {len(trip_files)}")

if not trip_files:
    raise FileNotFoundError(
        f"No trips.txt files found in {OPERATION_PLANS_DIR}"
    )


# ---------------------------------------------------------
# 2. Load all GTFS trips
# ---------------------------------------------------------

gtfs_parts = []

for file in trip_files:

    df = pd.read_csv(file, dtype=str)

    # Remember which operation plan this row came from
    df["gtfs_source"] = file.parent.name

    gtfs_parts.append(df)


gtfs_trips = pd.concat(
    gtfs_parts,
    ignore_index=True
)


print("\nGTFS DATA")
print("=" * 60)

print(f"Total rows:             {len(gtfs_trips):,}")
print(f"Unique trip_ids:        {gtfs_trips['trip_id'].nunique():,}")
print(f"Operation plans:        {gtfs_trips['gtfs_source'].nunique():,}")


# ---------------------------------------------------------
# 3. Load vehicle trip IDs
# ---------------------------------------------------------

con = duckdb.connect(str(DB_FILE), read_only=True)

vehicle_trips = con.execute("""
    SELECT
        trip_id,
        agency_id,
        COUNT(*) AS gps_points,
        COUNT(DISTINCT vehicle_id) AS vehicles
    FROM vehicles
    WHERE trip_id IS NOT NULL
      AND trip_id != ''
    GROUP BY
        trip_id,
        agency_id
""").fetchdf()

con.close()


print("\nVEHICLE DATA")
print("=" * 60)

print(f"Unique trip_id + agency combinations: {len(vehicle_trips):,}")
print(f"Unique trip_ids:                      {vehicle_trips['trip_id'].nunique():,}")
print(f"GPS points:                           {vehicle_trips['gps_points'].sum():,}")


# ---------------------------------------------------------
# 4. Match vehicle trip_id against ALL GTFS plans
# ---------------------------------------------------------

wanted_columns = [
    "trip_id",
    "route_id",
    "pattern_id",
    "trip_headsign",
    "direction_id",
    "service_id",
    "shape_id",
    "block_id",
    "gtfs_source",
]

# Only select columns that actually exist
wanted_columns = [
    col for col in wanted_columns
    if col in gtfs_trips.columns
]

comparison = vehicle_trips.merge(
    gtfs_trips[wanted_columns],
    on="trip_id",
    how="left",
    indicator=True,
)


# ---------------------------------------------------------
# 5. Match statistics
# ---------------------------------------------------------

matched_trip_ids = set(
    comparison.loc[
        comparison["_merge"] == "both",
        "trip_id"
    ]
)

vehicle_trips["matched"] = (
    vehicle_trips["trip_id"].isin(matched_trip_ids)
)


n_total = vehicle_trips["trip_id"].nunique()

n_matched = vehicle_trips.loc[
    vehicle_trips["matched"],
    "trip_id"
].nunique()

n_unmatched = n_total - n_matched

match_rate = (
    100 * n_matched / n_total
    if n_total else 0
)


print("\nMATCH RESULTS")
print("=" * 60)

print(f"Vehicle trip_ids:       {n_total:,}")
print(f"Matched trip_ids:       {n_matched:,}")
print(f"Unmatched trip_ids:     {n_unmatched:,}")
print(f"Match rate:             {match_rate:.2f} %")


# ---------------------------------------------------------
# 6. GPS point coverage
# ---------------------------------------------------------

gps_total = vehicle_trips["gps_points"].sum()

gps_matched = vehicle_trips.loc[
    vehicle_trips["matched"],
    "gps_points"
].sum()

gps_match_rate = (
    100 * gps_matched / gps_total
    if gps_total else 0
)


print("\nGPS POINT COVERAGE")
print("=" * 60)

print(f"Total GPS points:       {gps_total:,}")
print(f"Matched GPS points:     {gps_matched:,}")
print(f"Coverage:               {gps_match_rate:.2f} %")


# ---------------------------------------------------------
# 7. Which operation plan matches?
# ---------------------------------------------------------

print("\nMATCHES BY GTFS OPERATION PLAN")
print("=" * 60)

matches_by_plan = (
    comparison[
        comparison["_merge"] == "both"
    ]
    .groupby("gtfs_source")
    .agg(
        matched_trip_ids=("trip_id", "nunique"),
        gps_points=("gps_points", "sum"),
    )
    .sort_values(
        "matched_trip_ids",
        ascending=False
    )
)

print(matches_by_plan.to_string())


# ---------------------------------------------------------
# 8. Example successful mappings
# ---------------------------------------------------------

print("\nEXAMPLE MATCHES")
print("=" * 60)

display_columns = [
    col for col in [
        "trip_id",
        "agency_id",
        "route_id",
        "pattern_id",
        "direction_id",
        "trip_headsign",
        "service_id",
        "shape_id",
        "block_id",
        "gtfs_source",
        "gps_points",
        "vehicles",
    ]
    if col in comparison.columns
]

print(
    comparison.loc[
        comparison["_merge"] == "both",
        display_columns
    ]
    .sort_values(
        "gps_points",
        ascending=False
    )
    .head(30)
    .to_string(index=False)
)


# ---------------------------------------------------------
# 9. Example unmatched trip IDs
# ---------------------------------------------------------

print("\nEXAMPLE UNMATCHED TRIP IDs")
print("=" * 60)

unmatched = vehicle_trips[
    ~vehicle_trips["matched"]
].sort_values(
    "gps_points",
    ascending=False
)

print(
    unmatched[
        [
            "trip_id",
            "agency_id",
            "gps_points",
            "vehicles",
        ]
    ]
    .head(30)
    .to_string(index=False)
)


# ---------------------------------------------------------
# 10. Check if the same trip_id exists in several GTFS plans
# ---------------------------------------------------------

print("\nTRIP IDs FOUND IN MULTIPLE OPERATION PLANS")
print("=" * 60)

multi_plan = (
    gtfs_trips
    .groupby("trip_id")
    ["gtfs_source"]
    .nunique()
    .sort_values(ascending=False)
)

multi_plan = multi_plan[multi_plan > 1]

print(f"Trip IDs appearing in >1 plan: {len(multi_plan):,}")

print(
    multi_plan
    .head(20)
    .to_string()
)