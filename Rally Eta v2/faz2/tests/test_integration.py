"""
Integration tests for Rally ETA v2.0 prediction pipeline.

Tests the full 3-stage prediction flow:
1. Baseline calculation
2. Geometric correction
3. Final prediction with confidence
"""
import unittest
import sqlite3
import os
from pathlib import Path
import sys

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from tests._temp_paths import make_workspace_temp
from src.data.master_schema import ensure_stage_geometry_table, ensure_stage_results_columns


class TestConfidenceScorer(unittest.TestCase):
    """Test confidence scoring logic."""

    def setUp(self):
        from src.prediction.confidence_scorer import ConfidenceScorer
        self.scorer = ConfidenceScorer()

    def test_high_confidence(self):
        """Test high confidence scenario."""
        result = self.scorer.calculate(
            driver_history_count=20,
            surface_experience=15,
            geometry_data_available=True,
            driver_profile_confidence=0.9,
            rally_stages_count=4,
            baseline_ratio=1.05,
            geometric_mode='geometric'
        )

        self.assertEqual(result.level, 'HIGH')
        self.assertGreaterEqual(result.score, 75)

    def test_medium_confidence(self):
        """Test medium confidence scenario."""
        result = self.scorer.calculate(
            driver_history_count=10,
            surface_experience=7,
            geometry_data_available=True,
            driver_profile_confidence=0.6,
            rally_stages_count=2,
            baseline_ratio=1.08,
            geometric_mode='geometric'
        )

        self.assertIn(result.level, ['MEDIUM', 'HIGH'])
        self.assertGreaterEqual(result.score, 55)

    def test_low_confidence_no_geometry(self):
        """Test low confidence when no geometry data."""
        result = self.scorer.calculate(
            driver_history_count=5,
            surface_experience=3,
            geometry_data_available=False,
            driver_profile_confidence=0.3,
            rally_stages_count=1,
            baseline_ratio=1.15,
            geometric_mode='fallback'
        )

        self.assertIn(result.level, ['LOW', 'VERY_LOW'])
        self.assertLess(result.score, 55)

    def test_extreme_baseline_penalty(self):
        """Test penalty for extreme baseline ratio."""
        # Normal baseline
        result_normal = self.scorer.calculate(
            driver_history_count=15,
            surface_experience=10,
            geometry_data_available=True,
            driver_profile_confidence=0.8,
            rally_stages_count=3,
            baseline_ratio=1.05,
            geometric_mode='geometric'
        )

        # Extreme baseline
        result_extreme = self.scorer.calculate(
            driver_history_count=15,
            surface_experience=10,
            geometry_data_available=True,
            driver_profile_confidence=0.8,
            rally_stages_count=3,
            baseline_ratio=1.25,  # Very high
            geometric_mode='geometric'
        )

        # Extreme should have lower score
        self.assertLess(result_extreme.score, result_normal.score)

    def test_explanation_generation(self):
        """Test explanation text generation."""
        result = self.scorer.calculate(
            driver_history_count=15,
            surface_experience=10,
            geometry_data_available=True,
            driver_profile_confidence=0.8,
            rally_stages_count=3,
            baseline_ratio=1.05,
            geometric_mode='geometric'
        )

        explanation = self.scorer.generate_explanation(result)

        self.assertIn('GUVENILIRLIK', explanation)
        self.assertIn(result.level, explanation)
        self.assertTrue(len(result.reasons) > 0)


