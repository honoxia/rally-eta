import unittest

from src.prediction.manual_calculator import (
    build_manual_payload_from_rally,
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

    def test_build_manual_payload_from_rally_uses_raw_class_and_previous_stages(self):
        rally_data = {
            "rally_name": "Test Rallisi",
            "stages": [
                {
                    "stage_number": 1,
                    "stage_name": "Orman",
                    "stage_length_km": 10.0,
                    "results": [
                        {"driver_name": "Pilot A", "car_class": "K3", "time_str": "10:10:000"},
                        {"driver_name": "Pilot B", "car_class": "K3", "time_str": "10:00:000"},
                        {"driver_name": "Pilot C", "car_class": "S3", "time_str": "09:30:000"},
                    ],
                },
                {
                    "stage_number": 2,
                    "stage_name": "Göl",
                    "stage_length_km": 12.0,
                    "results": [
                        {"driver_name": "Pilot A", "car_class": "K3", "time_str": "12:24:000"},
                        {"driver_name": "Pilot B", "car_class": "K3", "time_str": "12:00:000"},
                    ],
                },
                {
                    "stage_number": 3,
                    "stage_name": "Tepe",
                    "stage_length_km": 15.0,
                    "results": [
                        {"driver_name": "Pilot A", "car_class": "K3", "time_str": "DNF"},
                        {"driver_name": "Pilot B", "car_class": "K3", "time_str": "15:00:000"},
                        {"driver_name": "Pilot C", "car_class": "S3", "time_str": "14:20:000"},
                    ],
                },
            ],
        }

        payload = build_manual_payload_from_rally(rally_data, "Pilot A", 3)

        self.assertEqual(payload["class_name"], "K3")
        self.assertEqual(len(payload["references"]), 2)
        self.assertEqual(payload["references"][0]["best_time"], "10:00:000")
        self.assertEqual(payload["references"][1]["driver_time"], "12:24:000")
        self.assertEqual(payload["target"]["best_time"], "15:00:000")
        self.assertEqual(payload["target"]["km"], 15.0)

    def test_build_manual_payload_requires_same_class_target_best(self):
        rally_data = {
            "stages": [
                {
                    "stage_number": 1,
                    "stage_length_km": 10.0,
                    "results": [
                        {"driver_name": "Pilot A", "car_class": "K3", "time_str": "10:10:000"},
                    ],
                },
                {
                    "stage_number": 2,
                    "stage_length_km": 12.0,
                    "results": [
                        {"driver_name": "Pilot A", "car_class": "K3", "time_str": "DNF"},
                        {"driver_name": "Pilot C", "car_class": "S3", "time_str": "11:00:000"},
                    ],
                },
            ]
        }

        with self.assertRaisesRegex(ValueError, "K3 sınıfında geçerli best derece"):
            build_manual_payload_from_rally(rally_data, "Pilot A", 2)


    def test_outlier_reference_stage_is_dropped(self):
        """Lastik/ariza yasanan referans etap ortalamayi bozmamali."""
        rows = [
            {"label": "SS1", "km": 10.0, "best_time": "10:00:000", "driver_time": "11:00:000"},
            {"label": "SS2", "km": 10.0, "best_time": "10:00:000", "driver_time": "11:06:000"},
            {"label": "SS3", "km": 10.0, "best_time": "10:00:000", "driver_time": "16:00:000"},
            {"label": "SS4", "km": 10.0, "best_time": "10:00:000", "driver_time": "10:54:000"},
            {"label": "SS5", "km": 10.0, "best_time": "10:00:000", "driver_time": "11:00:000"},
        ]
        result = calculate_manual_stage_estimate(
            reference_rows=rows,
            target_row={"km": 10.0, "best_time": "10:00:000"},
            class_name="K3",
        )

        self.assertEqual(result.used_stage_count, 4)
        self.assertNotIn("SS3", [item.label for item in result.reference_details])
        self.assertEqual(len(result.ignored_references), 1)
        self.assertIn("SS3", result.ignored_references[0])
        self.assertTrue(any("lastik/arıza" in w for w in result.warnings))
        # Elenmeseydi tahmin ~12:00 olurdu; simdi gercek seviyeye yakin.
        self.assertLess(result.km_based_prediction_seconds, 11 * 60 + 10)

    def test_consistent_driver_keeps_every_reference(self):
        """Normal dalgalanma eleme tetiklememeli."""
        rows = [
            {"label": "SS1", "km": 10.0, "best_time": "10:00:000", "driver_time": "11:00:000"},
            {"label": "SS2", "km": 10.0, "best_time": "10:00:000", "driver_time": "11:12:000"},
            {"label": "SS3", "km": 10.0, "best_time": "10:00:000", "driver_time": "10:48:000"},
            {"label": "SS4", "km": 10.0, "best_time": "10:00:000", "driver_time": "11:06:000"},
        ]
        result = calculate_manual_stage_estimate(
            reference_rows=rows,
            target_row={"km": 10.0, "best_time": "10:00:000"},
            class_name="K3",
        )

        self.assertEqual(result.used_stage_count, 4)
        self.assertEqual(result.ignored_references, ())

    def test_outlier_filter_needs_enough_references(self):
        """3 referansta eleme yapilmamali; veri zaten yetersiz."""
        rows = [
            {"label": "SS1", "km": 10.0, "best_time": "10:00:000", "driver_time": "11:00:000"},
            {"label": "SS2", "km": 10.0, "best_time": "10:00:000", "driver_time": "11:06:000"},
            {"label": "SS3", "km": 10.0, "best_time": "10:00:000", "driver_time": "16:00:000"},
        ]
        result = calculate_manual_stage_estimate(
            reference_rows=rows,
            target_row={"km": 10.0, "best_time": "10:00:000"},
            class_name="K3",
        )

        self.assertEqual(result.used_stage_count, 3)
        self.assertEqual(result.ignored_references, ())


if __name__ == "__main__":
    unittest.main()
