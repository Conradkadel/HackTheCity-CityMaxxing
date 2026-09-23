"""
Derive stop passage events (next_stop_id switch).

OWNER:   A
INPUT:   pings_clean
OUTPUT:  data/processed/stop_passages.parquet

TODO:
  [ ] passage = last ping before next_stop_id changes
  [ ] join sched_time from stop_time
  [ ] delay_s
"""
