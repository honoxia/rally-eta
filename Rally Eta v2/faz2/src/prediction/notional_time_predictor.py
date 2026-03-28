"""
Notional Time Predictor - 3-Stage Prediction Orchestrator.

Combines:
- STAGE 1: Baseline Calculator (historical, momentum, surface)
- STAGE 2: Geometric Correction (LightGBM + SHAP)
- STAGE 3: Final Prediction + Confidence

For DNF pilot notional time calculation in red flag situations.
"""
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from src.baseline.baseline_predictor import BaselinePredictor
from src.data.class_best_calculator import ClassBestTimeCalculator
from src.data.stage_metadata_manager import StageMetadataManager
from src.ml.feature_engineering import FeatureEngineer
from src.ml.geometric_correction_model import GeometricCorrectionModel, ModelWithFallback
from src.ml.explanation_generator import ExplanationGenerator
from src.prediction.confidence_scorer import ConfidenceScorer, ConfidenceResult

logger = logging.getLogger(__name__)


@dataclass
class PredictionResult:
    """Complete prediction result with all components."""
    # Driver/Stage info
    driver_id: str
    driver_name: str
    stage_id: str
    stage_name: str
    normalized_class: str
    surface: str

    # Prediction results
    predicted_time_seconds: float
    predicted_time_str: str
    predicted_ratio: float

    # Class best reference
    class_best_time: float
    class_best_str: str
    class_best_driver: str

    # Component breakdown
    baseline_ratio: float
    momentum_factor: float
    surface_adjustment: float
    geometric_correction: float
    geometric_mode: str  # 'geometric' or 'fallback'

    # Confidence
    confidence: ConfidenceResult

    # Explanations
    summary_text: str
    detailed_text: str

    # Metadata
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())


