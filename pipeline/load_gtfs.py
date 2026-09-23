"""
Load the 4 operator GTFS folders into unified reference tables.

OWNER:   A
INPUT:   ../operation-plans
OUTPUT:  data/interim/gtfs_*.parquet

TODO:
  [ ] line, pattern, stop, pattern_stop, trip, stop_time
  [ ] keep stop_id as string
  [ ] corridor_line from config
"""
