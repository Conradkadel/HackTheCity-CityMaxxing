# Combined bus database

From the repository root:

```powershell
python analytics/build_bus_database.py
python analytics/analyse_bus_database.py
```

The builder reads every `YYYYMMDD.db` in `data/vehicle_databases/` and creates
`data/hackthecity.db`. Existing outputs are protected; use `--output PATH` for
another build. `--source PATH` accepts either a directory or one daily database.

The output follows the table definitions in `CarolinaPipeline/`:

| Tables | Contents |
| --- | --- |
| `gps_pings` | GPS fields, text IDs, `FLOAT` coordinates, and SQL timestamps converted from Unix milliseconds |
| `gtfs_calendar_dates`, `gtfs_routes`, `gtfs_shapes`, `gtfs_stop_times`, `gtfs_stops`, `gtfs_trips` | GTFS files under `data/operation-plans/`, with all columns stored as text |
| `tb_calendario` | The first sheet of `data/calendario.xlsx` |
| `tb_gps_filtrado` | Carolina's geohash and route filters, with route information |
| `tb_bunching_events` | Carolina's headway calculation and severity categories |

The default GPS scope remains the exact GTFS-matched bus records from the earlier
builder. Add `--all-gps` to include all raw GPS records as Carolina's original
loader does. Repeated records are retained. The shared backend SQL lives in
`CarolinaPipeline/processar_filtros_backend.py`; both entry points call it.

GPS indexes are optional: `--create-indexes` adds Carolina's three indexes and
requires substantial extra disk space. The builder publishes the output only
after all ten tables have been created successfully.

The analysis script defaults to `gps_pings` and writes
`reports/bus_database_summary.csv`. To inspect the previous database, pass
`--database data/vehicle_databases/all_days_bus_matched.duckdb --table bus_signals`.
