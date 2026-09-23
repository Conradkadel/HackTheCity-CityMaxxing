"""
Clean Waze jams (Lisbon zones only).

OWNER:   E
INPUT:   ../Waze/*.csv
OUTPUT:  data/interim/waze_jams.parquet

TODO:
  [ ] parse date+hour+minute → ts
  [ ] parse geometry
  [ ] aggregate per zone × 15 min
"""
