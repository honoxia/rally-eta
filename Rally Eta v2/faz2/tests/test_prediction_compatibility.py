"""
Compatibility tests for lightweight prediction imports and schema fallbacks.
"""
import importlib.util
import sqlite3
import sys
import types
import unittest
from pathlib import Path


class TestPredictionCompatibility(unittest.TestCase):
    """Regression tests for recent compatibility fixes."""

    def test_confidence_scorer_import_is_lazy(self):
        """Confidence scorer should import without predictor dependencies."""
        from src.prediction.confidence_scorer import ConfidenceScorer

        scorer = ConfidenceScorer()
        self.assertIsNotNone(scorer)

    def test_notional_predictor_import_tolerates_missing_ml_deps(self):
        """Full predictor import should not fail when optional ML deps are absent."""
        from src.prediction.notional_time_predictor import NotionalTimePredictor

        self.assertIsNotNone(NotionalTimePredictor)

    def test_kml_matcher_supports_stage_number_schema(self):
        """KML matcher should work with the app's current stage_results schema."""
        from src.data.kml_stage_matcher import KMLStageMatcher

        db_path = Path('tests/test_kml_matcher_compat.db')
        db_path.unlink(missing_ok=True)

        conn = sqlite3.connect(db_path)
        conn.execute("""
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
                surface TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            INSERT INTO stage_results (
                result_id, rally_id, rally_name, stage_number, stage_name, stage_length_km,
                car_number, driver_name, co_driver_name, car_class, vehicle,
                time_str, time_seconds, diff_str, diff_seconds, surface
            ) VALUES (
                '171_ss1_1', '171', 'Test Rally', 1, 'SS1', 10.0,
                '1', 'Pilot', '', 'Rally2', 'Car',
                '1:00.0', 60.0, '', 0.0, 'gravel'
            )
        """)
        conn.commit()
        conn.close()

        try:
            matcher = KMLStageMatcher(str(db_path))
            rallies = matcher.get_all_rallies()
            stages = matcher.get_rally_stages('171')

            self.assertEqual(len(rallies), 1)
            self.assertEqual(rallies[0]['rally_id'], '171')
            self.assertEqual(rallies[0]['stage_count'], 1)

            self.assertEqual(len(stages), 1)
            self.assertEqual(stages[0]['stage_id'], '171_ss1')
            self.assertEqual(stages[0]['stage_number'], 1)
        finally:
            db_path.unlink(missing_ok=True)

    def test_notional_predictor_handles_baseline_fallback_and_stage_id_resolution(self):
        """Predictor should survive baseline fallback and resolve synthetic stage ids."""
        original_modules = {}
        stubbed_modules = [
            'src.baseline.baseline_predictor',
            'src.data.class_best_calculator',
            'src.data.stage_metadata_manager',
            'src.ml.feature_engineering',
            'src.ml.geometric_correction_model',
            'src.ml.explanation_generator',
            'tmp_notional_predictor_test',
        ]

        for name in stubbed_modules:
            original_modules[name] = sys.modules.get(name)

        try:
            base_mod = types.ModuleType('src.baseline.baseline_predictor')

            class BaselinePredictor:
                def __init__(self, db_path):
                    self.db_path = db_path

                def predict(self, **kwargs):
                    raise ValueError('forced baseline failure')

            base_mod.BaselinePredictor = BaselinePredictor
            sys.modules['src.baseline.baseline_predictor'] = base_mod

            calc_mod = types.ModuleType('src.data.class_best_calculator')

            class ClassBestTimeCalculator:
                def __init__(self, db_path):
                    self.db_path = db_path

                def get_class_best(self, **kwargs):
                    return {'class_best_time': 100.0, 'class_best_driver': 'Leader'}

            calc_mod.ClassBestTimeCalculator = ClassBestTimeCalculator
            sys.modules['src.data.class_best_calculator'] = calc_mod

            metadata_mod = types.ModuleType('src.data.stage_metadata_manager')

            class StageMetadataManager:
                def __init__(self, db_path):
                    self.db_path = db_path

                def get_stage(self, stage_id):
                    if stage_id == '166_ss1':
                        return {'stage_id': '166_ss1', 'surface': 'gravel', 'hairpin_density': 0.4}
                    return None

            metadata_mod.StageMetadataManager = StageMetadataManager
            sys.modules['src.data.stage_metadata_manager'] = metadata_mod

            feature_mod = types.ModuleType('src.ml.feature_engineering')

            class FeatureEngineer:
                def __init__(self, db_path):
                    self.db_path = db_path
                    self.last_stage_id = None

                def create_features_for_prediction(self, **kwargs):
                    self.last_stage_id = kwargs['stage_id']
                    return {
                        'hairpin_density': 0.4,
                        'surface': 'gravel',
                        'normalized_class': 'Rally2',
                    }

                def _get_driver_profile(self, driver_id):
                    return None

            feature_mod.FeatureEngineer = FeatureEngineer
            sys.modules['src.ml.feature_engineering'] = feature_mod

            geometry_mod = types.ModuleType('src.ml.geometric_correction_model')

            class GeometricCorrectionModel:
                def __init__(self):
                    self.model = object()

                def load(self, path):
                    return None

            class ModelWithFallback:
                def __init__(self, model=None):
                    self.model = model

                def predict(self, features, require_geometry=False):
                    return 1.02, 'geometric'

            geometry_mod.GeometricCorrectionModel = GeometricCorrectionModel
            geometry_mod.ModelWithFallback = ModelWithFallback
            sys.modules['src.ml.geometric_correction_model'] = geometry_mod

            explanation_mod = types.ModuleType('src.ml.explanation_generator')

            class ExplanationGenerator:
                def __init__(self, db_path, model_path):
                    self.db_path = db_path
                    self.model_path = model_path

            explanation_mod.ExplanationGenerator = ExplanationGenerator
            sys.modules['src.ml.explanation_generator'] = explanation_mod

            module_path = Path('src/prediction/notional_time_predictor.py')
            spec = importlib.util.spec_from_file_location('tmp_notional_predictor_test', module_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)

            predictor = module.NotionalTimePredictor(db_path='dummy.db', model_path=None)
            result = predictor.predict(
                driver_id='Driver One',
                driver_name='Driver One',
                rally_id='166',
                stage_id='SS1',
                stage_name='SS1',
                current_stage_number=1,
                normalized_class='Rally2',
                surface=None,
            )

            self.assertEqual(predictor.feature_engineer.last_stage_id, '166_ss1')
            self.assertEqual(result.geometric_mode, 'geometric')
            self.assertAlmostEqual(result.predicted_ratio, 1.05 * 1.02, places=6)
        finally:
            for name, original in original_modules.items():
                if original is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = original


if __name__ == '__main__':
    unittest.main()
