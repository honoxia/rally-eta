import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.data.master_schema import apply_master_schema
from src.prediction.operation_decision import save_operation_decision


class OperationDecisionTests(unittest.TestCase):
    def test_save_operation_decision_persists_auditable_choice(self):
        Path(".tmp_testdata").mkdir(exist_ok=True)
        db_path = Path(".tmp_testdata") / f"operation_{next(tempfile._get_candidate_names())}.db"
        try:
            apply_master_schema(str(db_path))
            decision_id = save_operation_decision(
                str(db_path),
                {
                    "rally_id": "171",
                    "rally_name": "Test Rallisi",
                    "stage_id": "171_ss3",
                    "stage_number": 3,
                    "stage_name": "Tepe",
                    "driver_name": "Pilot A",
                    "raw_class": "K3",
                    "selected_method": "Yüzde Bazlı",
                    "selected_time_seconds": 915.5,
                    "selected_time_str": "15:15:500",
                    "km_based_seconds": 914.0,
                    "percentage_seconds": 915.5,
                    "ml_seconds": 917.0,
                    "reference_stage_count": 2,
                    "rationale": "Aynı sınıftaki iki referans etapla uyumlu.",
                    "source_url": "https://sonuc.tosfed.org.tr/yaris/171/",
                },
            )

            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    """SELECT selected_method, selected_time_str, raw_class, reference_stage_count
                    FROM operation_decisions WHERE decision_id = ?""",
                    [decision_id],
                ).fetchone()
            conn.close()
            self.assertEqual(row, ("Yüzde Bazlı", "15:15:500", "K3", 2))
        finally:
            db_path.unlink(missing_ok=True)

    def test_save_operation_decision_requires_rationale(self):
        with self.assertRaisesRegex(ValueError, "gerekçesi"):
            save_operation_decision(
                ":memory:",
                {
                    "rally_id": "171",
                    "stage_id": "171_ss3",
                    "driver_name": "Pilot A",
                    "selected_method": "Km Bazlı",
                    "selected_time_seconds": 900,
                    "selected_time_str": "15:00:000",
                    "rationale": "",
                },
            )


if __name__ == "__main__":
    unittest.main()
