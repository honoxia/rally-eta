import unittest

from src.prediction.manual_calculator import (
    calculate_manual_stage_estimate,
    format_manual_time,
    parse_manual_time_input,
)


class ManualCalculatorTests(unittest.TestCase):
    def test_parse_manual_time_input_supports_requested_formats(self):
        self.assertAlmostEqual(parse_manual_time_input("01:10:800"), 70.8)
        self.assertAlmostEqual(parse_manual_time_input("01:30:3"), 90.3)
        self.assertAlmostEqual(parse_manual_time_input("10:37:900"), 637.9)
        self.assertAlmostEqual(parse_manual_time_input("04:18:300"), 258.3)

    def test_format_manual_time_uses_mm_ss_ms(self):
        self.assertEqual(format_manual_time(70.8), "01:10:800")
        self.assertEqual(format_manual_time(908.25), "15:08:250")

    def test_manual_stage_estimate_uses_valid_rows_and_keeps_raw_class(self):
        result = calculate_manual_stage_estimate(
            class_name="K3",
            reference_rows=[
                {
                    "label": "Etap 1",
                    "km": 10.0,
                    "best_time": "10:00:000",
                    "driver_time": "10:05:000",
                },
                {
                    "label": "Etap 2",
                    "km": 20.0,
                    "best_time": "16:40:000",
                    "driver_time": "17:00:000",
                },
                {
                    "label": "Etap 3",
                    "km": 0.0,
                    "best_time": "09:00:000",
                    "driver_time": "09:10:000",
                },
                {
                    "label": "Etap 4",
                    "km": 8.0,
                    "best_time": "",
                    "driver_time": "",
                },
            ],
            target_row={
                "km": 15.0,
                "best_time": "13:20:000",
            },
        )

        self.assertEqual(result.class_name, "K3")
        self.assertEqual(result.used_stage_count, 2)
        self.assertEqual(result.ignored_stage_count, 2)
        self.assertAlmostEqual(result.average_diff_per_km, 0.75)
        self.assertAlmostEqual(result.average_ratio, (605.0 / 600.0 + 1020.0 / 1000.0) / 2)
        self.assertAlmostEqual(result.km_based_prediction_seconds, 811.25)
        self.assertAlmostEqual(result.percentage_prediction_seconds, 811.3333333333334)
        self.assertAlmostEqual(result.methods_gap_seconds, 0.08333333333337123)
        self.assertEqual(len(result.ignored_references), 2)
        self.assertTrue(all("birlikte girilmediği için kullanılmadı" in item for item in result.ignored_references))

    def test_manual_stage_estimate_warns_for_single_row(self):
        result = calculate_manual_stage_estimate(
            class_name="Rally3",
            reference_rows=[
                {
                    "label": "Etap 1",
                    "km": 12.0,
                    "best_time": "12:00:000",
                    "driver_time": "12:12:000",
                }
            ],
            target_row={
                "km": 14.0,
                "best_time": "13:30:000",
            },
        )

        self.assertEqual(result.used_stage_count, 1)
        self.assertTrue(any("düşük güven" in warning for warning in result.warnings))


if __name__ == "__main__":
    unittest.main()