class NotionalTimePredictor:
    """
    3-Stage Notional Time Predictor.

    STAGE 1: Baseline Calculator
    - Historical performance (weighted avg of last N stages)
    - Rally momentum (within-rally form)
    - Surface adjustment (gravel/asphalt preference)

    STAGE 2: Geometric Correction (optional, requires KML)
    - Stage geometry features (hairpins, climb, curvature)
    - Driver geometry profile (lifetime characteristics)
    - LightGBM correction factor

    STAGE 3: Final Prediction
    - Combine baseline * geometric correction
    - Calculate confidence score
    - Generate explanations
    """

    def __init__(
        self,
        db_path: str,
        model_path: Optional[str] = None
    ):
        """
        Initialize predictor.

        Args:
            db_path: Path to database
            model_path: Path to trained model (optional)
        """
        self.db_path = db_path

        # Stage 1 components
        self.baseline_predictor = BaselinePredictor(db_path)
        self.class_best_calc = ClassBestTimeCalculator(db_path)
        self.metadata_manager = StageMetadataManager(db_path)

        # Stage 2 components
        self.feature_engineer = FeatureEngineer(db_path)
        self.model = None
        self.model_wrapper = None
        self.explanation_generator = None

        if model_path and Path(model_path).with_suffix('.pkl').exists():
            try:
                self.model = GeometricCorrectionModel()
                self.model.load(model_path)
                self.model_wrapper = ModelWithFallback(self.model)
                self.explanation_generator = ExplanationGenerator(db_path, model_path)
                logger.info(f"Geometric correction model loaded from {model_path}")
            except Exception as e:
                logger.warning(f"Could not load model: {e}")
                self.model_wrapper = ModelWithFallback(None)
        else:
            self.model_wrapper = ModelWithFallback(None)

        # Stage 3 components
        self.confidence_scorer = ConfidenceScorer()

    def predict(
        self,
        driver_id: str,
        driver_name: str,
        rally_id: str,
        stage_id: str,
        stage_name: str,
        current_stage_number: int,
        normalized_class: str,
        surface: Optional[str] = None
    ) -> PredictionResult:
        """
        Generate complete prediction for a driver/stage.

        Args:
            driver_id: Driver identifier
            driver_name: Driver display name
            rally_id: Rally identifier
            stage_id: Stage identifier
            stage_name: Stage display name
            current_stage_number: Stage number in rally
            normalized_class: Normalized car class
            surface: Stage surface (auto-detected if None)

        Returns:
            Complete PredictionResult
        """
        logger.info(f"Predicting for {driver_name} / {stage_name}")

        # Get stage metadata for surface
        stage_meta = self._resolve_stage_metadata(
            stage_id=stage_id,
            rally_id=rally_id,
            current_stage_number=current_stage_number
        )
        resolved_stage_id = stage_meta.get('stage_id', stage_id) if stage_meta else stage_id
        if not surface:
            surface = stage_meta.get('surface', 'gravel') if stage_meta else 'gravel'

        # ===========================================
        # STAGE 1: Baseline Calculation
        # ===========================================
        baseline_result = {'data_points': 0}
        try:
            baseline_result = self.baseline_predictor.predict(
                driver_id=driver_id,
                rally_id=rally_id,
                stage_id=resolved_stage_id,
                current_stage=current_stage_number,
                surface=surface,
                normalized_class=normalized_class
            )

            baseline_ratio = baseline_result['baseline_ratio']
            momentum_factor = baseline_result['components']['momentum_factor']
            surface_adjustment = baseline_result['components']['surface_adjustment']
            baseline_explanation = baseline_result['explanation']

        except Exception as e:
            logger.error(f"Baseline calculation failed: {e}")
            # Fallback to default
            baseline_ratio = 1.05
            momentum_factor = 1.0
            surface_adjustment = 1.0
            baseline_explanation = f"Baseline hesaplanamadi: {e}"

        # ===========================================
        # STAGE 2: Geometric Correction
        # ===========================================
        geometric_correction = 1.0
        geometric_mode = 'fallback'
        geometric_explanation = ""

        if stage_meta and stage_meta.get('hairpin_density') is not None:
            # Create features for geometric correction
            features = self.feature_engineer.create_features_for_prediction(
                driver_id=driver_id,
                stage_id=resolved_stage_id,
                baseline_ratio=baseline_ratio,
                momentum_factor=momentum_factor,
                surface_adjustment=surface_adjustment,
                surface=surface,
                normalized_class=normalized_class
            )

            if features:
                try:
                    geometric_correction, geometric_mode = self.model_wrapper.predict(
                        features, require_geometry=False
                    )

                    # Generate SHAP explanation if model available
                    if geometric_mode == 'geometric' and self.explanation_generator:
                        shap_explanation = self._get_shap_explanation(features)
                        geometric_explanation = shap_explanation
                    else:
                        geometric_explanation = self._generate_fallback_geo_explanation()

                except Exception as e:
                    logger.warning(f"Geometric correction failed: {e}")
                    geometric_correction = 1.0
                    geometric_mode = 'fallback'
                    geometric_explanation = f"Geometrik duzeltme basarisiz: {e}"
            else:
                geometric_explanation = "Feature olusturulamadi"
        else:
            geometric_explanation = "KML verisi yok - geometrik duzeltme uygulanmadi"

        # ===========================================
        # STAGE 3: Final Prediction + Confidence
        # ===========================================

        # Calculate final ratio
        final_ratio = baseline_ratio * geometric_correction

        # Get class best time
        class_best = self.class_best_calc.get_class_best(
            rally_id=rally_id,
            stage_id=resolved_stage_id,
            normalized_class=normalized_class
        )

        if not class_best:
            raise ValueError(
                f"No class best found for {normalized_class} in {rally_id}/{stage_id}"
            )

        class_best_time = class_best['class_best_time']
        class_best_driver = class_best['class_best_driver']

        # Calculate predicted time
        predicted_time_seconds = final_ratio * class_best_time
        predicted_time_str = self._format_time(predicted_time_seconds)
        class_best_str = self._format_time(class_best_time)

        # Calculate confidence
        driver_profile_confidence = self._get_driver_profile_confidence(driver_id)

        confidence = self.confidence_scorer.calculate(
            driver_history_count=baseline_result.get('data_points', 0) if 'data_points' in baseline_result else 10,
            surface_experience=self._get_surface_experience(driver_id, surface),
            geometry_data_available=stage_meta is not None,
            driver_profile_confidence=driver_profile_confidence,
            rally_stages_count=current_stage_number - 1,
            baseline_ratio=baseline_ratio,
            geometric_mode=geometric_mode
        )

        # Generate explanations
        summary_text = self._generate_summary(
            driver_name=driver_name,
            stage_name=stage_name,
            predicted_time_str=predicted_time_str,
            final_ratio=final_ratio,
            confidence=confidence
        )

        detailed_text = self._generate_detailed_explanation(
            driver_name=driver_name,
            stage_name=stage_name,
            baseline_explanation=baseline_explanation,
            geometric_explanation=geometric_explanation,
            baseline_ratio=baseline_ratio,
            momentum_factor=momentum_factor,
            surface_adjustment=surface_adjustment,
            geometric_correction=geometric_correction,
            geometric_mode=geometric_mode,
            final_ratio=final_ratio,
            predicted_time_str=predicted_time_str,
            class_best_str=class_best_str,
            class_best_driver=class_best_driver,
            class_best_time=class_best_time,
            confidence=confidence
        )

        return PredictionResult(
            driver_id=driver_id,
            driver_name=driver_name,
            stage_id=resolved_stage_id,
            stage_name=stage_name,
            normalized_class=normalized_class,
            surface=surface,
            predicted_time_seconds=predicted_time_seconds,
            predicted_time_str=predicted_time_str,
            predicted_ratio=final_ratio,
            class_best_time=class_best_time,
            class_best_str=class_best_str,
            class_best_driver=class_best_driver,
            baseline_ratio=baseline_ratio,
            momentum_factor=momentum_factor,
            surface_adjustment=surface_adjustment,
            geometric_correction=geometric_correction,
            geometric_mode=geometric_mode,
            confidence=confidence,
            summary_text=summary_text,
            detailed_text=detailed_text
        )

    def predict_batch(
        self,
        drivers: List[Dict],
        rally_id: str,
        stage_id: str,
        stage_name: str,
        current_stage_number: int
    ) -> List[PredictionResult]:
        """
        Predict for multiple drivers.

        Args:
            drivers: List of driver dicts with id, name, class
            rally_id: Rally identifier
            stage_id: Stage identifier
            stage_name: Stage name
            current_stage_number: Current stage number

        Returns:
            List of PredictionResults
        """
        results = []

        for driver in drivers:
            try:
                result = self.predict(
                    driver_id=driver['driver_id'],
                    driver_name=driver['driver_name'],
                    rally_id=rally_id,
                    stage_id=stage_id,
                    stage_name=stage_name,
                    current_stage_number=current_stage_number,
                    normalized_class=driver['normalized_class'],
                    surface=driver.get('surface')
                )
                results.append(result)

            except Exception as e:
                logger.error(f"Prediction failed for {driver['driver_name']}: {e}")

        return results

    def _format_time(self, seconds: float) -> str:
        """Format seconds as MM:SS.sss"""
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}:{secs:06.3f}"

    def _resolve_stage_metadata(
        self,
        stage_id: str,
        rally_id: Optional[str] = None,
        current_stage_number: Optional[int] = None
    ) -> Optional[Dict]:
        """Resolve stage metadata across plain and synthetic stage id formats."""
        candidates = []

        def add_candidate(value: Optional[str]):
            if value and value not in candidates:
                candidates.append(value)

        add_candidate(stage_id)

        stage_number = self._extract_stage_number(stage_id)
        if current_stage_number is not None:
            add_candidate(f"SS{current_stage_number}")
            add_candidate(f"ss{current_stage_number}")
            if rally_id:
                add_candidate(f"{rally_id}_ss{current_stage_number}")

        if stage_number is not None:
            add_candidate(f"SS{stage_number}")
            add_candidate(f"ss{stage_number}")
            if rally_id:
                add_candidate(f"{rally_id}_ss{stage_number}")

        for candidate in candidates:
            stage_meta = self.metadata_manager.get_stage(candidate)
            if stage_meta:
                return stage_meta

        return None

    def _extract_stage_number(self, stage_id: str) -> Optional[int]:
        """Extract stage number from ids like 166_ss1, SS1, ss01, or 3."""
        import re

        stage_str = str(stage_id)
        patterns = [
            r'(?i)_ss0*(\d+)\b',
            r'(?i)\bss\s*0*(\d+)\b',
            r'(\d+)$',
        ]

        for pattern in patterns:
            match = re.search(pattern, stage_str)
            if match:
                try:
                    return int(match.group(1))
                except ValueError:
                    return None

        return None

    def _get_driver_profile_confidence(self, driver_id: str) -> float:
        """Get driver geometry profile confidence."""
        try:
            profile = self.feature_engineer._get_driver_profile(driver_id)
            if profile:
                confidence_map = {
                    'HIGH': 0.9,
                    'MEDIUM': 0.6,
                    'LOW': 0.3,
                    'INSUFFICIENT': 0.1
                }
                return confidence_map.get(profile.confidence, 0.5)
        except:
            pass
        return 0.5

    def _get_surface_experience(self, driver_id: str, surface: str) -> int:
        """Get number of stages on surface for driver."""
        import sqlite3
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM stage_results
                WHERE COALESCE(driver_id, driver_name) = ?
                AND LOWER(surface) = LOWER(?)
                AND time_seconds > 0
            """, [driver_id, surface])
            count = cursor.fetchone()[0]
            conn.close()
            return count
        except:
            return 0

    def _get_shap_explanation(self, features: Dict) -> str:
        """Get SHAP explanation for features."""
        try:
            from src.ml.shap_explainer import SHAPExplainer
            if self.model:
                explainer = SHAPExplainer(self.model)
                explanation = explainer.explain(features)
                return explanation.explanation_text
        except Exception as e:
            logger.warning(f"SHAP explanation failed: {e}")
        return "SHAP aciklamasi alinamadi"

    def _generate_fallback_geo_explanation(self) -> str:
        """Generate explanation when using fallback mode."""
        return """
