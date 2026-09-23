"""
Headway per passage (same line/dir) + corridor headway.

OWNER:   A
INPUT:   stop_passages + stop_time
OUTPUT:  data/processed/headways.parquet

TODO:
  [ ] leader = previous bus same pattern/stop/day
  [ ] sched_headway from timetable (fallback: typical observed)
  [ ] headway_ratio
"""
