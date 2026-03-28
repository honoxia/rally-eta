import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.data.geometry_merge import merge_geometry_rows
from src.data.master_schema import apply_master_schema


def _geometry_row(
    stage_id: str,
    rally_id: str,
    stage_number: int,
    source_kml: str,
    distance_km: float = 12.3,
    total_ascent: float = 240.0,
    total_descent: float = 235.0,
    max_grade: float = 9.5,
    p95_curvature: float = 0.0123,
    hairpin_count: int = 4,
    surface: str = "gravel",
) -> dict:
    return {
        "stage_id": stage_id,
        "rally_id": rally_id,
        "stage_number": stage_number,
        "stage_name": f"SS{stage_number}",
        "surface": surface,
        "distance_km": distance_km,
        "total_ascent": total_ascent,
        "total_descent": total_descent,
        "max_grade": max_grade,
        "p95_curvature": p95_curvature,
        "hairpin_count": hairpin_count,
        "source_kml": source_kml,
        "kml_file": source_kml,
        "analysis_version": "test_analyzer_v1",
        "geometry_json": f'{{"stage":"{stage_id}","source":"{source_kml}"}}',
    }


class GeometryMergeTests(unittest.TestCase):
    def test_merge_geometry_rows_handles_updates_duplicates_and_conflicts(self):
        Path(".tmp_testdata").mkdir(exist_ok=True)
        master_db = Path(".tmp_testdata") / f"geometry_master_{next(tempfile._get_candidate_names())}.db"
        backup_dir = Path(".tmp_testdata") / f"geometry_backups_{next(tempfile._get_candidate_names())}"
        report_dir = Path(".tmp_testdata") / f"geometry_reports_{next(tempfile._get_candidate_names())}"

        try:
            apply_master_schema(str(master_db))

            inserted = merge_geometry_rows(
                master_db_path=str(master_db),
                incoming_rows=[_geometry_row("171_ss1", "171", 1, "seed.kml")],
                source_label="seed_geometry",
                backup_dir=str(backup_dir),
                report_dir=str(report_dir),
            )
            self.assertEqual(inserted.inserted_rows, 1)
            self.assertEqual(inserted.conflict_rows, 0)

            metadata_update = merge_geometry_rows(
                master_db_path=str(master_db),
                incoming_rows=[{"stage_id": "171_ss1", "analysis_version": "manual_review_v2"}],
                source_label="excel_surface_fix",
                backup_dir=str(backup_dir),
                report_dir=str(report_dir),
            )
            self.assertEqual(metadata_update.metadata_updated_rows, 1)
            self.assertEqual(metadata_update.conflict_rows, 0)

            near_duplicate = merge_geometry_rows(
                master_db_path=str(master_db),
                incoming_rows=[
                    _geometry_row(
                        "171_ss1",
                        "171",
                        1,
                        "near_duplicate.kml",
                        distance_km=12.31,
                        total_ascent=244.0,
                        total_descent=239.0,
                        max_grade=9.8,
                        p95_curvature=0.01235,
                        hairpin_count=5,
                    )
                ],
                source_label="near_duplicate_geometry",
                backup_dir=str(backup_dir),
                report_dir=str(report_dir),
            )
            self.assertEqual(near_duplicate.duplicate_rows, 1)
            self.assertEqual(near_duplicate.conflict_rows, 0)

            conflict = merge_geometry_rows(
                master_db_path=str(master_db),
                incoming_rows=[
                    _geometry_row(
                        "171_ss1",
                        "171",
                        1,
                        "different_route.kml",
                        distance_km=18.0,
                        total_ascent=40.0,
                        total_descent=35.0,
                        max_grade=2.0,
                        p95_curvature=0.001,
                        hairpin_count=0,
                    )
                ],
                source_label="conflicting_geometry",
                backup_dir=str(backup_dir),
                report_dir=str(report_dir),
            )
            self.assertEqual(conflict.conflict_rows, 1)
            self.assertEqual(conflict.conflict_stage_ids, ["171_ss1"])

            conn = sqlite3.connect(master_db)
            cur = conn.cursor()
            self.assertEqual(cur.execute("SELECT COUNT(*) FROM stage_geometry").fetchone()[0], 1)
            stage_row = cur.execute(
                "SELECT surface, source_kml, distance_km, analysis_version FROM stage_geometry WHERE stage_id = '171_ss1'"
            ).fetchone()
            conflict_count = cur.execute("SELECT COUNT(*) FROM merge_conflicts").fetchone()[0]
            merge_log_count = cur.execute(
                "SELECT COUNT(*) FROM merge_log WHERE merge_scope = 'geometry_merge'"
            ).fetchone()[0]
            conn.close()

            self.assertEqual(stage_row, ("gravel", "near_duplicate.kml", 12.31, "test_analyzer_v1"))
            self.assertEqual(conflict_count, 1)
            self.assertEqual(merge_log_count, 4)

            for summary in [inserted, metadata_update, near_duplicate, conflict]:
                for backup_path in summary.backups.values():
                    self.assertTrue(Path(backup_path).exists(), backup_path)
                self.assertTrue(Path(summary.merge_log_path).exists(), summary.merge_log_path)
        finally:
            master_db.unlink(missing_ok=True)
            for folder in [backup_dir, report_dir]:
                if folder.exists():
                    for item in folder.glob("*"):
                        item.unlink(missing_ok=True)
                    folder.rmdir()


if __name__ == "__main__":
    unittest.main()
