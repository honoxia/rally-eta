from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.baseline.driver_performance import DriverPerformanceAnalyzer
from src.baseline.rally_momentum import RallyMomentumAnalyzer
from src.data.master_schema import apply_master_schema, build_driver_id, build_stage_id, normalize_name_key, slugify
from src.prediction.notional_time_predictor import NotionalTimePredictor

logger = logging.getLogger(__name__)

ACCEPTED_ERROR_PCT = 15.0


def _clip(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


class PredictionService:
    """Single entry point for prediction, logging, and live compare flows."""

    def __init__(self, db_path: str, model_path: Optional[str] = None):
        self.db_path = db_path
        self.model_path = str(model_path) if model_path and Path(model_path).exists() else None
        apply_master_schema(db_path)

        self.predictor = NotionalTimePredictor(db_path=db_path, model_path=self.model_path)
        self.manual_predictor = NotionalTimePredictor(db_path=db_path, model_path=None)

        try:
            from src.data.car_class_normalizer import CarClassNormalizer

            self.class_normalizer = CarClassNormalizer()
        except Exception:
            self.class_normalizer = None

    def predict_manual_stage(
        self,
        driver_id: str,
        driver_name: str,
        stage_length_km: float,
        surface: str,
        stage_number: int,
        rally_name: str = "Manual Prediction",
        rally_id: str = "manual_prediction",
        stage_id: Optional[str] = None,
        day_or_night: str = "day",
        run_id: Optional[str] = None,
        log_prediction: bool = True,
    ) -> Dict[str, Any]:
        driver = self.resolve_driver(driver_id=driver_id, driver_name=driver_name)
        resolved_stage_id = stage_id or build_stage_id(rally_id, stage_number) or f"{rally_id}_ss{stage_number}"

        result = self.manual_predictor.predict_for_manual_input(
            driver_id=driver["driver_id"],
            driver_name=driver["driver_name"],
            stage_length_km=stage_length_km,
            surface=surface,
            day_or_night=day_or_night,
            stage_number=stage_number,
            rally_name=rally_name,
        )

        prediction = dict(result)
        prediction.update(
            {
                "driver_id": driver["driver_id"],
                "driver_name": driver["driver_name"],
                "rally_id": rally_id,
                "stage_id": resolved_stage_id,
                "stage_name": f"SS{stage_number}",
                "used_geometry": 0,
                "data_quality_flags": ["manual_input", "baseline_only"],
                "model_version": "prediction_service_manual_v1",
            }
        )

        if log_prediction:
            run_id = run_id or self._generate_run_id("manual")
            prediction["run_id"] = run_id
            prediction["prediction_id"] = self.log_prediction(
                run_id=run_id,
                rally_id=rally_id,
                stage_id=resolved_stage_id,
                driver_id=driver["driver_id"],
                predicted_time=prediction["predicted_time_seconds"],
                confidence=prediction.get("confidence_score"),
                used_geometry=False,
                data_quality_flags=prediction["data_quality_flags"],
                model_version=prediction["model_version"],
                comparison_status="not_applicable",
            )

        return prediction

    def compare_previous_and_predict_next(
        self,
        rally_data: Dict[str, Any],
        driver_name: str,
        driver_class: str,
        predict_stage_num: int,
        surface: Optional[str] = None,
        geo_features: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        run_id = self._generate_run_id("race_day")
        rally_id = str(rally_data["rally_id"])
        previous_stage = next(
            (
                stage
                for stage in sorted(
                    rally_data.get("stages", []),
                    key=lambda item: int(item.get("stage_number", 0) or 0),
                    reverse=True,
                )
                if int(stage.get("stage_number", 0) or 0) < int(predict_stage_num) and stage.get("results")
            ),
            None,
        )

        comparison_summary = None
        if previous_stage:
            comparison_summary = self.compare_predictions_with_live_stage(
                rally_id=rally_id,
                stage_number=int(previous_stage.get("stage_number", 0) or 0),
                stage_results=previous_stage.get("results", []),
                driver_name=driver_name,
            )

        prediction = self.predict_live_stage(
            rally_data=rally_data,
            driver_name=driver_name,
            driver_class=driver_class,
            predict_stage_num=predict_stage_num,
            surface=surface,
            geo_features=geo_features,
            run_id=run_id,
            log_prediction=True,
        )
        prediction["comparison_summary"] = comparison_summary
        return prediction

    def compare_predictions_with_live_stage(
        self,
        rally_id: str,
        stage_number: int,
        stage_results: List[Dict[str, Any]],
        driver_id: Optional[str] = None,
        driver_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        stage_id = build_stage_id(rally_id, stage_number) or f"{rally_id}_ss{stage_number}"
        target_driver_id = None
        if driver_id or driver_name:
            target_driver_id = self.resolve_driver(driver_id=driver_id, driver_name=driver_name)["driver_id"]

        actual_times: Dict[str, float] = {}
        for result in stage_results:
            raw_name = (result.get("driver_name") or "").strip()
            actual_time = float(result.get("time_seconds") or 0) or self._parse_time_str(result.get("time_str", ""))
            if not raw_name or actual_time <= 0:
                continue
            resolved = self.resolve_driver(driver_name=raw_name, car_class=result.get("car_class"))
            actual_times[resolved["driver_id"]] = actual_time

        conn = self._connect()
        try:
            query = """
                SELECT prediction_id, driver_id, predicted_time
                FROM prediction_log
                WHERE rally_id = ? AND stage_id = ? AND comparison_status = 'pending'
            """
            params: List[Any] = [str(rally_id), stage_id]
            if target_driver_id:
                query += " AND driver_id = ?"
                params.append(target_driver_id)

            rows = conn.execute(query, params).fetchall()
            compared_count = 0
            matched_count = 0
            missing_actual_count = 0
            error_values: List[float] = []
            compared_prediction_ids: List[int] = []
            compared_at = datetime.now().isoformat()

            for row in rows:
                prediction_id = int(row["prediction_id"])
                predicted_time = float(row["predicted_time"] or 0)
                actual_time = actual_times.get(row["driver_id"])

                if actual_time is None:
                    conn.execute(
                        """
                        UPDATE prediction_log
                        SET compared_at = ?, comparison_status = 'actual_missing'
                        WHERE prediction_id = ?
                        """,
                        [compared_at, prediction_id],
                    )
                    missing_actual_count += 1
                    compared_count += 1
                    compared_prediction_ids.append(prediction_id)
                    continue

                error_pct = abs(predicted_time - actual_time) / actual_time * 100 if actual_time > 0 else None
                accepted = int(error_pct is not None and error_pct <= ACCEPTED_ERROR_PCT)
                conn.execute(
                    """
                    UPDATE prediction_log
                    SET actual_time = ?, error_pct = ?, accepted = ?, compared_at = ?, comparison_status = 'matched'
                    WHERE prediction_id = ?
                    """,
                    [actual_time, error_pct, accepted, compared_at, prediction_id],
                )
                compared_count += 1
                matched_count += 1
                compared_prediction_ids.append(prediction_id)
                if error_pct is not None:
                    error_values.append(error_pct)

            conn.commit()
        finally:
            conn.close()

        return {
            "rally_id": str(rally_id),
            "stage_id": stage_id,
            "compared_count": compared_count,
            "matched_count": matched_count,
            "missing_actual_count": missing_actual_count,
            "avg_error_pct": round(sum(error_values) / len(error_values), 3) if error_values else None,
            "compared_prediction_ids": compared_prediction_ids,
        }

    def log_prediction(
        self,
        run_id: str,
        rally_id: str,
        stage_id: str,
        driver_id: str,
        predicted_time: float,
        confidence: Optional[float],
        used_geometry: bool,
        data_quality_flags: List[str],
        model_version: str,
        comparison_status: str = "pending",
    ) -> int:
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO prediction_log (
                    run_id, rally_id, stage_id, driver_id, predicted_time, confidence,
                    used_geometry, data_quality_flags, model_version, comparison_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    run_id,
                    str(rally_id),
                    stage_id,
                    driver_id,
                    float(predicted_time),
                    float(confidence) if confidence is not None else None,
                    int(bool(used_geometry)),
                    json.dumps(sorted(set(data_quality_flags)), ensure_ascii=False),
                    model_version,
                    comparison_status,
                ],
            )
            conn.commit()
            return int(cursor.lastrowid)
        finally:
            conn.close()

    def mark_prediction_issue_resolved(
        self,
        prediction_id: int,
        issue_types: List[str],
        resolution_source: str,
        resolution_note: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not issue_types:
            return {"prediction_id": int(prediction_id), "resolved_issue_types": [], "updated": False}

        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT resolved_issue_types, resolution_note
                FROM prediction_log
                WHERE prediction_id = ?
                """,
                [int(prediction_id)],
            ).fetchone()
            if row is None:
                return {"prediction_id": int(prediction_id), "resolved_issue_types": [], "updated": False}

            try:
                resolved_issue_types = json.loads(row["resolved_issue_types"] or "[]")
                if not isinstance(resolved_issue_types, list):
                    resolved_issue_types = []
            except Exception:
                resolved_issue_types = []

            updated_issue_types = sorted(set(resolved_issue_types).union({str(item) for item in issue_types if item}))
            resolved_at = datetime.now().isoformat()
            note_parts = [part.strip() for part in [row["resolution_note"], resolution_note] if part and str(part).strip()]
            merged_note = " | ".join(dict.fromkeys(note_parts)) if note_parts else None

            conn.execute(
                """
                UPDATE prediction_log
                SET resolved_issue_types = ?, resolution_note = ?, resolved_at = ?, resolution_source = ?
                WHERE prediction_id = ?
                """,
                [
                    json.dumps(updated_issue_types, ensure_ascii=False),
                    merged_note,
                    resolved_at,
                    str(resolution_source),
                    int(prediction_id),
                ],
            )
            conn.commit()
        finally:
            conn.close()

        return {
            "prediction_id": int(prediction_id),
            "resolved_issue_types": updated_issue_types,
            "resolution_note": merged_note,
            "resolved_at": resolved_at,
            "resolution_source": str(resolution_source),
            "updated": True,
        }

    def resolve_driver(
        self,
        driver_id: Optional[str] = None,
        driver_name: Optional[str] = None,
        normalized_class: Optional[str] = None,
        car_class: Optional[str] = None,
    ) -> Dict[str, Any]:
        conn = self._connect()
        try:
            row = None
            if driver_id:
                row = conn.execute(
                    """
                    SELECT d.driver_id, d.display_name, MAX(sr.car_class) as car_class,
                           COALESCE(MAX(sr.normalized_class), MAX(sr.car_class)) as normalized_class
                    FROM drivers d
                    LEFT JOIN stage_results sr ON sr.driver_id = d.driver_id
                    WHERE d.driver_id = ?
                    GROUP BY d.driver_id, d.display_name
                    """,
                    [driver_id],
                ).fetchone()

            if row is None and driver_name:
                row = conn.execute(
                    """
                    SELECT d.driver_id, d.display_name, MAX(sr.car_class) as car_class,
                           COALESCE(MAX(sr.normalized_class), MAX(sr.car_class)) as normalized_class
                    FROM drivers d
                    LEFT JOIN driver_aliases da ON da.driver_id = d.driver_id
                    LEFT JOIN stage_results sr ON sr.driver_id = d.driver_id
                    WHERE d.display_name = ? OR da.alias_name = ?
                    GROUP BY d.driver_id, d.display_name
                    ORDER BY MAX(da.is_primary) DESC, d.display_name
                    LIMIT 1
                    """,
                    [driver_name, driver_name],
                ).fetchone()

            if row is None and driver_name:
                normalized_key = normalize_name_key(driver_name)
                row = conn.execute(
                    """
                    SELECT d.driver_id, d.display_name, MAX(sr.car_class) as car_class,
                           COALESCE(MAX(sr.normalized_class), MAX(sr.car_class)) as normalized_class
                    FROM drivers d
                    LEFT JOIN driver_aliases da ON da.driver_id = d.driver_id
                    LEFT JOIN stage_results sr ON sr.driver_id = d.driver_id
                    WHERE d.normalized_name_key = ? OR da.normalized_name_key = ?
                    GROUP BY d.driver_id, d.display_name
                    ORDER BY MAX(da.is_primary) DESC, d.display_name
                    LIMIT 1
                    """,
                    [normalized_key, normalized_key],
                ).fetchone()
        finally:
            conn.close()

        if row:
            return {
                "driver_id": row["driver_id"],
                "driver_name": row["display_name"],
                "car_class": car_class or row["car_class"],
                "normalized_class": normalized_class or row["normalized_class"] or car_class,
                "resolved": True,
            }

        display_name = driver_name or driver_id or "Unknown Driver"
        return {
            "driver_id": driver_id or build_driver_id(display_name),
            "driver_name": display_name,
            "car_class": car_class,
            "normalized_class": normalized_class or car_class,
            "resolved": False,
        }

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _generate_run_id(self, prefix: str) -> str:
        return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"

    def predict_kml_stage(
        self,
        driver_name: str,
        geo_features: Dict[str, Any],
        surface: str,
        stage_name: str,
        driver_id: Optional[str] = None,
        run_id: Optional[str] = None,
        log_prediction: bool = True,
    ) -> Dict[str, Any]:
        driver = self.resolve_driver(driver_id=driver_id, driver_name=driver_name)
        normalized_class = driver["normalized_class"] or driver["car_class"] or "unknown"

        baseline_result = self._calculate_baseline(driver["driver_id"])
        baseline_ratio = baseline_result["baseline_ratio"]
        surface_adj = self._calculate_surface_adjustment(driver["driver_id"], normalized_class, surface)
        momentum_factor = self._calculate_recent_momentum(driver["driver_id"], baseline_ratio)

        geo_assessment = self._assess_geometry_features(geo_features)
        geometric_correction = 1.0
        geo_mode = "baseline_only"
        if geo_assessment["trusted"]:
            geometric_correction, geo_mode = self._apply_geometric_correction(
                baseline_ratio=baseline_ratio,
                momentum_factor=momentum_factor,
                surface_adj=surface_adj,
                geo_features=geo_features,
                driver_id=driver["driver_id"],
                normalized_class=normalized_class,
                surface=surface,
            )

        final_ratio = float(_clip(baseline_ratio * momentum_factor * surface_adj * geometric_correction, 1.0, 1.8))
        stage_length = float(geo_features.get("distance_km") or 15.0)
        reference_time, _adjusted_speed, _geo_difficulty = self._calculate_reference_time(
            stage_length, surface, normalized_class, geo_features if geo_assessment["trusted"] else None
        )
        predicted_time = reference_time * final_ratio
        predicted_speed = (stage_length / predicted_time) * 3600 if predicted_time > 0 else 0.0
        confidence_score = self._calculate_confidence(baseline_result, None, geo_mode, surface_adj)
        confidence_level = self._confidence_level(confidence_score)

        prediction = {
            "driver_id": driver["driver_id"],
            "driver_name": driver["driver_name"],
            "car_class": driver["car_class"],
            "normalized_class": normalized_class,
            "rally_id": "kml_manual",
            "stage_id": f"kml_{slugify(stage_name, fallback='stage')}",
            "stage_name": stage_name,
            "stage_length_km": stage_length,
            "surface": surface,
            "predicted_time_str": self._format_time(predicted_time),
            "predicted_time_seconds": predicted_time,
            "predicted_speed_kmh": predicted_speed,
            "predicted_ratio": final_ratio,
            "reference_time_str": self._format_time(reference_time),
            "baseline_ratio": baseline_ratio,
            "momentum_factor": momentum_factor,
            "surface_adj": surface_adj,
            "geometric_correction": geometric_correction,
            "geometric_mode": geo_mode,
            "confidence_level": confidence_level,
            "confidence_score": confidence_score,
            "data_quality_flags": self._build_quality_flags(
                geometry_trusted=geo_assessment["trusted"],
                extra_flags=geo_assessment["flags"],
            ),
            "used_geometry": int(geo_mode == "geometric"),
            "model_version": "prediction_service_kml_v1",
            "explanation": self._build_simple_explanation(
                driver_name=driver["driver_name"],
                stage_name=stage_name,
                stage_length_km=stage_length,
                surface=surface,
                baseline_ratio=baseline_ratio,
                momentum_factor=momentum_factor,
                surface_adj=surface_adj,
                geometric_correction=geometric_correction,
                geo_mode=geo_mode,
                reference_time=reference_time,
                predicted_time=predicted_time,
                predicted_speed=predicted_speed,
                confidence_level=confidence_level,
                confidence_score=confidence_score,
            ),
        }

        if log_prediction:
            run_id = run_id or self._generate_run_id("kml")
            prediction["run_id"] = run_id
            prediction["prediction_id"] = self.log_prediction(
                run_id=run_id,
                rally_id=prediction["rally_id"],
                stage_id=prediction["stage_id"],
                driver_id=driver["driver_id"],
                predicted_time=predicted_time,
                confidence=confidence_score,
                used_geometry=geo_mode == "geometric",
                data_quality_flags=prediction["data_quality_flags"],
                model_version=prediction["model_version"],
                comparison_status="not_applicable",
            )

        return prediction

    def predict_live_stage(
        self,
        rally_data: Dict[str, Any],
        driver_name: str,
        driver_class: str,
        predict_stage_num: int,
        surface: Optional[str] = None,
        geo_features: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
        log_prediction: bool = True,
    ) -> Dict[str, Any]:
        rally_id = str(rally_data["rally_id"])
        stage_id = build_stage_id(rally_id, predict_stage_num) or f"{rally_id}_ss{predict_stage_num}"
        normalized_class = self._normalize_class(driver_class)
        driver = self.resolve_driver(driver_name=driver_name, normalized_class=normalized_class, car_class=driver_class)
        resolved_surface = surface or rally_data.get("surface") or "gravel"

        baseline_result = self._calculate_baseline(driver["driver_id"])
        baseline_ratio = baseline_result["baseline_ratio"]

        previous_stages = [s for s in rally_data.get("stages", []) if int(s.get("stage_number", 0) or 0) < int(predict_stage_num)]
        for stage in previous_stages:
            for result in stage.get("results", []):
                if not result.get("time_seconds"):
                    result["time_seconds"] = self._parse_time_str(result.get("time_str", ""))

        try:
            momentum_result = RallyMomentumAnalyzer(self.db_path).calculate_momentum_from_live_data(
                stages_data=previous_stages,
                driver_name=driver_name,
                normalized_class=normalized_class,
                driver_baseline=baseline_ratio,
            )
            momentum_factor = momentum_result["momentum_factor"]
        except Exception as exc:
            momentum_result = {"status": f"Hesaplanamadi ({exc})", "momentum": 0.0, "stages_analyzed": 0}
            momentum_factor = 1.0

        surface_adj = self._calculate_surface_adjustment(driver["driver_id"], normalized_class, resolved_surface)

        stage_data = next(
            (stage for stage in rally_data.get("stages", []) if int(stage.get("stage_number", 0) or 0) == int(predict_stage_num)),
            None,
        )
        stage_name = stage_data.get("stage_name") if stage_data else f"SS{predict_stage_num}"
        stage_length = 15.0
        if geo_features and float(geo_features.get("distance_km") or 0) > 0.5:
            stage_length = float(geo_features["distance_km"])
        elif stage_data and float(stage_data.get("stage_length_km") or 0) > 0.5:
            stage_length = float(stage_data["stage_length_km"])

        stage_context = self.resolve_stage_context(
            rally_id=rally_id,
            stage_number=predict_stage_num,
            stage_id=stage_id,
            stage_name=stage_name,
            surface=resolved_surface,
            stage_length_km=stage_length,
            geo_features=geo_features,
        )
        geo_assessment = self._assess_stage_geometry(stage_context, geo_features)

        geometric_correction = 1.0
        geo_mode = "baseline_only"
        if geo_assessment["trusted"] and geo_features:
            geometric_correction, geo_mode = self._apply_geometric_correction(
                baseline_ratio=baseline_ratio,
                momentum_factor=momentum_factor,
                surface_adj=surface_adj,
                geo_features=geo_features,
                driver_id=driver["driver_id"],
                normalized_class=normalized_class,
                surface=stage_context["surface"],
            )

        final_ratio = float(_clip(baseline_ratio * momentum_factor * surface_adj * geometric_correction, 1.0, 1.8))
        reference_time, _adjusted_speed, _geo_difficulty = self._calculate_reference_time(
            stage_context["stage_length_km"],
            stage_context["surface"],
            normalized_class,
            geo_features if geo_assessment["trusted"] else None,
        )
        predicted_time = reference_time * final_ratio
        predicted_speed = (stage_context["stage_length_km"] / predicted_time) * 3600 if predicted_time > 0 else 0.0
        confidence_score = self._calculate_confidence(baseline_result, momentum_result, geo_mode, surface_adj)
        confidence_level = self._confidence_level(confidence_score)

        prediction = {
            "driver_id": driver["driver_id"],
            "driver_name": driver["driver_name"],
            "car_class": driver_class,
            "normalized_class": normalized_class,
            "rally_id": rally_id,
            "stage_id": stage_context["stage_id"],
            "stage_name": stage_context["stage_name"],
            "stage_number": predict_stage_num,
            "stage_length_km": stage_context["stage_length_km"],
            "surface": stage_context["surface"],
            "predicted_time_str": self._format_time(predicted_time),
            "predicted_time_seconds": predicted_time,
            "predicted_speed_kmh": predicted_speed,
            "predicted_ratio": final_ratio,
            "reference_time_str": self._format_time(reference_time),
            "baseline_ratio": baseline_ratio,
            "momentum_factor": momentum_factor,
            "surface_adj": surface_adj,
            "geometric_correction": geometric_correction,
            "geometric_mode": geo_mode,
            "confidence_level": confidence_level,
            "confidence_score": confidence_score,
            "used_geometry": int(geo_mode == "geometric"),
            "data_quality_flags": self._build_quality_flags(
                geometry_trusted=geo_assessment["trusted"],
                extra_flags=geo_assessment["flags"],
            ),
            "model_version": "prediction_service_live_v1",
            "explanation": self._build_simple_explanation(
                driver_name=driver["driver_name"],
                stage_name=stage_context["stage_name"],
                stage_length_km=stage_context["stage_length_km"],
                surface=stage_context["surface"],
                baseline_ratio=baseline_ratio,
                momentum_factor=momentum_factor,
                surface_adj=surface_adj,
                geometric_correction=geometric_correction,
                geo_mode=geo_mode,
                reference_time=reference_time,
                predicted_time=predicted_time,
                predicted_speed=predicted_speed,
                confidence_level=confidence_level,
                confidence_score=confidence_score,
                momentum_status=momentum_result.get("status"),
            ),
        }

        if log_prediction:
            run_id = run_id or self._generate_run_id("live")
            prediction["run_id"] = run_id
            prediction["prediction_id"] = self.log_prediction(
                run_id=run_id,
                rally_id=rally_id,
                stage_id=stage_context["stage_id"],
                driver_id=driver["driver_id"],
                predicted_time=predicted_time,
                confidence=confidence_score,
                used_geometry=geo_mode == "geometric",
                data_quality_flags=prediction["data_quality_flags"],
                model_version=prediction["model_version"],
                comparison_status="pending",
            )

        return prediction

    def resolve_stage_context(
        self,
        rally_id: str,
        stage_number: Optional[int] = None,
        stage_id: Optional[str] = None,
        stage_name: Optional[str] = None,
        surface: Optional[str] = None,
        stage_length_km: Optional[float] = None,
        geo_features: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        resolved_stage_id = stage_id or build_stage_id(rally_id, stage_number) or f"{rally_id}_ss{stage_number or 0}"
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT
                    s.stage_id,
                    s.rally_id,
                    s.stage_number,
                    s.stage_name,
                    COALESCE(
                        CASE
                            WHEN s.surface_override = 1 AND s.surface IS NOT NULL THEN s.surface
                            ELSE NULL
                        END,
                        r.surface,
                        sg.surface
                    ) as surface,
                    COALESCE(s.length_km, sg.distance_km) as stage_length_km,
                    sg.elevation_status,
                    sg.geometry_status,
                    sg.analysis_version,
                    sg.source_kml
                FROM stages s
                LEFT JOIN rallies r ON r.rally_id = s.rally_id
                LEFT JOIN stage_geometry sg ON sg.stage_id = s.stage_id AND COALESCE(sg.is_active, 1) = 1
                WHERE s.stage_id = ? OR (s.rally_id = ? AND s.stage_number = ?)
                LIMIT 1
                """,
                [resolved_stage_id, str(rally_id), stage_number],
            ).fetchone()
        finally:
            conn.close()

        context = {
            "stage_id": resolved_stage_id,
            "rally_id": str(rally_id),
            "stage_number": stage_number,
            "stage_name": stage_name or resolved_stage_id,
            "surface": surface or "gravel",
            "stage_length_km": float(stage_length_km or 0) or 15.0,
            "elevation_status": None,
            "geometry_status": None,
            "analysis_version": None,
            "source_kml": None,
        }
        if row:
            context.update(
                {
                    "stage_id": row["stage_id"] or context["stage_id"],
                    "rally_id": row["rally_id"] or context["rally_id"],
                    "stage_number": row["stage_number"] or context["stage_number"],
                    "stage_name": row["stage_name"] or context["stage_name"],
                    "surface": row["surface"] or context["surface"],
                    "stage_length_km": float(row["stage_length_km"] or context["stage_length_km"]),
                    "elevation_status": row["elevation_status"],
                    "geometry_status": row["geometry_status"],
                    "analysis_version": row["analysis_version"],
                    "source_kml": row["source_kml"],
                }
            )

        if geo_features and float(geo_features.get("distance_km") or 0) > 0.5:
            context["stage_length_km"] = float(geo_features["distance_km"])
        if surface:
            context["surface"] = surface
        return context

    def _calculate_baseline(self, driver_id: str) -> Dict[str, Any]:
        perf_analyzer = DriverPerformanceAnalyzer(self.db_path)
        baseline_result = perf_analyzer.calculate_baseline_ratio(driver_id)
        if baseline_result:
            return baseline_result
        return {
            "baseline_ratio": self._fallback_baseline(driver_id),
            "data_points": 0,
            "total_stages": 0,
        }

    def _calculate_recent_momentum(self, driver_id: str, baseline_ratio: float) -> float:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT rally_id
                FROM stage_results
                WHERE COALESCE(driver_id, driver_name) = ? AND time_seconds > 0
                ORDER BY CAST(rally_id AS INTEGER) DESC, stage_number DESC
                LIMIT 1
                """,
                [driver_id],
            ).fetchone()
        finally:
            conn.close()

        if not row:
            return 1.0

        try:
            momentum_result = RallyMomentumAnalyzer(self.db_path).calculate_momentum(
                driver_name=driver_id,
                rally_id=str(row["rally_id"]),
                current_stage=99,
                driver_baseline=baseline_ratio,
            )
            return momentum_result.get("momentum_factor", 1.0)
        except Exception:
            return 1.0

    def _fallback_baseline(self, driver_id: str) -> float:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT AVG(ratio_to_class_best) as avg_ratio
                FROM stage_results
                WHERE COALESCE(driver_id, driver_name) = ?
                  AND time_seconds > 0
                  AND ratio_to_class_best IS NOT NULL
                  AND ratio_to_class_best > 0
                """,
                [driver_id],
            ).fetchone()
        finally:
            conn.close()

        return float(row["avg_ratio"]) if row and row["avg_ratio"] else 1.1

    def _calculate_surface_adjustment(self, driver_id: str, normalized_class: str, target_surface: str) -> float:
        conn = self._connect()
        try:
            surface_row = conn.execute(
                """
                SELECT AVG(ratio_to_class_best) as avg_ratio, COUNT(*) as cnt
                FROM stage_results
                WHERE COALESCE(driver_id, driver_name) = ?
                  AND LOWER(surface) = LOWER(?)
                  AND ratio_to_class_best IS NOT NULL
                  AND ratio_to_class_best > 0
                """,
                [driver_id, target_surface],
            ).fetchone()
            overall_row = conn.execute(
                """
                SELECT AVG(ratio_to_class_best) as avg_ratio
                FROM stage_results
                WHERE COALESCE(driver_id, driver_name) = ?
                  AND ratio_to_class_best IS NOT NULL
                  AND ratio_to_class_best > 0
                """,
                [driver_id],
            ).fetchone()
        finally:
            conn.close()

        if (
            surface_row
            and surface_row["cnt"]
            and int(surface_row["cnt"]) >= 3
            and overall_row
            and overall_row["avg_ratio"]
        ):
            surface_ratio = float(surface_row["avg_ratio"])
            overall_ratio = float(overall_row["avg_ratio"])
            if overall_ratio > 0:
                return surface_ratio / overall_ratio

        return 1.0

    def _apply_geometric_correction(
        self,
        baseline_ratio: float,
        momentum_factor: float,
        surface_adj: float,
        geo_features: Dict[str, Any],
        driver_id: str,
        normalized_class: str,
        surface: str,
    ) -> tuple[float, str]:
        if not self.model_path or not Path(self.model_path).exists():
            return 1.0, "baseline_only"

        import pickle

        try:
            with open(self.model_path, "rb") as handle:
                model_data = pickle.load(handle)
            model = model_data["model"]
            feature_cols = model_data["feature_columns"]
            import pandas as pd

            conn = self._connect()
            try:
                driver_stats = pd.read_sql_query(
                    """
                    SELECT COUNT(*) as stage_count, AVG(ratio_to_class_best) as avg_ratio
                    FROM stage_results
                    WHERE COALESCE(driver_id, driver_name) = ?
                      AND time_seconds > 0
                      AND ratio_to_class_best IS NOT NULL
                    """,
                    conn,
                    params=[driver_id],
                )
                surface_stats = pd.read_sql_query(
                    """
                    SELECT AVG(ratio_to_class_best) as surface_ratio
                    FROM stage_results
                    WHERE COALESCE(driver_id, driver_name) = ?
                      AND LOWER(surface) = LOWER(?)
                      AND ratio_to_class_best IS NOT NULL
                    """,
                    conn,
                    params=[driver_id, surface],
                )
            finally:
                conn.close()

            driver_stage_count = int(driver_stats.iloc[0]["stage_count"]) if len(driver_stats) > 0 else 0
            driver_avg_ratio = (
                float(driver_stats.iloc[0]["avg_ratio"])
                if len(driver_stats) > 0 and driver_stats.iloc[0]["avg_ratio"]
                else baseline_ratio
            )
            driver_surface_ratio = (
                float(surface_stats.iloc[0]["surface_ratio"])
                if len(surface_stats) > 0 and surface_stats.iloc[0]["surface_ratio"]
                else driver_avg_ratio
            )

            features = {
                "baseline_ratio": baseline_ratio,
                "stage_length_km": geo_features.get("distance_km", 15),
                "hairpin_count": geo_features.get("hairpin_count", 0),
                "hairpin_density": geo_features.get("hairpin_density", 0),
                "turn_count": geo_features.get("turn_count", 0),
                "turn_density": geo_features.get("turn_density", 0),
                "total_ascent": geo_features.get("total_ascent", 0),
                "total_descent": geo_features.get("total_descent", 0),
                "avg_curvature": geo_features.get("avg_curvature", 0),
                "max_curvature": geo_features.get("max_curvature", 0),
                "p95_curvature": geo_features.get("p95_curvature", 0),
                "curvature_density": geo_features.get("curvature_density", 0),
                "max_grade": geo_features.get("max_grade", 0),
                "avg_abs_grade": geo_features.get("avg_abs_grade", 0),
                "straight_percentage": geo_features.get("straight_ratio", 0) * 100,
                "curvy_percentage": (1 - geo_features.get("straight_ratio", 0)) * 100,
                "driver_stage_count": driver_stage_count,
                "driver_avg_ratio": driver_avg_ratio,
                "driver_surface_ratio": driver_surface_ratio,
                "momentum_factor": momentum_factor,
                "surface": surface,
                "normalized_class": normalized_class,
            }

            frame = pd.DataFrame([features])
            available_cols = [column for column in feature_cols if column in frame.columns]
            frame = frame[available_cols]
            for column in ("surface", "normalized_class"):
                if column in frame.columns:
                    frame[column] = frame[column].astype("category")

            correction = float(model.predict(frame)[0])
            return float(_clip(correction, 0.9, 1.1)), "geometric"
        except Exception as exc:
            return 1.0, f"baseline_only ({exc})"

    def _calculate_reference_time(
        self,
        stage_length: float,
        surface: str,
        normalized_class: str,
        geo_features: Optional[Dict[str, Any]] = None,
    ) -> tuple[float, float, float]:
        if surface == "asphalt":
            base_speed = 105
        elif surface == "snow":
            base_speed = 70
        else:
            base_speed = 85

        class_factors = {
            "WRC": 1.0,
            "Rally1": 1.0,
            "Rally2": 1.08,
            "R5": 1.08,
            "Rally3": 1.15,
            "R2": 1.15,
            "Rally4": 1.12,
            "Rally5": 1.18,
            "N": 1.15,
            "K1": 1.10,
            "K2": 1.12,
            "K3": 1.18,
            "K4": 1.22,
            "H1": 1.10,
            "H2": 1.15,
        }
        class_factor = class_factors.get(normalized_class, 1.10)
        geo_difficulty = 1.0
        if geo_features:
            geo_difficulty += float(geo_features.get("hairpin_density", 0) or 0) * 0.02
            geo_difficulty += float(geo_features.get("avg_abs_grade", 0) or 0) * 0.005
            geo_difficulty = min(geo_difficulty, 1.3)

        adjusted_speed = base_speed / class_factor / geo_difficulty
        reference_time = (stage_length / adjusted_speed) * 3600
        return reference_time, adjusted_speed, geo_difficulty

    def _calculate_confidence(
        self,
        baseline_result: Optional[Dict[str, Any]],
        momentum_info: Optional[Dict[str, Any]],
        geo_mode: str,
        surface_adj: float,
    ) -> float:
        score = 30
        if baseline_result:
            score += min(int(baseline_result.get("data_points", 0) or 0) * 5, 20)
            score += min(int(baseline_result.get("total_stages", 0) or 0), 15)
        if momentum_info and int(momentum_info.get("stages_analyzed", 0) or 0) > 0:
            score += min(int(momentum_info["stages_analyzed"]) * 3, 15)
        if geo_mode == "geometric":
            score += 10
        if abs(surface_adj - 1.0) > 1e-6:
            score += 5
        return min(100.0, float(score))

    def _assess_stage_geometry(
        self,
        stage_context: Dict[str, Any],
        geo_features: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        flags: List[str] = []
        trusted = False

        geometry_status = stage_context.get("geometry_status")
        elevation_status = stage_context.get("elevation_status")
        if geometry_status == "validated" and elevation_status != "missing":
            trusted = True
        elif geometry_status:
            flags.append(str(geometry_status))
        elif geo_features:
            return self._assess_geometry_features(geo_features)
        else:
            flags.append("geometry_missing")

        if elevation_status == "missing":
            flags.append("elevation_missing")
        if not trusted:
            flags.append("baseline_only")
        return {"trusted": trusted, "flags": flags}

    def _assess_geometry_features(self, geo_features: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not geo_features:
            return {"trusted": False, "flags": ["geometry_missing", "baseline_only"]}

        distance_km = float(geo_features.get("distance_km") or 0)
        total_ascent = float(geo_features.get("total_ascent") or 0)
        total_descent = float(geo_features.get("total_descent") or 0)
        max_grade = float(geo_features.get("max_grade") or 0)
        max_elevation = float(geo_features.get("max_elevation") or geo_features.get("max_altitude") or 0)
        min_elevation = float(geo_features.get("min_elevation") or geo_features.get("min_altitude") or 0)

        has_elevation = any(
            value != 0.0 for value in (total_ascent, total_descent, max_grade, max_elevation, min_elevation)
        )
        if distance_km > 3 and total_ascent == 0 and total_descent == 0 and max_grade == 0:
            return {
                "trusted": False,
                "flags": ["red_flag_missing_elevation", "elevation_missing", "baseline_only"],
            }
        if not has_elevation:
            return {"trusted": False, "flags": ["elevation_missing", "baseline_only"]}
        return {"trusted": True, "flags": []}

    def _build_quality_flags(self, geometry_trusted: bool, extra_flags: Optional[List[str]] = None) -> List[str]:
        flags = list(extra_flags or [])
        if geometry_trusted:
            flags.append("geometry_trusted")
        else:
            flags.append("baseline_only")
        return sorted(set(flags))

    def _build_simple_explanation(
        self,
        driver_name: str,
        stage_name: str,
        stage_length_km: float,
        surface: str,
        baseline_ratio: float,
        momentum_factor: float,
        surface_adj: float,
        geometric_correction: float,
        geo_mode: str,
        reference_time: float,
        predicted_time: float,
        predicted_speed: float,
        confidence_level: str,
        confidence_score: float,
        momentum_status: Optional[str] = None,
    ) -> str:
        lines = [
            "### Tahmin Detaylari",
            "",
            f"Pilot: {driver_name}",
            f"Etap: {stage_name} ({stage_length_km:.2f} km, {surface})",
            "",
            f"Baseline ratio: {baseline_ratio:.4f}",
            f"Momentum factor: {momentum_factor:.4f}",
            f"Surface adjustment: {surface_adj:.4f}",
            f"Geometrik duzeltme: {geometric_correction:.4f} ({geo_mode})",
        ]
        if momentum_status:
            lines.append(f"Momentum: {momentum_status}")
        lines.extend(
            [
                "",
                f"Referans sure: {self._format_time(reference_time)}",
                f"Tahmini sure: {self._format_time(predicted_time)}",
                f"Tahmini hiz: {predicted_speed:.1f} km/h",
                f"Guven: {confidence_level} ({confidence_score:.0f}/100)",
            ]
        )
        return "\n".join(lines)

    def _normalize_class(self, car_class: Optional[str]) -> str:
        if self.class_normalizer and car_class:
            try:
                return self.class_normalizer.normalize(car_class)
            except Exception:
                pass
        return car_class or "unknown"

    def _confidence_level(self, confidence_score: float) -> str:
        if confidence_score >= 75:
            return "HIGH"
        if confidence_score >= 55:
            return "MEDIUM"
        return "LOW"

    def _parse_time_str(self, time_str: str) -> float:
        if not time_str or ":" not in time_str:
            return 0.0
        try:
            time_str = time_str.replace(",", ".")
            parts = time_str.split(":")
            if len(parts) == 2:
                return float(parts[0]) * 60 + float(parts[1])
            if len(parts) == 3:
                first, second, third = float(parts[0]), float(parts[1]), float(parts[2])
                if third < 10 and second < 60:
                    return first * 60 + second + third / 10.0
                return first * 3600 + second * 60 + third
        except Exception:
            return 0.0
        return 0.0

    def _format_time(self, seconds: float) -> str:
        if seconds <= 0:
            return "0:00.00"
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}:{secs:05.2f}"

    def get_prediction_log_rows(
        self,
        limit: int = 200,
        rally_id: Optional[str] = None,
        comparison_status: Optional[str] = None,
        driver_id: Optional[str] = None,
        only_flag: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        conn = self._connect()
        try:
            query = """
                SELECT
                    pl.prediction_id,
                    pl.run_id,
                    pl.rally_id,
                    pl.stage_id,
                    pl.driver_id,
                    COALESCE(d.display_name, pl.driver_id) as driver_name,
                    pl.predicted_time,
                    pl.confidence,
                    pl.used_geometry,
                    pl.data_quality_flags,
                    pl.model_version,
                    pl.predicted_at,
                    pl.actual_time,
                    pl.error_pct,
                    pl.accepted,
                    pl.compared_at,
                    pl.comparison_status,
                    pl.resolved_issue_types,
                    pl.resolution_note,
                    pl.resolved_at,
                    pl.resolution_source
                FROM prediction_log pl
                LEFT JOIN drivers d ON d.driver_id = pl.driver_id
                WHERE 1 = 1
            """
            params: List[Any] = []

            if rally_id:
                query += " AND pl.rally_id = ?"
                params.append(str(rally_id))
            if comparison_status:
                query += " AND pl.comparison_status = ?"
                params.append(comparison_status)
            if driver_id:
                query += " AND pl.driver_id = ?"
                params.append(driver_id)
            if only_flag:
                query += " AND pl.data_quality_flags LIKE ?"
                params.append(f"%{only_flag}%")

            query += " ORDER BY COALESCE(pl.compared_at, pl.predicted_at) DESC, pl.prediction_id DESC LIMIT ?"
            params.append(int(limit))

            rows = [dict(row) for row in conn.execute(query, params).fetchall()]
        finally:
            conn.close()

        for row in rows:
            try:
                flags = json.loads(row.get("data_quality_flags") or "[]")
                if not isinstance(flags, list):
                    flags = []
            except Exception:
                flags = []
            try:
                resolved_issue_types = json.loads(row.get("resolved_issue_types") or "[]")
                if not isinstance(resolved_issue_types, list):
                    resolved_issue_types = []
            except Exception:
                resolved_issue_types = []
            row["data_quality_flags_list"] = flags
            row["data_quality_flags_display"] = ", ".join(flags)
            row["resolved_issue_types_list"] = resolved_issue_types
            row["resolved_issue_types_display"] = ", ".join(resolved_issue_types)
            row["predicted_time_str"] = self._format_time(float(row["predicted_time"] or 0))
            row["actual_time_str"] = self._format_time(float(row["actual_time"] or 0)) if row.get("actual_time") else None
            row["used_geometry_label"] = "yes" if int(row.get("used_geometry") or 0) else "no"
            if row.get("accepted") is None:
                row["accepted_label"] = "-"
            else:
                row["accepted_label"] = "yes" if int(row["accepted"]) == 1 else "no"
        return rows

    def get_prediction_log_summary(
        self,
        rally_id: Optional[str] = None,
        comparison_status: Optional[str] = None,
    ) -> Dict[str, Any]:
        conn = self._connect()
        try:
            query = """
                SELECT
                    COUNT(*) as total_predictions,
                    SUM(CASE WHEN comparison_status = 'pending' THEN 1 ELSE 0 END) as pending_count,
                    SUM(CASE WHEN comparison_status = 'matched' THEN 1 ELSE 0 END) as matched_count,
                    SUM(CASE WHEN comparison_status = 'actual_missing' THEN 1 ELSE 0 END) as actual_missing_count,
                    SUM(CASE WHEN accepted = 1 THEN 1 ELSE 0 END) as accepted_count,
                    SUM(CASE WHEN accepted = 0 AND comparison_status = 'matched' THEN 1 ELSE 0 END) as rejected_count,
                    AVG(error_pct) as avg_error_pct,
                    SUM(CASE WHEN used_geometry = 1 THEN 1 ELSE 0 END) as geometry_used_count,
                    SUM(CASE WHEN data_quality_flags LIKE '%baseline_only%' THEN 1 ELSE 0 END) as baseline_only_count
                FROM prediction_log
                WHERE 1 = 1
            """
            params: List[Any] = []
            if rally_id:
                query += " AND rally_id = ?"
                params.append(str(rally_id))
            if comparison_status:
                query += " AND comparison_status = ?"
                params.append(comparison_status)
            row = dict(conn.execute(query, params).fetchone())
        finally:
            conn.close()

        total = int(row.get("total_predictions") or 0)
        matched = int(row.get("matched_count") or 0)
        accepted = int(row.get("accepted_count") or 0)
        row["acceptance_rate_pct"] = round((accepted / matched) * 100, 2) if matched else None
        row["geometry_usage_rate_pct"] = round((int(row.get("geometry_used_count") or 0) / total) * 100, 2) if total else None
        row["avg_error_pct"] = round(float(row["avg_error_pct"]), 3) if row.get("avg_error_pct") is not None else None
        return row

    def get_prediction_quality_breakdown(
        self,
        rally_id: Optional[str] = None,
        comparison_status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        rows = self.get_prediction_log_rows(
            limit=5000,
            rally_id=rally_id,
            comparison_status=comparison_status,
        )
        counts: Dict[str, int] = {}
        for row in rows:
            for flag in row.get("data_quality_flags_list", []):
                counts[flag] = counts.get(flag, 0) + 1
        return [
            {"flag": flag, "count": count}
            for flag, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        ]

    def get_prediction_log_filter_options(self) -> Dict[str, List[str]]:
        conn = self._connect()
        try:
            rally_ids = [
                row[0]
                for row in conn.execute(
                    "SELECT DISTINCT rally_id FROM prediction_log ORDER BY rally_id DESC"
                ).fetchall()
                if row[0] is not None
            ]
            statuses = [
                row[0]
                for row in conn.execute(
                    "SELECT DISTINCT comparison_status FROM prediction_log ORDER BY comparison_status"
                ).fetchall()
                if row[0] is not None
            ]
        finally:
            conn.close()
        return {"rally_ids": rally_ids, "comparison_statuses": statuses}

    def _resolve_issue_action_target(
        self,
        issue_type: str,
        row: Dict[str, Any],
    ) -> Dict[str, str]:
        flags = set(row.get("data_quality_flags_list", []))

        if issue_type == "actual_missing":
            return {
                "action_target_page": "Veri Cek",
                "action_target_section": "Database Yukle",
                "action_target_label": "Sonuc Merge",
            }
        if issue_type == "pending_compare":
            return {
                "action_target_page": "Tahmin Yap",
                "action_target_section": "Canli Tahmin",
                "action_target_label": "Canli Akis",
            }
        if issue_type in {
            "geometry_missing",
            "elevation_missing",
            "red_flag_missing_elevation",
            "baseline_only",
        }:
            return {
                "action_target_page": "KML Yonetimi",
                "action_target_section": "Manuel Analiz",
                "action_target_label": "Geometriyi Duzenle",
            }
        if issue_type == "high_error":
            if "manual_input" in flags:
                return {
                    "action_target_page": "Tahmin Yap",
                    "action_target_section": "Manuel Tahmin",
                    "action_target_label": "Tahmini Gozden Gecir",
                }
            return {
                "action_target_page": "KML Yonetimi",
                "action_target_section": "Manuel Analiz",
                "action_target_label": "Etabi Incele",
            }
        return {
            "action_target_page": "Tahmin Yap",
            "action_target_section": "Degerlendirme",
            "action_target_label": "Detayi Ac",
        }

    def _build_prediction_issue_items(
        self,
        row: Dict[str, Any],
        high_error_pct: float = ACCEPTED_ERROR_PCT,
    ) -> List[Dict[str, Any]]:
        flags = set(row.get("data_quality_flags_list", []))
        resolved_issue_types = set(row.get("resolved_issue_types_list", []))
        comparison_status = str(row.get("comparison_status") or "")
        error_pct = row.get("error_pct")
        is_manual_only = comparison_status == "not_applicable" and "manual_input" in flags

        issues: List[Dict[str, Any]] = []

        def add_issue(
            issue_type: str,
            priority: str,
            title: str,
            reason: str,
            action: str,
        ) -> None:
            if issue_type in resolved_issue_types:
                return
            target = self._resolve_issue_action_target(issue_type, row)
            issue = {
                "prediction_id": row["prediction_id"],
                "predicted_at": row["predicted_at"],
                "rally_id": row["rally_id"],
                "stage_id": row["stage_id"],
                "driver_id": row["driver_id"],
                "driver_name": row["driver_name"],
                "comparison_status": comparison_status,
                "confidence": row.get("confidence"),
                "used_geometry": row.get("used_geometry"),
                "used_geometry_label": row.get("used_geometry_label"),
                "error_pct": error_pct,
                "error_pct_display": f"{float(error_pct):.2f}" if error_pct is not None else "-",
                "quality_flags": row.get("data_quality_flags_display") or "-",
                "data_quality_flags_list": row.get("data_quality_flags_list", []),
                "issue_type": issue_type,
                "priority": priority,
                "issue_title": title,
                "issue_reason": reason,
                "recommended_action": action,
                **target,
            }
            issues.append(issue)

        if "red_flag_missing_elevation" in flags:
            add_issue(
                "red_flag_missing_elevation",
                "P1",
                "Kirmizi Bayrak: Yukseklik Eksik",
                "Etap geometrisinde mesafe anlamli ama yukseklik metrikleri sifir gorunuyor.",
                "KML veya elevation kaynagini yeniden analiz edin; bu kaydi egitim ve full-mode tahminden gecici olarak dislayin.",
            )
        elif "elevation_missing" in flags and not is_manual_only:
            add_issue(
                "elevation_missing",
                "P2",
                "Yukseklik Verisi Eksik",
                "Geometri mevcut olsa da yukseklik bilgisi guvenilir degil.",
                "Elevation kaynagini tamamlayin; duzelene kadar baseline-only modunu koruyun.",
            )
        elif "geometry_missing" in flags and not is_manual_only:
            add_issue(
                "geometry_missing",
                "P2",
                "Geometri Kaydi Eksik",
                "Etap icin aktif stage_geometry kaydi bulunamadi.",
                "Dogru stage_id ile KML/geometry merge akisini yeniden calistirin.",
            )

        if comparison_status == "actual_missing":
            add_issue(
                "actual_missing",
                "P1",
                "Gercek Sonuc Eksik",
                "Tahmin logu var ama karsilastirma icin gercek etap sonucu bulunamadi.",
                "Ilgili etap sonucunu master result DB'ye alin ve compare previous akisina tekrar sokun.",
            )
        elif comparison_status == "pending":
            add_issue(
                "pending_compare",
                "P3",
                "Karsilastirma Bekliyor",
                "Tahmin kaydi alinmis, gercek sonuc ile kapanis henuz yapilmamis.",
                "Etap sonucu geldiyse compare previous + predict next aksiyonunu calistirin.",
            )

        if comparison_status == "matched" and error_pct is not None and float(error_pct) > float(high_error_pct):
            add_issue(
                "high_error",
                "P1",
                "Yuksek Tahmin Hatasi",
                f"Gercek sonuc ile tahmin arasindaki hata kabul esigini (%{float(high_error_pct):.1f}) asti.",
                "driver_id, stage_id, surface ve geometry guvenini birlikte gozden gecirin; gerekiyorsa alias veya stage eslemesini duzeltin.",
            )

        if (
            "baseline_only" in flags
            and not is_manual_only
            and "red_flag_missing_elevation" not in flags
            and "elevation_missing" not in flags
            and "geometry_missing" not in flags
        ):
            add_issue(
                "baseline_only",
                "P2",
                "Sadece Baseline Modu",
                "Tahmin geometri duzeltmesi kullanmadan uretilmis.",
                "Bu etap icin geometri kaydinin dogrulugunu ve quality status alanlarini kontrol edin.",
            )

        return issues

    def get_prediction_issue_worklist(
        self,
        limit: int = 200,
        rally_id: Optional[str] = None,
        comparison_status: Optional[str] = None,
        only_flag: Optional[str] = None,
        issue_type: Optional[str] = None,
        priority: Optional[str] = None,
        high_error_pct: float = ACCEPTED_ERROR_PCT,
    ) -> List[Dict[str, Any]]:
        rows = self.get_prediction_log_rows(
            limit=5000,
            rally_id=rally_id,
            comparison_status=comparison_status,
            only_flag=only_flag,
        )
        issues: List[Dict[str, Any]] = []
        for row in rows:
            issues.extend(self._build_prediction_issue_items(row, high_error_pct=high_error_pct))

        if issue_type:
            issues = [item for item in issues if item["issue_type"] == issue_type]
        if priority:
            issues = [item for item in issues if item["priority"] == priority]

        priority_rank = {"P1": 1, "P2": 2, "P3": 3}
        issues.sort(
            key=lambda item: (
                priority_rank.get(item["priority"], 99),
                -int(item["prediction_id"]),
            )
        )
        return issues[: int(limit)]

    def get_prediction_issue_breakdown(
        self,
        rally_id: Optional[str] = None,
        comparison_status: Optional[str] = None,
        only_flag: Optional[str] = None,
        high_error_pct: float = ACCEPTED_ERROR_PCT,
    ) -> List[Dict[str, Any]]:
        issues = self.get_prediction_issue_worklist(
            limit=5000,
            rally_id=rally_id,
            comparison_status=comparison_status,
            only_flag=only_flag,
            high_error_pct=high_error_pct,
        )
        counts: Dict[tuple[str, str, str], int] = {}
        for item in issues:
            key = (item["issue_type"], item["issue_title"], item["priority"])
            counts[key] = counts.get(key, 0) + 1
        return [
            {
                "issue_type": issue_type,
                "issue_title": issue_title,
                "priority": priority,
                "count": count,
            }
            for (issue_type, issue_title, priority), count in sorted(
                counts.items(),
                key=lambda item: (item[0][2], -item[1], item[0][0]),
            )
        ]

    def get_prediction_issue_filter_options(
        self,
        rally_id: Optional[str] = None,
        comparison_status: Optional[str] = None,
        only_flag: Optional[str] = None,
        high_error_pct: float = ACCEPTED_ERROR_PCT,
    ) -> Dict[str, List[str]]:
        breakdown = self.get_prediction_issue_breakdown(
            rally_id=rally_id,
            comparison_status=comparison_status,
            only_flag=only_flag,
            high_error_pct=high_error_pct,
        )
        priorities = sorted({item["priority"] for item in breakdown})
        issue_types = sorted({item["issue_type"] for item in breakdown})
        return {"priorities": priorities, "issue_types": issue_types}
