"""Regression coverage for refresh, automatic calculation and decision labels."""

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from streamlit.testing.v1 import AppTest

from src.data.master_schema import apply_master_schema
from src.prediction.prediction_service import PredictionService


URL = "https://sonuc.tosfed.org.tr/yaris/171/"


def rally_fixture(reference_count=2, best_time="10:00:000"):
    return {
        "rally_id": 171,
        "rally_name": "Test Rallisi",
        "suggested_stage": reference_count + 1,
        "stages": [
            {
                "stage_number": number,
                "stage_name": f"Etap {number}",
                "stage_length_km": 10.0,
                "results": [
                    {"driver_name": "Pilot A", "car_class": "K3", "time_str": "10:10:000"},
                    {"driver_name": "Pilot B", "car_class": "K3", "time_str": best_time},
                ],
            }
            for number in range(1, reference_count + 2)
        ],
    }


class RaceDayUITests(unittest.TestCase):
    def setUp(self):
        original_path = sys.path[:]
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "segment"))
        self.addCleanup(lambda: sys.path.__setitem__(slice(None), original_path))

    def assert_healthy(self, app):
        self.assertFalse(app.exception, [error.message for error in app.exception])

    def test_explicit_refresh_reads_source_on_both_screens(self):
        for module, render, key, data_key in (
            ("operations", "render", "operation_fetch", "operation_rally_data"),
            ("prediction", "_render_single_prediction", "manual_auto_fetch", "manual_auto_rally_data"),
        ):
            with self.subTest(screen=module):
                app = AppTest.from_string(f"from pages.{module} import {render}\n{render}()")
                app.session_state["live_rally_url"] = URL
                app.session_state["live_rally_data"] = rally_fixture()
                app.session_state["operation_url" if module == "operations" else "manual_auto_url"] = URL
                app.run()
                for best_time in ("09:50:000", "09:40:000"):
                    fresh_data = rally_fixture(best_time=best_time)
                    with patch(
                        "src.scraper.tosfed_sonuc_scraper.TOSFEDSonucScraper.fetch_rally_from_url",
                        return_value=fresh_data,
                    ) as fetch:
                        app.button(key=key).click().run()
                    self.assert_healthy(app)
                    fetch.assert_called_once_with(URL)
                    self.assertEqual(app.session_state[data_key], fresh_data)

    def test_failed_refresh_is_not_reported_as_success_from_cached_data(self):
        for module, render, key in (
            ("operations", "render", "operation_fetch"),
            ("prediction", "_render_single_prediction", "manual_auto_fetch"),
        ):
            with self.subTest(screen=module):
                app = AppTest.from_string(f"from pages.{module} import {render}\n{render}()")
                app.session_state["live_rally_url"] = URL
                app.session_state["live_rally_data"] = rally_fixture()
                app.session_state["operation_url" if module == "operations" else "manual_auto_url"] = URL
                app.run()
                with patch(
                    "src.scraper.tosfed_sonuc_scraper.TOSFEDSonucScraper.fetch_rally_from_url",
                    return_value=None,
                ):
                    app.button(key=key).click().run()
                self.assert_healthy(app)
                self.assertTrue(app.error)
                self.assertFalse(app.success)

    def test_auto_calculation_shows_result_with_one_two_or_six_references(self):
        for reference_count in (1, 2, 6):
            with self.subTest(references=reference_count):
                app = AppTest.from_string(
                    "from pages.prediction import _render_single_prediction\n_render_single_prediction()"
                )
                app.session_state["manual_auto_rally_data"] = rally_fixture(reference_count)
                app.run()
                app.button(key="manual_auto_calculate").click().run()
                self.assert_healthy(app)
                self.assertEqual(app.session_state["manual_calc_result"].used_stage_count, reference_count)
                self.assertFalse(any("Girdiler değişti" in item.value for item in app.info))
                self.assertTrue(any("Km Bazlı" in item.value for item in app.markdown))
                app.run()
                self.assertTrue(any("Km Bazlı" in item.value for item in app.markdown))

    def test_editing_an_empty_reference_after_auto_calculation_invalidates_result(self):
        app = AppTest.from_string(
            "from pages.prediction import _render_single_prediction\n_render_single_prediction()"
        )
        app.session_state["manual_auto_rally_data"] = rally_fixture()
        app.run()
        app.button(key="manual_auto_calculate").click().run()
        app.number_input(key="manual_ref_3_km").set_value(10.0).run()
        self.assert_healthy(app)
        self.assertTrue(any("Girdiler değişti" in item.value for item in app.info))
        self.assertFalse(any("Km Bazlı" in item.value for item in app.markdown))

    def test_baseline_and_ml_decisions_use_the_actual_method(self):
        for mode, label in (("baseline_only", "Baz Tahmin"), ("geometric", "ML Tahmini")):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                db_path = str(Path(tmp) / "decisions.db")
                apply_master_schema(db_path)
                # Exercise the real fallback. The geometric result models the service contract.
                service = PredictionService(db_path)
                if mode == "geometric":
                    service = Mock()
                    service.compare_previous_and_predict_next.return_value = {
                        "geometric_mode": mode,
                        "predicted_time_seconds": 615.0,
                        "predicted_time_str": "10:15:000",
                        "confidence_level": "MEDIUM",
                    }
                app = AppTest.from_string("from pages.operations import render\nrender()")
                app.session_state["db_path"] = db_path
                app.session_state["operation_rally_data"] = rally_fixture()
                app.session_state["operation_loaded_url"] = URL
                app.session_state["operation_url"] = URL
                app.run()
                with patch("pages.operations.get_prediction_service", return_value=service):
                    app.button(key="operation_calculate").click().run()
                self.assert_healthy(app)
                self.assertIn(label, app.radio(key="operation_selected_method").options)
                if mode == "baseline_only":
                    self.assertNotIn("ML Tahmini", app.radio(key="operation_selected_method").options)
                    self.assertTrue(any("ML modeli kullanılmadı" in item.value for item in app.warning))
                app.radio(key="operation_selected_method").set_value(label).run()
                app.text_area(key="operation_rationale").set_value("Referanslarla uyumlu karar.").run()
                app.button(key="operation_save").click().run()
                self.assert_healthy(app)
                with sqlite3.connect(db_path) as conn:
                    row = conn.execute(
                        "SELECT selected_method, selected_time_seconds, ml_seconds FROM operation_decisions"
                    ).fetchone()
                self.assertEqual(row[0], label)
                self.assertGreater(row[1], 0)
                if mode == "baseline_only":
                    self.assertIsNone(row[2])
                else:
                    self.assertEqual(row[2], row[1])


if __name__ == "__main__":
    unittest.main()
