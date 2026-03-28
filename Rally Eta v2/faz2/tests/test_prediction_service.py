import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.data.master_schema import apply_master_schema, normalize_name_key
from src.prediction.prediction_service import PredictionService


def _seed_driver(conn: sqlite3.Connection, driver_id: str, display_name: str, alias_name: str) -> None:
    conn.execute(
        """
        INSERT INTO drivers (driver_id, display_name, normalized_name_key, merge_review_status)
        VALUES (?, ?, ?, 'auto')
        """,
        [driver_id, display_name, normalize_name_key(display_name)],
    )
    conn.execute(
        """
        INSERT INTO driver_aliases (
            driver_id, alias_name, normalized_name_key, is_primary, merge_status
        ) VALUES (?, ?, ?, ?, 'auto')
        """,
        [driver_id, alias_name, normalize_name_key(alias_name), 0],
    )


def _seed_history(conn: sqlite3.Connection, driver_id: str, driver_name: str) -> None:
    rows = [
        ("160_ss1_1", "160", "Test Rally 160", 1, "SS1", 10.0, "1", driver_name, "", "Rally2", "Fabia", "10:00.0", 600.0, "", 0.0, "gravel", "Rally2", 1.00, 1, "160_ss1", driver_id, driver_name, "seed", "FINISHED"),
        ("160_ss1_2", "160", "Test Rally 160", 1, "SS1", 10.0, "2", "Other Driver", "", "Rally2", "Fabia", "10:10.0", 610.0, "+10.0", 10.0, "gravel", "Rally2", 1.016667, 2, "160_ss1", "drv_other-driver", "Other Driver", "seed", "FINISHED"),
        ("161_ss2_1", "161", "Test Rally 161", 2, "SS2", 12.0, "1", driver_name, "", "Rally2", "Fabia", "12:20.0", 740.0, "", 0.0, "gravel", "Rally2", 1.00, 1, "161_ss2", driver_id, driver_name, "seed", "FINISHED"),
        ("161_ss2_2", "161", "Test Rally 161", 2, "SS2", 12.0, "2", "Other Driver", "", "Rally2", "Fabia", "12:30.0", 750.0, "+10.0", 10.0, "gravel", "Rally2", 1.013514, 2, "161_ss2", "drv_other-driver", "Other Driver", "seed", "FINISHED"),
        ("162_ss1_1", "162", "Test Rally 162", 1, "SS1", 11.0, "1", driver_name, "", "Rally2", "Fabia", "11:05.0", 665.0, "", 0.0, "gravel", "Rally2", 1.00, 1, "162_ss1", driver_id, driver_name, "seed", "FINISHED"),
        ("162_ss1_2", "162", "Test Rally 162", 1, "SS1", 11.0, "2", "Other Driver", "", "Rally2", "Fabia", "11:15.0", 675.0, "+10.0", 10.0, "gravel", "Rally2", 1.015038, 2, "162_ss1", "drv_other-driver", "Other Driver", "seed", "FINISHED"),
    ]
    conn.executemany(
        """
        INSERT INTO stage_results (
            result_id, rally_id, rally_name, stage_number, stage_name, stage_length_km,
            car_number, driver_name, co_driver_name, car_class, vehicle, time_str,
            time_seconds, diff_str, diff_seconds, surface, normalized_class,
            ratio_to_class_best, class_position, stage_id, driver_id, raw_driver_name,
            source_run_id, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


class PredictionServiceTests(unittest.TestCase):
    def test_predict_manual_stage_logs_prediction(self):
        Path(".tmp_testdata").mkdir(exist_ok=True)
        db_path = Path(".tmp_testdata") / f"prediction_service_{next(tempfile._get_candidate_names())}.db"

        try:
            apply_master_schema(str(db_path))
            conn = sqlite3.connect(db_path)
            _seed_driver(conn, "drv_ali-turkkkan", "Ali Turkkkan", "ALI TURKKAN")
            _seed_history(conn, "drv_ali-turkkkan", "Ali Turkkkan")
            conn.commit()
            conn.close()

            service = PredictionService(str(db_path), model_path=None)
            result = service.predict_manual_stage(
                driver_id="drv_ali-turkkkan",
                driver_name="Ali Turkkkan",
                stage_length_km=13.5,
                surface="gravel",
                stage_number=3,
            )

            self.assertIn("prediction_id", result)
            self.assertGreater(result["predicted_time_seconds"], 0)

            conn = sqlite3.connect(db_path)
            row = conn.execute(
                "SELECT rally_id, stage_id, driver_id, comparison_status FROM prediction_log WHERE prediction_id = ?",
                [result["prediction_id"]],
            ).fetchone()
            conn.close()
            self.assertEqual(row, ("manual_prediction", "manual_prediction_ss3", "drv_ali-turkkkan", "not_applicable"))
        finally:
            db_path.unlink(missing_ok=True)

    def test_compare_predictions_with_live_stage_updates_prediction_log(self):
        Path(".tmp_testdata").mkdir(exist_ok=True)
        db_path = Path(".tmp_testdata") / f"prediction_compare_{next(tempfile._get_candidate_names())}.db"

        try:
            apply_master_schema(str(db_path))
            conn = sqlite3.connect(db_path)
            _seed_driver(conn, "drv_ali-turkkkan", "Ali Turkkkan", "ALI TURKKAN")
            conn.commit()
            conn.close()

            service = PredictionService(str(db_path), model_path=None)
            prediction_id = service.log_prediction(
                run_id="race_day_test",
                rally_id="171",
                stage_id="171_ss1",
                driver_id="drv_ali-turkkkan",
                predicted_time=610.0,
                confidence=78.0,
                used_geometry=True,
                data_quality_flags=["geometry_trusted"],
                model_version="prediction_service_live_v1",
                comparison_status="pending",
            )

            summary = service.compare_predictions_with_live_stage(
                rally_id="171",
                stage_number=1,
                stage_results=[
                    {
                        "driver_name": "ALI TURKKAN",
                        "car_class": "Rally2",
                        "time_str": "10:05.0",
                    }
                ],
                driver_name="Ali Turkkkan",
            )

            self.assertEqual(summary["matched_count"], 1)
            self.assertEqual(summary["missing_actual_count"], 0)
            self.assertAlmostEqual(summary["avg_error_pct"], 0.826, places=3)

            conn = sqlite3.connect(db_path)
            row = conn.execute(
                """
                SELECT actual_time, accepted, comparison_status
                FROM prediction_log
                WHERE prediction_id = ?
                """,
                [prediction_id],
            ).fetchone()
            conn.close()

            self.assertEqual(row, (605.0, 1, "matched"))
        finally:
            db_path.unlink(missing_ok=True)

    def test_prediction_log_summary_and_quality_breakdown(self):
        Path(".tmp_testdata").mkdir(exist_ok=True)
        db_path = Path(".tmp_testdata") / f"prediction_summary_{next(tempfile._get_candidate_names())}.db"

        try:
            apply_master_schema(str(db_path))
            conn = sqlite3.connect(db_path)
            _seed_driver(conn, "drv_ali-turkkkan", "Ali Turkkkan", "ALI TURKKAN")
            conn.commit()
            conn.close()

            service = PredictionService(str(db_path), model_path=None)
            first_id = service.log_prediction(
                run_id="summary_test_1",
                rally_id="171",
                stage_id="171_ss1",
                driver_id="drv_ali-turkkkan",
                predicted_time=610.0,
                confidence=82.0,
                used_geometry=True,
                data_quality_flags=["geometry_trusted"],
                model_version="prediction_service_live_v1",
                comparison_status="pending",
            )
            second_id = service.log_prediction(
                run_id="summary_test_2",
                rally_id="171",
                stage_id="171_ss2",
                driver_id="drv_ali-turkkkan",
                predicted_time=620.0,
                confidence=61.0,
                used_geometry=False,
                data_quality_flags=["baseline_only", "elevation_missing"],
                model_version="prediction_service_live_v1",
                comparison_status="actual_missing",
            )

            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                UPDATE prediction_log
                SET actual_time = 605.0, error_pct = 0.826, accepted = 1, compared_at = '2026-03-27T10:00:00', comparison_status = 'matched'
                WHERE prediction_id = ?
                """,
                [first_id],
            )
            conn.commit()
            conn.close()

            summary = service.get_prediction_log_summary(rally_id="171")
            self.assertEqual(summary["total_predictions"], 2)
            self.assertEqual(summary["matched_count"], 1)
            self.assertEqual(summary["actual_missing_count"], 1)
            self.assertEqual(summary["geometry_used_count"], 1)
            self.assertEqual(summary["baseline_only_count"], 1)
            self.assertAlmostEqual(summary["avg_error_pct"], 0.826, places=3)
            self.assertAlmostEqual(summary["acceptance_rate_pct"], 100.0, places=2)

            rows = service.get_prediction_log_rows(limit=10, rally_id="171", only_flag="baseline_only")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["prediction_id"], second_id)
            self.assertEqual(rows[0]["data_quality_flags_list"], ["baseline_only", "elevation_missing"])

            breakdown = service.get_prediction_quality_breakdown(rally_id="171")
            breakdown_map = {item["flag"]: item["count"] for item in breakdown}
            self.assertEqual(breakdown_map["geometry_trusted"], 1)
            self.assertEqual(breakdown_map["baseline_only"], 1)
            self.assertEqual(breakdown_map["elevation_missing"], 1)
        finally:
            db_path.unlink(missing_ok=True)

    def test_prediction_issue_worklist_filters_noise_and_surfaces_actions(self):
        Path(".tmp_testdata").mkdir(exist_ok=True)
        db_path = Path(".tmp_testdata") / f"prediction_issues_{next(tempfile._get_candidate_names())}.db"

        try:
            apply_master_schema(str(db_path))
            conn = sqlite3.connect(db_path)
            _seed_driver(conn, "drv_ali-turkkkan", "Ali Turkkkan", "ALI TURKKAN")
            conn.commit()
            conn.close()

            service = PredictionService(str(db_path), model_path=None)

            high_error_id = service.log_prediction(
                run_id="issue_test_1",
                rally_id="171",
                stage_id="171_ss3",
                driver_id="drv_ali-turkkkan",
                predicted_time=620.0,
                confidence=74.0,
                used_geometry=True,
                data_quality_flags=["geometry_trusted"],
                model_version="prediction_service_live_v1",
                comparison_status="matched",
            )
            actual_missing_id = service.log_prediction(
                run_id="issue_test_2",
                rally_id="171",
                stage_id="171_ss4",
                driver_id="drv_ali-turkkkan",
                predicted_time=630.0,
                confidence=58.0,
                used_geometry=False,
                data_quality_flags=["baseline_only", "elevation_missing"],
                model_version="prediction_service_live_v1",
                comparison_status="actual_missing",
            )
            pending_id = service.log_prediction(
                run_id="issue_test_3",
                rally_id="171",
                stage_id="171_ss5",
                driver_id="drv_ali-turkkkan",
                predicted_time=640.0,
                confidence=62.0,
                used_geometry=False,
                data_quality_flags=["baseline_only", "red_flag_missing_elevation", "elevation_missing"],
                model_version="prediction_service_live_v1",
                comparison_status="pending",
            )
            manual_id = service.log_prediction(
                run_id="issue_test_4",
                rally_id="manual_prediction",
                stage_id="manual_prediction_ss1",
                driver_id="drv_ali-turkkkan",
                predicted_time=650.0,
                confidence=40.0,
                used_geometry=False,
                data_quality_flags=["manual_input", "baseline_only"],
                model_version="prediction_service_manual_v1",
                comparison_status="not_applicable",
            )

            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                UPDATE prediction_log
                SET actual_time = 700.0, error_pct = 18.5, accepted = 0, compared_at = '2026-03-27T11:00:00'
                WHERE prediction_id = ?
                """,
                [high_error_id],
            )
            conn.commit()
            conn.close()

            issues = service.get_prediction_issue_worklist(limit=20)
            issue_pairs = {(item["prediction_id"], item["issue_type"]) for item in issues}

            self.assertIn((high_error_id, "high_error"), issue_pairs)
            self.assertIn((actual_missing_id, "actual_missing"), issue_pairs)
            self.assertIn((actual_missing_id, "elevation_missing"), issue_pairs)
            self.assertIn((pending_id, "pending_compare"), issue_pairs)
            self.assertIn((pending_id, "red_flag_missing_elevation"), issue_pairs)
            self.assertNotIn((manual_id, "baseline_only"), issue_pairs)

            priorities = {item["issue_type"]: item["priority"] for item in issues}
            self.assertEqual(priorities["high_error"], "P1")
            self.assertEqual(priorities["actual_missing"], "P1")
            self.assertEqual(priorities["red_flag_missing_elevation"], "P1")

            targets = {item["issue_type"]: (item["action_target_page"], item["action_target_section"]) for item in issues}
            self.assertEqual(targets["high_error"], ("KML Yonetimi", "Manuel Analiz"))
            self.assertEqual(targets["actual_missing"], ("Veri Cek", "Database Yukle"))
            self.assertEqual(targets["pending_compare"], ("Tahmin Yap", "Canli Tahmin"))

            breakdown = service.get_prediction_issue_breakdown()
            breakdown_map = {item["issue_type"]: item["count"] for item in breakdown}
            self.assertEqual(breakdown_map["high_error"], 1)
            self.assertEqual(breakdown_map["actual_missing"], 1)
            self.assertEqual(breakdown_map["pending_compare"], 1)
            self.assertEqual(breakdown_map["red_flag_missing_elevation"], 1)

            options = service.get_prediction_issue_filter_options()
            self.assertIn("P1", options["priorities"])
            self.assertIn("high_error", options["issue_types"])

            resolution = service.mark_prediction_issue_resolved(
                prediction_id=actual_missing_id,
                issue_types=["actual_missing"],
                resolution_source="results_merge_auto_compare",
                resolution_note="Gercek sonuc merge edildi",
            )
            self.assertTrue(resolution["updated"])
            self.assertEqual(resolution["resolved_issue_types"], ["actual_missing"])

            rows_after_resolution = service.get_prediction_log_rows(limit=10, rally_id="171")
            resolved_row = next(row for row in rows_after_resolution if row["prediction_id"] == actual_missing_id)
            self.assertEqual(resolved_row["resolved_issue_types_list"], ["actual_missing"])
            self.assertEqual(resolved_row["resolution_source"], "results_merge_auto_compare")

            issues_after_resolution = service.get_prediction_issue_worklist(limit=20)
            issue_pairs_after_resolution = {
                (item["prediction_id"], item["issue_type"]) for item in issues_after_resolution
            }
            self.assertNotIn((actual_missing_id, "actual_missing"), issue_pairs_after_resolution)
            self.assertIn((actual_missing_id, "elevation_missing"), issue_pairs_after_resolution)
        finally:
            db_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
