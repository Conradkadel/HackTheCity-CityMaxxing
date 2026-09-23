# Data contracts (agree tonight, then don't break them)

All tables = parquet in `data/…`. Times: `ts` = unix ms (UTC), plus `time_local` where useful.
Keys are **composite with agency_id**. `stop_id` is always a **string** (leading zeros!).
Scheduled fields are **nullable** (stale GTFS, no Carris/MobiCascais GTFS).

## Reference (from GTFS) – `data/interim/gtfs_*.parquet`
| table | columns | key |
|---|---|---|
| line | agency_id, line_id, short_name, long_name, color | (agency_id, line_id) |
| corridor_line | corridor_id, line_id | – |
| pattern | agency_id, pattern_id, line_id, direction, shape_wkt, length_m | pattern_id |
| stop | stop_id, name, lat, lon | stop_id |
| pattern_stop | pattern_id, stop_id, sequence, dist_m | (pattern_id, sequence) |
| trip | agency_id, trip_id, pattern_id, service_id, sched_start | (agency_id, trip_id) |
| stop_time | trip_id, stop_id, sequence, sched_time | (trip_id, sequence) |
| calendar_day | date, day_type, period_of_day map | date |
| zone | geohash, name, days_available | geohash |

## Observed – `data/interim/`
| table | columns |
|---|---|
| pings_clean | agency_id, vehicle_id, trip_id, line_id, pattern_id, direction, ts, lat, lon, next_stop_id, geohash, operational_date, dist_along_m (nullable) |
| waze_jams | zone, geohash6, ts, level, speed_kmh, delay_s, length_m, geometry_wkt |

## Derived – `data/processed/`
| table | columns | produced by |
|---|---|---|
| stop_passages | passage_id, agency_id, trip_id, vehicle_id, line_id, pattern_id, corridor_id, stop_id, seq, operational_date, ts_pass, sched_time, delay_s | pipeline |
| headways | passage_id, leader_passage_id, headway_s, sched_headway_s, headway_ratio, corridor_headway_s | pipeline |
| bunching_events | event_id, corridor_id, line_id, leader_trip, follower_trip, start_stop, end_stop, ts_start, ts_end, min_headway_s, suspected_cause | analytics |
| kpis | corridor_id, line_id, stop_id, date, hour, n_passages, bunch_rate, headway_cv, ewt_s | analytics |
| predictions | passage_id, horizon_stops, prob_bunch, model_version | ml |
| sim_results | run_id, corridor_id, date, scenario, params_json, kpi, before, after | simulation |

## Definitions (fixed)
- Stop passage = moment `next_stop_id` switches away from stop X (bus just passed X).
- Bunched = `headway_ratio < 0.25` (config), gap = `> 1.5`.
- Prediction target = pair becomes bunched within next `N=3` stops (config).

## Serving – `data/serving/` (what the API returns)
| file | shape |
|---|---|
| network/{corridor}.geojson | lines + stops |
| replay/{corridor}_{date}.parquet | ts_frame (10 s), vehicle_id, line_id, lat, lon, headway_ratio, status, prob_bunch |
| events/{corridor}_{date}.json | list of bunching_events |
| heatmap/{corridor}.parquet | stop × hour × metric |

## API (FastAPI, prefix /api/v1) – Pydantic schemas in backend/app/schemas = TS types in frontend/src/types/contracts.ts
- `GET /corridors`
- `GET /network/{corridor}`
- `GET /replay?corridor&date&from&to`
- `GET /events?corridor&date`
- `GET /heatmap?corridor&metric`
- `GET /kpis?corridor&date`
- `GET /alerts?corridor&date&ts`
- `GET /scenarios`
- `POST /simulate {corridor, date, scenario, params}`
- `GET /health`
