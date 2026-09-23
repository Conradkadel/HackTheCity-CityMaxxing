"""
Single DuckDB connection over parquet/geojson files.

OWNER:   C
INPUT:   data/serving or data/mock
OUTPUT:  query helper returning DataFrames/dicts

TODO:
  [ ] register one view per serving file pattern
  [ ] get_conn() dependency for services
"""
