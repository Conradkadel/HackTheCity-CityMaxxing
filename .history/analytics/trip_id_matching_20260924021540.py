from pathlib import Path

import duckdb
import pandas as pd


# =========================================================
# PATHS
# =========================================================

ROOT = Path(__file__).resolve().parents[1]

DB_FILE = ROOT / "data" / "vehicle_databases" / "20260831.db"

GTFS_DIR = (
    ROOT
    / "data"
    / "operation-plans"
    / "20251002_41_YEAR_03_47_02"
)

TRIPS_FILE = GTFS_DIR / "trips.txt"


# =========================================================
# 1. CHECK FILES
# =========================================================

print("\nFILES")
print("=" * 60)

print(f"Vehicle database: {DB_FILE}")
print(f"GTFS trips file:  {TRIPS_FILE}")

if not DB_FILE.exists():
    raise FileNotFoundError(
        f"Vehicle database not found:\n{DB_FILE}"
    )

if not TRIPS_FILE.exists():
    raise FileNotFoundError(
        f"trips.txt not found:\n{TRIPS_FILE}"
    )


# =========================================================
# 2. LOAD GTFS TRIPS
# =========================================================

gtfs_trips = pd.read_csv(
    TRIPS_FILE,
    dtype=str
)

print("\nGTFS DATA")
print("=" * 60)

print(f"Operation plan:          {GTFS_DIR.name}")
print(f"Total rows:              {len(gtfs_trips):,}")
print(f"Unique trip_ids:         {gtfs_trips['trip_id'].nunique():,}")
print(f"Unique routes:           {gtfs_trips['route_id'].nunique():,}")

if "pattern_id" in gtfs_trips.columns:
    print(
        f"Unique patterns:         "
        f"{gtfs_trips['pattern_id'].nunique():,}"
    )


# =========================================================
# 3. LOAD VEHICLE TRIP IDs
# =========================================================

con = duckdb.connect(
    str(DB_FILE),
    read_only=True
)

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

print(
    f"Unique trip_id + agency combinations: "
    f"{len(vehicle_trips):,}"
)

print(
    f"Unique trip_ids:                      "
    f"{vehicle_trips['trip_id'].nunique():,}"
)

print(
    f"GPS points:                           "
    f"{vehicle_trips['gps_points'].sum():,}"
)


# =========================================================
# 4. PREPARE GTFS COLUMNS
# =========================================================

wanted_columns = [
    "trip_id",
    "route_id",
    "pattern_id",
    "trip_headsign",
    "direction_id",
    "service_id",
    "shape_id",
    "block_id",
]

# Only use columns that actually exist in trips.txt
wanted_columns = [
    column
    for column in wanted_columns
    if column in gtfs_trips.columns
]


# =========================================================
# 5. MATCH VEHICLE trip_id -> GTFS trip_id
# =========================================================

comparison = vehicle_trips.merge(
    gtfs_trips[wanted_columns],
    on="trip_id",
    how="left",
    indicator=True,
)


# =========================================================
# 6. MATCH STATISTICS
# =========================================================

matched_trip_ids = set(
    comparison.loc[
        comparison["_merge"] == "both",
        "trip_id"
    ]
)

vehicle_trips["matched"] = (
    vehicle_trips["trip_id"]
    .isin(matched_trip_ids)
)


n_total = vehicle_trips["trip_id"].nunique()

n_matched = vehicle_trips.loc[
    vehicle_trips["matched"],
    "trip_id"
].nunique()

n_unmatched = n_total - n_matched

match_rate = (
    100 * n_matched / n_total
    if n_total
    else 0
)


print("\nMATCH RESULTS")
print("=" * 60)

print(f"Vehicle trip_ids:       {n_total:,}")
print(f"Matched trip_ids:       {n_matched:,}")
print(f"Unmatched trip_ids:     {n_unmatched:,}")
print(f"Match rate:             {match_rate:.2f} %")


