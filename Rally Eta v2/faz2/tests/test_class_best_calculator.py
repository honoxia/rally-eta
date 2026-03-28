"""
Unit tests for ClassBestTimeCalculator
"""
import unittest
import sqlite3
from pathlib import Path
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.class_best_calculator import ClassBestTimeCalculator
from src.data.master_schema import ensure_stage_results_columns
from tests._temp_paths import make_workspace_temp


class TestClassBestTimeCalculator(unittest.TestCase):
    """Test class best time calculator."""

    @classmethod
    def setUpClass(cls):
        """Create test database."""
        cls.temp_dir = make_workspace_temp("class_best_unit_")
        cls.test_db = str(Path(cls.temp_dir) / 'test_rally_results.db')
        conn = sqlite3.connect(cls.test_db)
        cursor = conn.cursor()

        # Create table (stage_number INTEGER - matches production schema)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stage_results (
                result_id INTEGER PRIMARY KEY,
                rally_id TEXT,
                rally_name TEXT,
                stage_number INTEGER,
                driver_name TEXT,
                car_class TEXT,
                normalized_class TEXT,
                time_seconds REAL,
                status TEXT
            )
        """)
        ensure_stage_results_columns(conn)

        # Insert test data (stage_number as INTEGER)
        test_data = [
            # Rally2 - SS1
            ('bodrum_2025', 'Bodrum Rally', 1, 'Pilot A', 'Rally2', 'Rally2', 630.5, 'FINISHED'),
            ('bodrum_2025', 'Bodrum Rally', 1, 'Pilot B', 'R4', 'Rally2', 645.2, 'FINISHED'),
            ('bodrum_2025', 'Bodrum Rally', 1, 'Pilot C', 'S2000', 'Rally2', 638.0, 'FINISHED'),

            # Rally3 - SS1
            ('bodrum_2025', 'Bodrum Rally', 1, 'Pilot D', 'Rally3', 'Rally3', 655.0, 'FINISHED'),
            ('bodrum_2025', 'Bodrum Rally', 1, 'Pilot E', 'Rally3', 'Rally3', 670.5, 'FINISHED'),

            # DNF
            ('bodrum_2025', 'Bodrum Rally', 1, 'Pilot F', 'Rally2', 'Rally2', 0, 'DNF'),
        ]

        for row in test_data:
            cursor.execute("""
                INSERT INTO stage_results
                (rally_id, rally_name, stage_number, driver_name, car_class, normalized_class, time_seconds, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, row)

        conn.commit()
        conn.close()

    @classmethod
    def tearDownClass(cls):
        """Remove test database."""
        import shutil
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def setUp(self):
        self.calc = ClassBestTimeCalculator(self.test_db)

    def test_rally2_class_best(self):
        """Test Rally2 class best time."""
        result = self.calc.get_class_best('bodrum_2025', 'SS1', 'Rally2')

        self.assertIsNotNone(result)
        self.assertEqual(result['class_best_time'], 630.5)  # Pilot A
        self.assertEqual(result['class_best_driver'], 'Pilot A')
        self.assertEqual(result['finisher_count'], 3)  # A, B, C (F is DNF)

    def test_rally3_class_best(self):
        """Test Rally3 class best time."""
        result = self.calc.get_class_best('bodrum_2025', 'SS1', 'Rally3')

        self.assertIsNotNone(result)
        self.assertEqual(result['class_best_time'], 655.0)  # Pilot D
        self.assertEqual(result['finisher_count'], 2)

    def test_no_finishers(self):
        """Test when no finishers in class."""
        result = self.calc.get_class_best('bodrum_2025', 'SS1', 'Rally1')

        self.assertIsNone(result)

    def test_all_class_bests(self):
        """Test getting all class bests."""
        results = self.calc.get_all_class_bests('bodrum_2025', 'SS1')

        self.assertIn('Rally2', results)
        self.assertIn('Rally3', results)
        self.assertEqual(len(results), 2)

        self.assertEqual(results['Rally2']['class_best_time'], 630.5)
        self.assertEqual(results['Rally3']['class_best_time'], 655.0)

    def test_cross_class_comparison_prevention(self):
        """Test that Rally2 and Rally3 are separate."""
        rally2_best = self.calc.get_class_best('bodrum_2025', 'SS1', 'Rally2')
        rally3_best = self.calc.get_class_best('bodrum_2025', 'SS1', 'Rally3')

        # Rally2 best (630.5) should NOT be Rally3's best
        self.assertNotEqual(
            rally2_best['class_best_time'],
            rally3_best['class_best_time']
        )

        # Rally3's best should be 655.0, NOT 630.5
        self.assertEqual(rally3_best['class_best_time'], 655.0)


if __name__ == '__main__':
    unittest.main()