GEOMETRIK DUZELTME
==================================================
Mod: Fallback (baseline-only)
Geometrik duzeltme: x1.000

Model yuklu degil veya etap icin KML verisi yok.
Tahmin sadece baseline ratio kullanilarak yapildi.
"""

    def _generate_summary(
        self,
        driver_name: str,
        stage_name: str,
        predicted_time_str: str,
        final_ratio: float,
        confidence: ConfidenceResult
    ) -> str:
        """Generate one-line summary."""
        diff_pct = (final_ratio - 1) * 100

        if abs(diff_pct) < 0.5:
            speed_desc = "sinif lideriyle benzer"
        elif diff_pct > 0:
            speed_desc = f"sinif liderinden %{diff_pct:.1f} yavas"
        else:
            speed_desc = f"sinif liderinden %{abs(diff_pct):.1f} hizli"

        return (
            f"{driver_name} - {stage_name}: "
            f"Tahmini {predicted_time_str} "
            f"({speed_desc}) - Guven: {confidence.level} {confidence.emoji}"
        )

    def _generate_detailed_explanation(
        self,
        driver_name: str,
        stage_name: str,
        baseline_explanation: str,
        geometric_explanation: str,
        baseline_ratio: float,
        momentum_factor: float,
        surface_adjustment: float,
        geometric_correction: float,
        geometric_mode: str,
        final_ratio: float,
        predicted_time_str: str,
        class_best_str: str,
        class_best_driver: str,
        class_best_time: float,
        confidence: ConfidenceResult
    ) -> str:
        """Generate detailed multi-line explanation."""
        lines = []

        lines.append("=" * 60)
        lines.append(f"NOTIONAL TIME TAHMINI: {driver_name.upper()}")
        lines.append(f"Etap: {stage_name}")
        lines.append("=" * 60)
        lines.append("")

        # Stage 1: Baseline
        lines.append("-" * 40)
        lines.append("STAGE 1: BASELINE HESAPLAMA")
        lines.append("-" * 40)
        lines.append(baseline_explanation if baseline_explanation else "Baseline bilgisi yok")
        lines.append("")

        # Stage 2: Geometric
        lines.append("-" * 40)
        lines.append(f"STAGE 2: GEOMETRIK DUZELTME ({geometric_mode.upper()})")
        lines.append("-" * 40)
        lines.append(geometric_explanation if geometric_explanation else "Geometrik bilgi yok")
        lines.append("")

        # Stage 3: Final
        lines.append("=" * 60)
        lines.append("STAGE 3: FINAL TAHMIN")
        lines.append("=" * 60)
        lines.append("")

        lines.append("Hesaplama:")
        lines.append(f"  Baseline ratio:        {baseline_ratio:.4f}")
        lines.append(f"    (Momentum:           {momentum_factor:.4f})")
        lines.append(f"    (Surface adj:        {surface_adjustment:.4f})")
        lines.append(f"  x Geometrik duzeltme:  {geometric_correction:.4f}")
        lines.append(f"  ----------------------------")
        lines.append(f"  = Final ratio:         {final_ratio:.4f}")
        lines.append("")

        lines.append("Zaman Tahmini:")
        lines.append(f"  Sinif lideri ({class_best_driver}): {class_best_str}")
        lines.append(f"  {driver_name}: {predicted_time_str}")

        diff_seconds = (final_ratio - 1) * class_best_time
        lines.append(f"  Fark: {diff_seconds:+.1f} saniye")
        lines.append("")

        # Confidence
        lines.append("-" * 40)
        lines.append(f"GUVENILIRLIK: {confidence.level} ({confidence.score}/100) {confidence.emoji}")
        lines.append("-" * 40)
        for reason in confidence.reasons:
            if reason:
                lines.append(f"  - {reason}")
        lines.append("")

        lines.append("=" * 60)

        return "\n".join(lines)

    def predict_for_manual_input(
        self,
        driver_id: str,
        driver_name: str,
        stage_length_km: float,
        surface: str,
        day_or_night: str,
        stage_number: int,
        rally_name: str
    ) -> dict:
        """
        Predict time for manual input (for UI compatibility).

        This method provides backward compatibility with the v1 predictor interface.
        It estimates reference times when rally/stage data isn't available.

        Args:
            driver_id: Driver ID
            driver_name: Driver name
            stage_length_km: Stage length in km
            surface: Surface type (gravel/asphalt)
            day_or_night: Time of day (day/night)
            stage_number: Stage number
            rally_name: Rally name

        Returns:
            Dictionary with prediction details matching v1 interface
        """
        import sqlite3

        def _mean(values):
            return sum(values) / len(values) if values else 0.0

        def _clip(value, minimum, maximum):
            return max(minimum, min(value, maximum))

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Get driver's car class and historical data
        # stage_id olustur: rally_id || '_ss' || stage_number
        query = """
            SELECT car_class, COALESCE(normalized_class, car_class) as normalized_class, time_seconds,
                   (rally_id || '_ss' || stage_number) as stage_id,
                   rally_id, stage_number, surface
            FROM stage_results
            WHERE COALESCE(driver_id, driver_name) = ?
            AND time_seconds > 0
            ORDER BY CAST(rally_id AS INTEGER) DESC, stage_number DESC
            LIMIT 15
        """
        cursor.execute(query, [driver_id])
        driver_history = [dict(row) for row in cursor.fetchall()]

        # Try clean_stage_results if no results
        if len(driver_history) == 0:
            try:
                fallback_query = query.replace('stage_results', 'clean_stage_results')
                cursor.execute(fallback_query, [driver_id])
                driver_history = [dict(row) for row in cursor.fetchall()]
            except sqlite3.OperationalError:
                driver_history = []

        if len(driver_history) == 0:
            conn.close()
            raise ValueError(f"No historical data found for driver {driver_name}")

        car_class = driver_history[0]['car_class']
        normalized_class = driver_history[0].get('normalized_class', car_class)

        # Calculate driver's historical ratios
        driver_ratios = []
        surface_ratios = []
        for row in driver_history:
            stage_id = row['stage_id']

            # Get class best time for this stage
            # stage_id formatı: rally_id_ss{stage_number}
            parts = stage_id.split('_ss')
            if len(parts) == 2:
                rally_id_part, stage_num_part = parts
            else:
                rally_id_part = row['rally_id']
                stage_num_part = row['stage_number']

            class_best_query = """
                SELECT MIN(time_seconds) as class_best
                FROM stage_results
                WHERE rally_id = ? AND stage_number = ? AND COALESCE(normalized_class, car_class) = ? AND time_seconds > 0
            """
            cursor.execute(class_best_query, [str(rally_id_part), int(stage_num_part), normalized_class])
            class_best_row = cursor.fetchone()

            if class_best_row and class_best_row['class_best'] is not None:
                class_best = class_best_row['class_best']
                if class_best > 0:
                    ratio = row['time_seconds'] / class_best
                    driver_ratios.append(ratio)

                    # Track surface-specific ratios
                    if str(row.get('surface', '')).lower() == surface.lower():
                        surface_ratios.append(ratio)

        conn.close()

        if len(driver_ratios) == 0:
            raise ValueError(f"Cannot calculate performance ratio for driver {driver_name}")

        # Calculate momentum (recent vs historical)
        if len(driver_ratios) >= 10:
            recent_avg_ratio = _mean(driver_ratios[:5])
            historical_avg_ratio = _mean(driver_ratios[5:10])
            momentum_delta = (historical_avg_ratio - recent_avg_ratio) * 100

            if momentum_delta > 2.0:
                momentum = "Hizlaniyor"
                momentum_factor = 0.99
            elif momentum_delta < -2.0:
                momentum = "Yavasliyor"
                momentum_factor = 1.01
            else:
                momentum = "Stabil"
                momentum_factor = 1.0
        else:
            recent_avg_ratio = _mean(driver_ratios)
            historical_avg_ratio = recent_avg_ratio
            momentum_delta = 0.0
            momentum = "Yetersiz veri"
            momentum_factor = 1.0

        # Surface adjustment
        if len(surface_ratios) >= 3:
            surface_avg = _mean(surface_ratios)
            general_avg = _mean(driver_ratios)
            surface_adjustment = surface_avg / general_avg
        else:
            surface_adjustment = 1.0

        # Estimate reference time (class best for this stage type)
        if surface == 'asphalt':
            base_speed = 100  # km/h
        else:
            base_speed = 85  # km/h

        # Class factors (slower classes take longer)
        class_factors = {
            'WRC': 1.0, 'Rally1': 1.0,
            'Rally2': 1.08, 'R5': 1.08, 'R4': 1.08,
            'Rally3': 1.15, 'R2': 1.15,
            'N4': 1.12, 'NR4': 1.12
        }

        factor = class_factors.get(normalized_class, class_factors.get(car_class, 1.10))
        adjusted_speed = base_speed / factor

        reference_time = (stage_length_km / adjusted_speed) * 3600

        # Calculate final ratio using baseline components
        baseline_ratio = recent_avg_ratio * momentum_factor * surface_adjustment

        # Apply constraints
        predicted_ratio = _clip(baseline_ratio, 1.0, 1.5)

        # Calculate predicted time
        predicted_time = predicted_ratio * reference_time

        # Calculate speed
        predicted_speed_kmh = round((stage_length_km / predicted_time) * 3600)

        # Format times
        predicted_time_str = self._format_time(predicted_time)
        reference_time_str = self._format_time(reference_time)

        # Calculate confidence
        confidence_score = min(100, 30 + len(driver_ratios) * 4 + len(surface_ratios) * 2)
        if confidence_score >= 75:
            confidence_level = "HIGH"
            confidence_emoji = "🟢"
        elif confidence_score >= 55:
            confidence_level = "MEDIUM"
            confidence_emoji = "🟡"
        else:
            confidence_level = "LOW"
            confidence_emoji = "🔴"

        # Build explanation
        explanation = f"""
