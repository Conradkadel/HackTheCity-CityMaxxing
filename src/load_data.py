"""
Load and clean raw data.

Owner:  A
Input:  ../_processed/vehicles_bus_only, ../operation-plans, ../calendario.xlsx, ../Waze
Output: pings, gtfs tables, calendar, waze (DataFrames / data/processed)

TODO
  [ ] load_pings(dates, corridor): read parquet, keep only needed columns
  [ ] parse_trip_id(): line_id / direction / sched start per agency format (CM 1715_0_1_..., 2605_1_1|..., MobiCascais M13-..., Carris → None)
  [ ] remove GPS jumps (> 150 km/h)
  [ ] load_gtfs(agency): routes, trips, stop_times, stops, shapes (stop_id as string!)
  [ ] load_calendar(): day_type + period of day
  [ ] load_waze(): ts from date+hour+minute, geometry
"""