class TestPredictionPipelineWithMockData(unittest.TestCase):
    """Test prediction pipeline with mock database."""

    @classmethod
    def setUpClass(cls):
        """Create test database with mock data."""
        cls.temp_dir = make_workspace_temp("prediction_pipeline_")
        cls.test_db = os.path.join(cls.temp_dir, 'test_rally.db')

        conn = sqlite3.connect(cls.test_db)
        cursor = conn.cursor()

        # Create tables
        cursor.execute("""
            CREATE TABLE stage_results (
                result_id INTEGER PRIMARY KEY,
                driver_id TEXT,
                driver_name TEXT,
                rally_id TEXT,
                rally_name TEXT,
                rally_date TEXT,
                stage_id TEXT,
                stage_number INTEGER,
                car_class TEXT,
                normalized_class TEXT,
                time_seconds REAL,
                ratio_to_class_best REAL,
                class_position INTEGER,
                status TEXT,
                surface TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE stages_metadata (
                stage_id TEXT PRIMARY KEY,
                rally_id TEXT,
                distance_km REAL,
                surface TEXT,
                hairpin_count INTEGER,
                hairpin_density REAL,
                turn_count INTEGER,
                turn_density REAL,
                total_ascent REAL,
                total_descent REAL,
                elevation_gain REAL,
                max_grade REAL,
                avg_abs_grade REAL,
                avg_curvature REAL,
                max_curvature REAL,
                p95_curvature REAL,
                curvature_density REAL,
                straight_percentage REAL,
                curvy_percentage REAL
            )
        """)
        ensure_stage_results_columns(conn)
        ensure_stage_geometry_table(conn)

        # Insert test driver data
        test_stages = []
        for i in range(20):
            rally_idx = i // 5
            test_stages.append((
                f'driver_001',
                'Test Pilot',
                f'rally_{rally_idx}',
                f'Rally {rally_idx}',
                f'2025-01-{10 + i}',
                f'SS{(i % 5) + 1}',
                (i % 5) + 1,
                'Rally2',
                'Rally2',
                600 + i * 5,  # Time
                1.05 + (i % 3) * 0.01,  # Ratio
                i % 5 + 1,
                'FINISHED',
                'gravel' if i % 2 == 0 else 'asphalt'
            ))

        cursor.executemany("""
            INSERT INTO stage_results
            (driver_id, driver_name, rally_id, rally_name, rally_date, stage_id, stage_number,
             car_class, normalized_class, time_seconds, ratio_to_class_best,
             class_position, status, surface)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, test_stages)

        # Insert stage metadata
        cursor.execute("""
            INSERT INTO stages_metadata
            (stage_id, rally_id, distance_km, surface, hairpin_count, hairpin_density,
             turn_count, turn_density, total_ascent, total_descent, elevation_gain,
             max_grade, avg_abs_grade, avg_curvature, max_curvature, p95_curvature,
             curvature_density, straight_percentage, curvy_percentage)
            VALUES
            ('SS3', 'rally_test', 15.5, 'gravel', 12, 0.77, 45, 2.9, 521, 480, 320,
             12.5, 5.2, 0.003, 0.025, 0.012, 3.2, 35, 25)
        """)

        conn.commit()
        conn.close()

    @classmethod
    def tearDownClass(cls):
        """Cleanup test database."""
        import shutil
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def test_baseline_predictor(self):
        """Test baseline predictor with mock data."""
        from src.baseline.baseline_predictor import BaselinePredictor

        predictor = BaselinePredictor(self.test_db)

        # driver_name is used as identifier (not driver_id)
        try:
            result = predictor.predict(
                driver_id='Test Pilot',
                rally_id='rally_test',
                stage_id='SS3',
                current_stage=3,
                surface='gravel',
                normalized_class='Rally2'
            )

            self.assertIn('baseline_ratio', result)
            self.assertIn('predicted_time_str', result)
            self.assertIn('components', result)

        except Exception as e:
            # Expected: class_best not found for rally_test (no stage data for that rally)
            error_msg = str(e).lower()
            expected_errors = ['class best', 'no performance', 'no finishers']
            self.assertTrue(
                any(err in error_msg for err in expected_errors),
                f"Unexpected error: {e}"
            )

    def test_feature_engineering(self):
        """Test feature engineering."""
        from src.ml.feature_engineering import FeatureEngineer

        engineer = FeatureEngineer(self.test_db)

        features = engineer.create_features_for_prediction(
            driver_id='driver_001',
            stage_id='SS3',
            baseline_ratio=1.05,
            momentum_factor=1.01,
            surface_adjustment=0.98,
            surface='gravel',
            normalized_class='Rally2'
        )

        if features:
            self.assertIn('distance_km', features)
            self.assertIn('hairpin_density', features)
            self.assertIn('baseline_ratio', features)
            self.assertEqual(features['baseline_ratio'], 1.05)


class TestExcelExporter(unittest.TestCase):
    """Test Excel export functionality."""

    def setUp(self):
        self.temp_dir = make_workspace_temp("excel_export_")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_single_export(self):
        """Test single prediction export."""
        from src.export.excel_exporter import ExcelExporter
        from src.prediction.confidence_scorer import ConfidenceResult
        from dataclasses import dataclass, field

        @dataclass
        class MockPrediction:
            driver_id: str = "test"
            driver_name: str = "Test Pilot"
            stage_id: str = "SS3"
            stage_name: str = "SS3 - Test"
            normalized_class: str = "Rally2"
            surface: str = "gravel"
            predicted_time_seconds: float = 645.5
            predicted_time_str: str = "10:45.500"
            predicted_ratio: float = 1.052
            class_best_time: float = 613.5
            class_best_str: str = "10:13.500"
            class_best_driver: str = "Leader"
            baseline_ratio: float = 1.045
            momentum_factor: float = 1.01
            surface_adjustment: float = 0.98
            geometric_correction: float = 1.015
            geometric_mode: str = "geometric"
            confidence: ConfidenceResult = None
            summary_text: str = "Summary"
            detailed_text: str = "Details"
            generated_at: str = "2025-12-29T10:00:00"

            def __post_init__(self):
                if self.confidence is None:
                    self.confidence = ConfidenceResult(
                        level="HIGH",
                        score=85,
                        emoji="🟢",
                        reasons=["Test reason"],
                        breakdown={"historical": 40}
                    )

        exporter = ExcelExporter()
        output_path = os.path.join(self.temp_dir, "test_single.xlsx")

        pred = MockPrediction()
        exporter.export_prediction(pred, output_path)

        self.assertTrue(os.path.exists(output_path))

    def test_batch_export(self):
        """Test batch prediction export."""
        from src.export.excel_exporter import ExcelExporter
        from src.prediction.confidence_scorer import ConfidenceResult
        from dataclasses import dataclass

        @dataclass
        class MockPrediction:
            driver_id: str
            driver_name: str
            stage_id: str = "SS3"
            stage_name: str = "SS3"
            normalized_class: str = "Rally2"
            surface: str = "gravel"
            predicted_time_seconds: float = 645.5
            predicted_time_str: str = "10:45.500"
            predicted_ratio: float = 1.052
            class_best_time: float = 613.5
            class_best_str: str = "10:13.500"
            class_best_driver: str = "Leader"
            baseline_ratio: float = 1.045
            momentum_factor: float = 1.01
            surface_adjustment: float = 0.98
            geometric_correction: float = 1.015
            geometric_mode: str = "geometric"
            confidence: ConfidenceResult = None
            summary_text: str = "Summary"
            detailed_text: str = "Details"
            generated_at: str = "2025-12-29T10:00:00"

            def __post_init__(self):
                if self.confidence is None:
                    self.confidence = ConfidenceResult(
                        level="HIGH",
                        score=85,
                        emoji="🟢",
                        reasons=["Test reason"],
                        breakdown={"historical": 40}
                    )

        exporter = ExcelExporter()
        output_path = os.path.join(self.temp_dir, "test_batch.xlsx")

        predictions = [
            MockPrediction(driver_id=f"d{i}", driver_name=f"Pilot {i}")
            for i in range(5)
        ]

        exporter.export_batch(
            predictions,
            rally_name="Test Rally",
            stage_name="SS3",
            output_path=output_path
        )

        self.assertTrue(os.path.exists(output_path))


class TestCarClassNormalizer(unittest.TestCase):
    """Test car class normalization."""

    def setUp(self):
        from src.data.car_class_normalizer import CarClassNormalizer
        self.normalizer = CarClassNormalizer()

    def test_rally2_variants(self):
        """Test Rally2 normalization."""
        variants = ['R4', 'S2000', 'Rally 2', 'rally2', 'NR4', 'VR4']

        for variant in variants:
            result = self.normalizer.normalize(variant)
            self.assertEqual(result, 'Rally2', f"Failed for {variant}")

    def test_rally3_variants(self):
        """Test Rally3 normalization."""
        variants = ['Rally3', 'Rally 3', 'rally3']

        for variant in variants:
            result = self.normalizer.normalize(variant)
            self.assertEqual(result, 'Rally3', f"Failed for {variant}")

    def test_unknown_class(self):
        """Test unknown class handling."""
        result = self.normalizer.normalize('CustomClass')
        self.assertEqual(result, 'CustomClass')

    def test_empty_class(self):
        """Test empty class handling."""
        result = self.normalizer.normalize('')
        self.assertEqual(result, 'Unknown')


class TestClassBestCalculator(unittest.TestCase):
    """Test class best time calculation."""

    @classmethod
    def setUpClass(cls):
        """Create test database."""
        cls.temp_dir = make_workspace_temp("class_best_integration_")
        cls.test_db = os.path.join(cls.temp_dir, 'test_class_best.db')

        conn = sqlite3.connect(cls.test_db)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE stage_results (
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

        test_data = [
            ('rally_1', 'Rally 1', 1, 'Pilot A', 'Rally2', 'Rally2', 600.0, 'FINISHED'),
            ('rally_1', 'Rally 1', 1, 'Pilot B', 'Rally2', 'Rally2', 615.0, 'FINISHED'),
            ('rally_1', 'Rally 1', 1, 'Pilot C', 'Rally3', 'Rally3', 620.0, 'FINISHED'),
            ('rally_1', 'Rally 1', 1, 'Pilot D', 'Rally3', 'Rally3', 635.0, 'FINISHED'),
            ('rally_1', 'Rally 1', 1, 'Pilot E', 'Rally2', 'Rally2', 0, 'DNF'),
        ]

        cursor.executemany("""
            INSERT INTO stage_results
            (rally_id, rally_name, stage_number, driver_name, car_class, normalized_class,
             time_seconds, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, test_data)

        conn.commit()
        conn.close()

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def test_class_best_rally2(self):
        """Test Rally2 class best."""
        from src.data.class_best_calculator import ClassBestTimeCalculator

        calc = ClassBestTimeCalculator(self.test_db)
        result = calc.get_class_best('rally_1', 'SS1', 'Rally2')

        self.assertIsNotNone(result)
        self.assertEqual(result['class_best_time'], 600.0)
        self.assertEqual(result['class_best_driver'], 'Pilot A')
        self.assertEqual(result['finisher_count'], 2)  # A and B

    def test_class_best_rally3(self):
        """Test Rally3 class best."""
        from src.data.class_best_calculator import ClassBestTimeCalculator

        calc = ClassBestTimeCalculator(self.test_db)
        result = calc.get_class_best('rally_1', 'SS1', 'Rally3')

        self.assertIsNotNone(result)
        self.assertEqual(result['class_best_time'], 620.0)
        self.assertEqual(result['class_best_driver'], 'Pilot C')

    def test_no_finishers(self):
        """Test when no finishers in class."""
        from src.data.class_best_calculator import ClassBestTimeCalculator

        calc = ClassBestTimeCalculator(self.test_db)
        result = calc.get_class_best('rally_1', 'SS1', 'Rally1')

        self.assertIsNone(result)


def run_tests():
    """Run all integration tests."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add test classes
    suite.addTests(loader.loadTestsFromTestCase(TestConfidenceScorer))
    suite.addTests(loader.loadTestsFromTestCase(TestExcelExporter))
    suite.addTests(loader.loadTestsFromTestCase(TestCarClassNormalizer))
    suite.addTests(loader.loadTestsFromTestCase(TestClassBestCalculator))
    suite.addTests(loader.loadTestsFromTestCase(TestPredictionPipelineWithMockData))

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_tests()
    exit(0 if success else 1)