**Tahmin Detaylari:**

- Pilot: {driver_name} ({car_class})
- Son performans ortalamasi: {recent_avg_ratio:.3f}x sinif lideri
- Tahmin edilen oran: {predicted_ratio:.3f}x
- Referans zaman (sinif lideri tahmini): {reference_time_str}
- Tahmini zaman: {predicted_time_str} ({predicted_speed_kmh} km/h)

**Momentum Analizi:**
- Son 5 yaris ortalamasi: {recent_avg_ratio:.3f}
- Onceki 5 yaris ortalamasi: {historical_avg_ratio:.3f}
- Trend: {momentum} ({momentum_delta:+.1f}%)

**Guvenilirlik:** {confidence_level} ({confidence_score}/100) {confidence_emoji}
- Veri sayisi: {len(driver_ratios)} etap
- Yuzey deneyimi: {len(surface_ratios)} etap ({surface})
"""

        return {
            'driver_name': driver_name,
            'car_class': car_class,
            'stage_length_km': stage_length_km,
            'surface': surface,
            'day_or_night': day_or_night,
            'predicted_time_seconds': predicted_time,
            'predicted_time_str': predicted_time_str,
            'predicted_speed_kmh': predicted_speed_kmh,
            'predicted_ratio': predicted_ratio,
            'reference_time_seconds': reference_time,
            'reference_time_str': reference_time_str,
            'momentum': momentum,
            'momentum_delta': momentum_delta,
            'recent_avg_ratio': recent_avg_ratio,
            'historical_avg_ratio': historical_avg_ratio,
            'confidence_level': confidence_level,
            'confidence_score': confidence_score,
            'confidence_emoji': confidence_emoji,
            'explanation': explanation
        }


def main():
    """Test notional time predictor."""
    import argparse

    parser = argparse.ArgumentParser(description="Notional Time Predictor")
    parser.add_argument('--db-path', default='data/raw/rally_results.db',
                       help='Database path')
    parser.add_argument('--model-path', type=str,
                       help='Path to trained model')
    parser.add_argument('--driver-id', required=True,
                       help='Driver ID')
    parser.add_argument('--driver-name', required=True,
                       help='Driver name')
    parser.add_argument('--rally-id', required=True,
                       help='Rally ID')
    parser.add_argument('--stage-id', required=True,
                       help='Stage ID')
    parser.add_argument('--stage-name', default='Test Stage',
                       help='Stage name')
    parser.add_argument('--stage-number', type=int, default=3,
                       help='Stage number')
    parser.add_argument('--car-class', default='Rally2',
                       help='Car class')

    args = parser.parse_args()

    print("Initializing Notional Time Predictor...")
    predictor = NotionalTimePredictor(
        db_path=args.db_path,
        model_path=args.model_path
    )

    print(f"\nPredicting for {args.driver_name}...")
    result = predictor.predict(
        driver_id=args.driver_id,
        driver_name=args.driver_name,
        rally_id=args.rally_id,
        stage_id=args.stage_id,
        stage_name=args.stage_name,
        current_stage_number=args.stage_number,
        normalized_class=args.car_class
    )

    print("\n" + "=" * 60)
    print("PREDICTION RESULT")
    print("=" * 60)
    print(f"\nSummary: {result.summary_text}")
    print(f"\nPredicted Time: {result.predicted_time_str}")
    print(f"Final Ratio: {result.predicted_ratio:.4f}")
    print(f"Confidence: {result.confidence.level} ({result.confidence.score}/100)")

    print("\n" + "-" * 60)
    print("DETAILED EXPLANATION")
    print("-" * 60)
    print(result.detailed_text)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
