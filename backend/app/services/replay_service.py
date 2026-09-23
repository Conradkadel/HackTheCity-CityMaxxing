"""
Replay frames + alerts

OWNER:   C (+D for simulation)
INPUT:   DuckDB views
OUTPUT:  python dicts / DataFrames

TODO:
  [ ] get_frames(corridor,date,from,to) – paginate by time window, get_alerts(ts)
  [ ] no FastAPI imports here
"""
