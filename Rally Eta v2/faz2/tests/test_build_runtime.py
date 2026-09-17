import ast
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from src.ml.model_trainer import _load_training_dependencies


class BuildRuntimeTests(unittest.TestCase):
    def test_model_trainer_enables_experimental_hist_gradient_import(self):
        class FakeHistGradientBoostingRegressor:
            pass

        enabled = {"value": False}
        train_test_split = object()
        mean_absolute_error = object()
        mean_squared_error = object()
        r2_score = object()
        permutation_importance = object()

        def fake_import_module(name: str):
            if name == "sklearn.model_selection":
                return types.SimpleNamespace(train_test_split=train_test_split)
            if name == "sklearn.metrics":
                return types.SimpleNamespace(
                    mean_absolute_error=mean_absolute_error,
                    mean_squared_error=mean_squared_error,
                    r2_score=r2_score,
                )
            if name == "sklearn.inspection":
                return types.SimpleNamespace(permutation_importance=permutation_importance)
            if name == "sklearn.ensemble":
                if enabled["value"]:
                    return types.SimpleNamespace(
                        HistGradientBoostingRegressor=FakeHistGradientBoostingRegressor
                    )
                return types.SimpleNamespace()
            if name == "sklearn.experimental.enable_hist_gradient_boosting":
                enabled["value"] = True
                return types.SimpleNamespace()
            raise ImportError(name)

        with patch("src.ml.model_trainer.import_module", side_effect=fake_import_module):
            dependencies = _load_training_dependencies()

        self.assertIs(
            dependencies["HistGradientBoostingRegressor"],
            FakeHistGradientBoostingRegressor,
        )
        self.assertIs(dependencies["train_test_split"], train_test_split)
        self.assertIs(dependencies["r2_score"], r2_score)

    def test_build_spec_bundles_segment_router_and_hist_gradient_modules(self):
        spec_source = Path("RallyETA_v2.spec").read_text(encoding="utf-8")

        self.assertIn("D:\\\\claude\\\\Rally Eta v2\\\\faz2\\\\app.py", spec_source)
        self.assertIn("D:\\\\claude\\\\Rally Eta v2\\\\faz2\\\\segment', 'segment", spec_source)
        self.assertIn("sklearn.experimental.enable_hist_gradient_boosting", spec_source)
        self.assertIn("sklearn.ensemble._hist_gradient_boosting.gradient_boosting", spec_source)
        self.assertIn("collect_submodules('sklearn.ensemble._hist_gradient_boosting')", spec_source)

    def test_launcher_prefers_segment_router(self):
        launcher_source = Path("launcher.py").read_text(encoding="utf-8")

        self.assertIn('app_path = get_resource_path("segment/app.py")', launcher_source)
        self.assertIn('app_path = get_resource_path("app.py")', launcher_source)
        self.assertIn('sys.path.insert(0, str(base_path / "segment"))', launcher_source)

    def test_root_entrypoints_reexecute_router_on_every_rerun(self):
        """Giris noktalari router'i import etmemeli, her rerun'da calistirmali.

        Streamlit bu dosyalari her etkilesimde yeniden calistiriyor ama
        segment.app sys.modules'ta kaldigi icin ikinci import no-op oluyor ve
        sayfa bombos geliyordu. runpy her seferinde dosyayi bastan calistirir.
        """
        for entry in ("app.py", "streamlit_app.py"):
            with self.subTest(entry=entry):
                source = Path(entry).read_text(encoding="utf-8")

                self.assertIn("import runpy", source)
                self.assertIn('runpy.run_path(str(ROUTER_PATH), run_name="__main__")', source)
                self.assertIn('ROUTER_PATH = SEGMENT_ROOT / "app.py"', source)

                # Statik import geri gelirse sayfa yine ilk tiklamada bosalir.
                # Docstring'lere degil, gercek import ifadelerine bakiyoruz.
                imported = set()
                for node in ast.walk(ast.parse(source)):
                    if isinstance(node, ast.Import):
                        imported.update(alias.name for alias in node.names)
                    elif isinstance(node, ast.ImportFrom):
                        imported.add(node.module or "")
                self.assertNotIn("segment.app", imported)

    def test_segment_prediction_page_uses_prediction_service(self):
        prediction_source = Path("segment/pages/prediction.py").read_text(encoding="utf-8")
        app_source = Path("segment/app.py").read_text(encoding="utf-8")
        data_loader_source = Path("segment/shared/data_loaders.py").read_text(encoding="utf-8")
        services_source = Path("segment/shared/services.py").read_text(encoding="utf-8")

        self.assertIn("predict_manual_stage", prediction_source)
        self.assertIn("predict_kml_stage", prediction_source)
        self.assertIn("compare_previous_and_predict_next", prediction_source)
        self.assertIn("get_prediction_service", prediction_source)
        self.assertIn("PredictionService", services_source)
        self.assertIn("@st.cache_resource", services_source)
        self.assertIn("initialize_runtime_schema(active_db_path", app_source)
        self.assertIn("FROM drivers d", data_loader_source)


if __name__ == "__main__":
    unittest.main()
