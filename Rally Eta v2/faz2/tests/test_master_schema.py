import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.data.master_schema import apply_master_schema, normalize_name_key


class MasterSchemaMigrationTests(unittest.TestCase):
    def test_normalize_name_key_handles_turkish_variants(self):
        self.assertEqual(normalize_name_key("Ali Türkkan"), "ali turkkan")
        self.assertEqual(normalize_name_key(" ALİ   TÜRKKAN "), "ali turkkan")
        self.assertEqual(normalize_name_key("Ali-Türkkan"), "ali turkkan")

    def test_apply_master_schema_creates_canonical_dimensions(self):
        Path(".tmp_testdata").mkdir(exist_ok=True)
        db_path = Path(".tmp_testdata") / f"master_schema_{next(tempfile._get_candidate_names())}.db"
        report_path = Path(".tmp_testdata") / f"master_schema_{next(tempfile._get_candidate_names())}.json"
        conn = None
        try:
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                CREATE TABLE stage_results (
                    result_id TEXT PRIMARY KEY,
                    rally_id TEXT,
                    rally_name TEXT,
                    stage_number INTEGER,
                    stage_name TEXT,
                    stage_length_km REAL,
                    car_number TEXT,
                    driver_name TEXT,
                    car_class TEXT,
                    time_seconds REAL,
                    surface TEXT,
                    normalized_class TEXT,
                    ratio_to_class_best REAL,
                    class_position INTEGER
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE stages_metadata (
                    stage_id TEXT PRIMARY KEY,
                    rally_id TEXT,
                    stage_name TEXT,
                    distance_km REAL,
                    total_ascent REAL,
                    total_descent REAL,
                    max_grade REAL,
                    hairpin_count INTEGER,
                    hairpin_density REAL,
                    p95_curvature REAL,
                    curvature_density REAL,
                    surface TEXT,
                    kml_file TEXT,
                    processed_at TEXT
                )
                """
            )
            conn.executemany(
                """
                INSERT INTO stage_results (
                    result_id, rally_id, rally_name, stage_number, stage_name,
                    stage_length_km, car_number, driver_name, car_class,
                    time_seconds, surface, normalized_class, ratio_to_class_best, class_position
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    ("171_ss1_1", "171", "Test Rally", 1, "SS1", 10.5, "1", "Ali Türkkan", "Rally2", 600.0, "gravel", "Rally2", 1.0, 1),
                    ("171_ss1_2", "171", "Test Rally", 1, "SS1", 10.5, "2", "ALİ TÜRKKAN", "Rally2", 603.0, "gravel", "Rally2", 1.005, 2),
                ],
            )
            conn.execute(
                """
                INSERT INTO stages_metadata (
                    stage_id, rally_id, stage_name, distance_km, total_ascent, total_descent,
                    max_grade, hairpin_count, hairpin_density, p95_curvature, curvature_density,
                    surface, kml_file, processed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "171_ss1",
                    "171",
                    "SS1",
                    10.5,
                    0.0,
                    0.0,
                    0.0,
                    4,
                    0.4,
                    0.01,
                    0.2,
                    "gravel",
                    "sample.kml",
                    "2026-03-27T12:00:00",
                ),
            )
            conn.commit()
            conn.close()

            result = apply_master_schema(str(db_path), str(report_path))

            self.assertEqual(result["drivers"], 1)
            self.assertEqual(result["stages"], 1)
            self.assertEqual(result["rallies"], 1)
            self.assertEqual(result["red_flagged_rows"], 1)

            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            self.assertEqual(cur.execute("SELECT COUNT(*) FROM drivers").fetchone()[0], 1)
            self.assertEqual(cur.execute("SELECT COUNT(*) FROM driver_aliases").fetchone()[0], 2)
            self.assertEqual(cur.execute("SELECT COUNT(*) FROM stages").fetchone()[0], 1)
            self.assertEqual(cur.execute("SELECT COUNT(*) FROM stage_geometry").fetchone()[0], 1)
            self.assertEqual(cur.execute("SELECT COUNT(*) FROM stages_metadata").fetchone()[0], 1)
            self.assertEqual(
                cur.execute(
                    "SELECT COUNT(*) FROM stage_results WHERE driver_id IS NOT NULL AND stage_id = '171_ss1'"
                ).fetchone()[0],
                2,
            )
            self.assertEqual(
                cur.execute(
                    "SELECT geometry_status FROM stage_geometry WHERE stage_id = '171_ss1'"
                ).fetchone()[0],
                "red_flag_missing_elevation",
            )
            prediction_log_columns = {
                row[1] for row in cur.execute("PRAGMA table_info(prediction_log)").fetchall()
            }
            self.assertTrue({"resolved_issue_types", "resolution_note", "resolved_at", "resolution_source"}.issubset(prediction_log_columns))
            conn.close()
            conn = None
        finally:
            if conn is not None:
                conn.close()
            db_path.unlink(missing_ok=True)
            report_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
