"""
Enrich + clean pings.

OWNER:   A
INPUT:   pings_raw + gtfs
OUTPUT:  data/interim/pings_clean.parquet

TODO:
  [ ] parse trip_id (src/bunching/ids.py)
  [ ] remove GPS jumps (>150 km/h)
  [ ] flag trips matched/unmatched to GTFS
"""
