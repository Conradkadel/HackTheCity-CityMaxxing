"""
Group bunched passages into bunching episodes (leader/follower pairs).

OWNER:   A/E
INPUT:   headways
OUTPUT:  data/processed/bunching_events.parquet

TODO:
  [ ] pair consecutive buses
  [ ] episode start = stop where headway began shrinking
  [ ] episode end
"""
