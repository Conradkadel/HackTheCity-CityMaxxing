import csv
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import duckdb
import pandas as pd

from analytics.build_bus_database import EXPECTED_TABLES, build, discover_sources


class BuildBusDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sources = self.root / "sources"
        self.sources.mkdir()
        self.output = self.sources / "all_days_bus_matched.duckdb"
        pd.DataFrame({"date": ["2026-08-31"], "day_type": ["weekday"]}).to_excel(
            self.root / "calendario.xlsx", index=False)
        plan = self.root / "plans" / "test-plan"
        plan.mkdir(parents=True)
        for name, rows in {
            "routes": [("route_id", "route_type", "route_short_name"), ("route", 3, "1715")],
            "trips": [("trip_id", "route_id", "direction_id"), ("trip", "route", 0)],
            "stops": [("stop_id", "stop_name", "stop_lat", "stop_lon"), ("001", "Stop", 1, 2)],
            "stop_times": [("trip_id", "stop_id", "arrival_time", "departure_time", "stop_sequence"),
                           ("trip", "001", "08:00:00", "08:00:00", 1)],
            "shapes": [("shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"), ("shape", 1, 2, 1)],
            "calendar_dates": [("service_id", "date", "exception_type"), ("service", "20260831", 1)],
        }.items():
            with (plan / f"{name}.txt").open("w", newline="", encoding="utf-8") as handle:
                csv.writer(handle).writerows(rows)
        self.plans = patch("analytics.build_bus_database.PLANS", {"test-plan": "agency"})
        self.plans.start()
        self.addCleanup(self.plans.stop)

    def database(self, name, trips, timestamp="created_at"):
        path = self.sources / name
        with duckdb.connect(str(path)) as con:
            con.execute(f"""CREATE TABLE vehicles (
                _id VARCHAR, vehicle_id VARCHAR, trip_id VARCHAR, agency_id VARCHAR,
                latitude DOUBLE, longitude DOUBLE, {timestamp} BIGINT,
                driver_id VARCHAR, stop_id VARCHAR, operational_date VARCHAR,
                received_at BIGINT, geohash_5 VARCHAR)""")
            for trip in trips:
                con.execute("""INSERT INTO vehicles VALUES ('same-id', 'bus', ?, 'agency', 1, 2, 123,
                    'driver', '001', ?, 456, 'eyckp')""", [trip, path.stem])
        return path

    def run_build(self, source=None, all_gps=False):
        with redirect_stdout(StringIO()):
            build(source or self.sources, self.root / "plans", self.output, all_gps=all_gps)

    def test_combines_days_with_carolina_tables_types_and_preserved_duplicates(self):
        self.database("20260831.db", ["trip", "trip", None])
        self.database("20260901.db", ["trip", "unknown"], "timestamp_criado")
        # Existing generated databases must never be treated as daily inputs.
        (self.sources / "20260831_bus_matched.duckdb").touch()
        self.run_build()
        with duckdb.connect(str(self.output), read_only=True) as con:
            self.assertEqual({row[0] for row in con.execute("SHOW TABLES").fetchall()}, EXPECTED_TABLES)
            self.assertEqual(con.execute("SELECT COUNT(*), MIN(epoch_ms(timestamp_criado)), MAX(epoch_ms(timestamp_criado)) FROM gps_pings").fetchone(), (3, 123, 123))
            self.assertEqual(con.execute("SELECT operational_date, COUNT(*) FROM gps_pings GROUP BY 1 ORDER BY 1").fetchall(), [("20260831", 2), ("20260901", 1)])
            self.assertEqual([(r[0], r[1]) for r in con.execute("DESCRIBE gps_pings").fetchall()], [
                ("_id", "VARCHAR"), ("agency_id", "VARCHAR"), ("driver_id", "VARCHAR"),
                ("vehicle_id", "VARCHAR"), ("trip_id", "VARCHAR"), ("stop_id", "VARCHAR"),
                ("latitude", "FLOAT"), ("longitude", "FLOAT"), ("operational_date", "VARCHAR"),
                ("timestamp_criado", "TIMESTAMP"), ("timestamp_recebido", "TIMESTAMP"), ("geohash_5", "VARCHAR")])
            self.assertEqual(con.execute("SELECT COUNT(*), MIN(route_short_name), MIN(stop_id) FROM tb_gps_filtrado").fetchone(), (3, "1715", "001"))
            self.assertEqual(con.execute("SELECT MIN(epoch_ms(timestamp_recebido)) FROM gps_pings").fetchone()[0], 456)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM tb_calendario").fetchone()[0], 1)
            self.assertTrue(all(r[1] == "VARCHAR" for r in con.execute("DESCRIBE gtfs_stops").fetchall()))
        self.assertEqual(len(discover_sources(self.sources)), 2)

    def test_first_day_without_matches_does_not_prevent_later_matches(self):
        self.database("20260831.db", ["unknown"])
        self.database("20260901.db", ["trip"])
        self.run_build()
        with duckdb.connect(str(self.output), read_only=True) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM gps_pings").fetchone()[0], 1)

    def test_all_gps_includes_unmatched_and_missing_trip_records(self):
        self.database("20260831.db", ["trip", "unknown", None])
        self.run_build(all_gps=True)
        with duckdb.connect(str(self.output), read_only=True) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM gps_pings").fetchone()[0], 3)

    def test_shared_filter_and_bunching_definitions(self):
        source = self.database("20260831.db", ["trip"])
        with duckdb.connect(str(source)) as con:
            con.execute("""INSERT INTO vehicles SELECT 'second', 'bus2', trip_id, agency_id,
                latitude, longitude, created_at + 60000, driver_id, stop_id,
                operational_date, received_at + 60000, geohash_5 FROM vehicles""")
            con.execute("""INSERT INTO vehicles SELECT 'outside', 'bus3', trip_id, agency_id,
                latitude, longitude, created_at + 30000, driver_id, stop_id,
                operational_date, received_at + 30000, 'xxxxx' FROM vehicles LIMIT 1""")
        self.run_build()
        with duckdb.connect(str(self.output), read_only=True) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM tb_gps_filtrado").fetchone()[0], 2)
            self.assertEqual(con.execute("SELECT linha, headway_segundos, nivel_bunching FROM tb_bunching_events").fetchall(), [("1715", 60, "CRÍTICO")])

    def test_single_file_and_existing_output_protection(self):
        source = self.database("custom.db", ["trip"])
        self.run_build(source)
        with self.assertRaises(FileExistsError):
            self.run_build(source)
        with duckdb.connect(str(source), read_only=True) as con:
            self.assertEqual(con.execute("SHOW TABLES").fetchall(), [("vehicles",)])

    def test_no_matches_leaves_no_output(self):
        self.database("20260831.db", [None, "unknown"])
        with self.assertRaisesRegex(ValueError, "Keine passenden Signale"):
            self.run_build()
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.sources.glob(".bus-build-*")), [])

    def test_late_invalid_schema_leaves_no_partial_output(self):
        self.database("20260831.db", ["trip"])
        self.database("20260901.db", ["trip"], "invalid_timestamp")
        with self.assertRaisesRegex(ValueError, "timestamp_criado oder created_at"):
            self.run_build()
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.sources.glob(".bus-build-*")), [])

    def test_discovery_ignores_invalid_dates_and_rejects_empty_directory(self):
        (self.sources / "20260230.db").touch()
        (self.sources / "other.db").touch()
        with self.assertRaises(FileNotFoundError):
            discover_sources(self.sources)
        source = self.database("20260901.db", [])
        self.assertEqual(discover_sources(self.sources), [source.resolve()])


if __name__ == "__main__":
    unittest.main()
