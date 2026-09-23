"""
Read all vehicles/<geohash>/<date>/1.csv, keep bus agencies, de-duplicate.

OWNER:   A
INPUT:   raw vehicles CSVs
OUTPUT:  data/interim/pings_raw.parquet

TODO:
  [ ] dedup on (agency_id, vehicle_id, created_at)
  [ ] drop trains/metro/ferry
  [ ] drop _id, driver_id
"""