# =========================================================
# 7. GPS POINT COVERAGE
# =========================================================

gps_total = vehicle_trips["gps_points"].sum()

gps_matched = vehicle_trips.loc[
    vehicle_trips["matched"],
    "gps_points"
].sum()

gps_match_rate = (
    100 * gps_matched / gps_total
    if gps_total
    else 0
)


print("\nGPS POINT COVERAGE")
print("=" * 60)

print(f"Total GPS points:       {gps_total:,}")
print(f"Matched GPS points:     {gps_matched:,}")
print(f"Coverage:               {gps_match_rate:.2f} %")


# =========================================================
# 8. MATCH RATE BY VEHICLE AGENCY
# =========================================================

print("\nMATCH RATE BY VEHICLE AGENCY")
print("=" * 80)

agency_stats = (
    vehicle_trips
    .groupby("agency_id")
    .agg(
        trip_ids=("trip_id", "nunique"),
        gps_points=("gps_points", "sum"),
        matched_trip_ids=("matched", "sum"),
    )
)


agency_stats["trip_match_pct"] = (
    100
    * agency_stats["matched_trip_ids"]
    / agency_stats["trip_ids"]
)


matched_gps = (
    vehicle_trips[
        vehicle_trips["matched"]
    ]
    .groupby("agency_id")["gps_points"]
    .sum()
)


agency_stats["matched_gps_points"] = (
    matched_gps
    .reindex(agency_stats.index)
    .fillna(0)
    .astype(int)
)


agency_stats["gps_match_pct"] = (
    100
    * agency_stats["matched_gps_points"]
    / agency_stats["gps_points"]
)


print(
    agency_stats
    .sort_values(
        "gps_points",
        ascending=False
    )
    .to_string()
)


# =========================================================
# 9. EXAMPLE SUCCESSFUL MATCHES
# =========================================================

print("\nEXAMPLE MATCHES")
print("=" * 80)

display_columns = [
    column
    for column in [
        "trip_id",
        "agency_id",
        "route_id",
        "pattern_id",
        "direction_id",
        "trip_headsign",
        "service_id",
        "shape_id",
        "block_id",
        "gps_points",
        "vehicles",
    ]
    if column in comparison.columns
]


matched_examples = (
    comparison.loc[
        comparison["_merge"] == "both",
        display_columns
    ]
    .sort_values(
        "gps_points",
        ascending=False
    )
    .head(30)
)


print(
    matched_examples.to_string(
        index=False
    )
)


# =========================================================
# 10. EXAMPLE UNMATCHED TRIP IDs
# =========================================================

print("\nEXAMPLE UNMATCHED TRIP IDs")
print("=" * 80)

unmatched = (
    vehicle_trips[
        ~vehicle_trips["matched"]
    ]
    .sort_values(
        "gps_points",
        ascending=False
    )
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
    .to_string(
        index=False
    )
)


# =========================================================
# 11. MATCHED ROUTES
# =========================================================

print("\nMATCHED ROUTES")
print("=" * 80)

matched_routes = (
    comparison[
        comparison["_merge"] == "both"
    ]
    .groupby("route_id")
    .agg(
        trip_ids=("trip_id", "nunique"),
        gps_points=("gps_points", "sum"),
        vehicles=("vehicles", "sum"),
    )
    .sort_values(
        "gps_points",
        ascending=False
    )
)


print(
    matched_routes
    .head(30)
    .to_string()
)


# =========================================================
# 12. SUMMARY
# =========================================================

print("\nSUMMARY")
print("=" * 80)

print(f"GTFS operation plan:    {GTFS_DIR.name}")
print(f"GTFS trip_ids:          {gtfs_trips['trip_id'].nunique():,}")
print(f"Vehicle trip_ids:       {n_total:,}")
print(f"Matched trip_ids:       {n_matched:,}")
print(f"Trip match rate:        {match_rate:.2f} %")
print(f"GPS point coverage:     {gps_match_rate:.2f} %")

print("\nDone.")