import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.data.results_merge import merge_results_database


def _create_legacy_stage_results_db(path: Path, rows: list[tuple]) -> None:
    conn = sqlite3.connect(path)
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
            co_driver_name TEXT,
            car_class TEXT,
            vehicle TEXT,
            time_str TEXT,
            time_seconds REAL,
            diff_str TEXT,
            diff_seconds REAL,
            surface TEXT
        )
        """
    )
    conn.executemany(
        """
        INSERT INTO stage_results (
            result_id, rally_id, rally_name, stage_number, stage_name, stage_length_km,
            car_number, driver_name, co_driver_name, car_class, vehicle,
            time_str, time_seconds, diff_str, diff_seconds, surface
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    conn.close()


class ResultsMergeTests(unittest.TestCase):
    def test_merge_results_database_handles_insert_skip_and_conflict(self):
        Path(".tmp_testdata").mkdir(exist_ok=True)
        master_db = Path(".tmp_testdata") / f"merge_master_{next(tempfile._get_candidate_names())}.db"
        incoming_db = Path(".tmp_testdata") / f"merge_incoming_{next(tempfile._get_candidate_names())}.db"
        backup_dir = Path(".tmp_testdata") / f"merge_backups_{next(tempfile._get_candidate_names())}"
        report_dir = Path(".tmp_testdata") / f"merge_reports_{next(tempfile._get_candidate_names())}"

        try:
            _create_legacy_stage_results_db(
                master_db,
                [
                    ("171_ss1_1", "171", "Test Rally", 1, "SS1", 10.5, "1", "Ali Türkkan", "", "Rally2", "Fabia", "10:00.0", 600.0, "", 0.0, "gravel"),
                    ("171_ss1_2", "171", "Test Rally", 1, "SS1", 10.5, "2", "Burak Çukurova", "", "Rally2", "Fabia", "10:10.0", 610.0, "+10.0", 10.0, "gravel"),
                ],
            )
            _create_legacy_stage_results_db(
                incoming_db,
                [
                    ("171_ss1_1", "171", "Test Rally", 1, "SS1", 10.5, "1", "Ali Türkkan", "", "Rally2", "Fabia", "10:00.0", 600.0, "", 0.0, "gravel"),
                    ("171_ss1_2", "171", "Test Rally", 1, "SS1", 10.5, "2", "Burak Çukurova", "", "Rally2", "Fabia", "10:11.0", 611.0, "+11.0", 11.0, "gravel"),
                    ("171_ss1_3", "171", "Test Rally", 1, "SS1", 10.5, "3", "Efehan Yazıcı", "", "Rally2", "Fabia", "10:30.0", 630.0, "+30.0", 30.0, "gravel"),
                ],
            )

            summary = merge_results_database(
                master_db_path=str(master_db),
                incoming_db_path=str(incoming_db),
                backup_dir=str(backup_dir),
                report_dir=str(report_dir),
            )

            self.assertEqual(summary.inserted_rows, 1)
            self.assertEqual(summary.skipped_rows, 1)
            self.assertEqual(summary.conflict_rows, 1)
            self.assertEqual(summary.incoming_rows, 3)
            self.assertEqual(summary.incoming_duplicate_rows, 0)
            self.assertEqual(summary.conflict_result_ids, ["171_ss1_2"])

            conn = sqlite3.connect(master_db)
            cur = conn.cursor()
            self.assertEqual(cur.execute("SELECT COUNT(*) FROM stage_results").fetchone()[0], 3)
            self.assertEqual(cur.execute("SELECT COUNT(*) FROM merge_conflicts").fetchone()[0], 1)
            self.assertEqual(cur.execute("SELECT COUNT(*) FROM drivers").fetchone()[0], 3)
            self.assertEqual(cur.execute("SELECT COUNT(*) FROM stages").fetchone()[0], 1)
            self.assertEqual(
                cur.execute(
                    "SELECT stage_id, driver_id, normalized_class, class_position FROM stage_results WHERE result_id = '171_ss1_3'"
                ).fetchone(),
                ("171_ss1", "drv_efehan-yazici", "Rally2", 3),
            )
            self.assertEqual(
                cur.execute(
                    "SELECT COUNT(*) FROM merge_log WHERE merge_scope = 'results_merge'"
                ).fetchone()[0],
                1,
            )
            conn.close()

            for backup_path in summary.backups.values():
                self.assertTrue(Path(backup_path).exists(), backup_path)
            self.assertTrue(Path(summary.merge_log_path).exists())
            self.assertTrue(Path(summary.alias_report_path).exists())
        finally:
            for path in [master_db, incoming_db]:
                path.unlink(missing_ok=True)
            for folder in [backup_dir, report_dir]:
                if folder.exists():
                    for item in folder.glob("*"):
                        item.unlink(missing_ok=True)
                    folder.rmdir()


if __name__ == "__main__":
    unittest.main()
