"""
Explanation Generator for Rally ETA Predictions.

Integrates:
- Baseline prediction components
- Geometric correction model
- SHAP explanations

Produces comprehensive, human-readable explanations for
each prediction.
"""
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import json

from src.ml.geometric_correction_model import GeometricCorrectionModel, ModelWithFallback
from src.ml.feature_engineering import FeatureEngineer
from src.ml.shap_explainer import SHAPExplainer, PredictionExplanation

logger = logging.getLogger(__name__)


@dataclass
class PredictionBreakdown:
    """Complete breakdown of a prediction."""
    # Driver info
    driver_id: str
    driver_name: str
    stage_id: str
    car_class: str

    # Prediction components
    baseline_ratio: float
    baseline_time: float  # seconds

    momentum_factor: float
    momentum_adjusted_ratio: float

    surface_adjustment: float
    surface_adjusted_ratio: float

    geometric_correction: float
    geometric_mode: str  # 'geometric' or 'fallback'

    # Final prediction
    final_ratio: float
    final_time: float  # seconds

    # Confidence
    confidence_level: str
    confidence_score: float

    # Explanation
    shap_explanation: Optional[PredictionExplanation] = None

    # Metadata
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class StageExplanationReport:
    """Complete explanation report for a stage prediction."""
    driver_id: str
    driver_name: str
    stage_id: str
    stage_name: str

    # Summary
    predicted_time_seconds: float
    predicted_time_formatted: str
    confidence: str

    # Breakdown
    breakdown: PredictionBreakdown

    # Text explanation
    summary_text: str
    detailed_text: str

    # For UI/visualization
    visualization_data: Dict


class ExplanationGenerator:
    """
    Generates comprehensive explanations for predictions.

    Combines all prediction components and SHAP analysis
    into human-readable reports.
    """

    def __init__(self, db_path: str, model_path: str = None):
        """
        Initialize generator.

        Args:
            db_path: Path to database
            model_path: Path to trained model (optional)
        """
        self.db_path = db_path
        self.feature_engineer = FeatureEngineer(db_path)

        # Load model if provided
        self.model = None
        self.shap_explainer = None

        if model_path:
            try:
                self.model = GeometricCorrectionModel()
                self.model.load(model_path)
                self.shap_explainer = SHAPExplainer(self.model)
                logger.info(f"Model loaded from {model_path}")
            except Exception as e:
                logger.warning(f"Could not load model: {e}")

        self.model_wrapper = ModelWithFallback(self.model)

    def generate_explanation(
        self,
        driver_id: str,
        driver_name: str,
        stage_id: str,
        stage_name: str,
        class_best_time: float,
        baseline_ratio: float,
        momentum_factor: float = 1.0,
        surface_adjustment: float = 1.0,
        surface: str = 'gravel',
        normalized_class: str = 'Rally2',
        include_shap: bool = True
    ) -> StageExplanationReport:
        """
        Generate complete explanation for a prediction.

        Args:
            driver_id: Driver identifier
            driver_name: Driver display name
            stage_id: Stage identifier
            stage_name: Stage display name
            class_best_time: Best time in driver's class (seconds)
            baseline_ratio: Historical baseline ratio
            momentum_factor: Rally momentum factor
            surface_adjustment: Surface performance adjustment
            surface: Stage surface type
            normalized_class: Car class
            include_shap: Whether to include SHAP analysis

        Returns:
            Complete explanation report
        """
        # Step 1: Create features for geometric correction
        features = self.feature_engineer.create_features_for_prediction(
            driver_id=driver_id,
            stage_id=stage_id,
            baseline_ratio=baseline_ratio,
            momentum_factor=momentum_factor,
            surface_adjustment=surface_adjustment,
            surface=surface,
            normalized_class=normalized_class
        )

        # Step 2: Get geometric correction
        if features:
            geometric_correction, geo_mode = self.model_wrapper.predict(features)
        else:
            geometric_correction = 1.0
            geo_mode = 'fallback'

        # Step 3: Calculate prediction steps
        momentum_adjusted_ratio = baseline_ratio * momentum_factor
        surface_adjusted_ratio = momentum_adjusted_ratio * surface_adjustment
        final_ratio = surface_adjusted_ratio * geometric_correction

        # Times
        baseline_time = baseline_ratio * class_best_time
        final_time = final_ratio * class_best_time

        # Step 4: Get SHAP explanation if available
        shap_explanation = None
        if include_shap and features and self.shap_explainer:
            try:
                shap_explanation = self.shap_explainer.explain(features)
            except Exception as e:
                logger.warning(f"SHAP explanation failed: {e}")

        # Step 5: Calculate confidence
        confidence_level, confidence_score = self._calculate_confidence(
            features=features,
            geo_mode=geo_mode,
            baseline_ratio=baseline_ratio
        )

        # Step 6: Create breakdown
        breakdown = PredictionBreakdown(
            driver_id=driver_id,
            driver_name=driver_name,
            stage_id=stage_id,
            car_class=normalized_class,
            baseline_ratio=baseline_ratio,
            baseline_time=baseline_time,
            momentum_factor=momentum_factor,
            momentum_adjusted_ratio=momentum_adjusted_ratio,
            surface_adjustment=surface_adjustment,
            surface_adjusted_ratio=surface_adjusted_ratio,
            geometric_correction=geometric_correction,
            geometric_mode=geo_mode,
            final_ratio=final_ratio,
            final_time=final_time,
            confidence_level=confidence_level,
            confidence_score=confidence_score,
            shap_explanation=shap_explanation
        )

        # Step 7: Generate text explanations
        summary_text = self._generate_summary(breakdown, stage_name)
        detailed_text = self._generate_detailed_explanation(breakdown, stage_name, features)

        # Step 8: Create visualization data
        viz_data = self._create_visualization_data(breakdown, features)

        return StageExplanationReport(
            driver_id=driver_id,
            driver_name=driver_name,
            stage_id=stage_id,
            stage_name=stage_name,
            predicted_time_seconds=final_time,
            predicted_time_formatted=self._format_time(final_time),
            confidence=confidence_level,
            breakdown=breakdown,
            summary_text=summary_text,
            detailed_text=detailed_text,
            visualization_data=viz_data
        )

    def _calculate_confidence(
        self,
        features: Optional[Dict],
        geo_mode: str,
        baseline_ratio: float
    ) -> Tuple[str, float]:
        """Calculate prediction confidence."""
        score = 1.0

        # Penalty for no geometry
        if geo_mode == 'fallback':
            score -= 0.3

        # Penalty for no features at all
        if not features:
            score -= 0.2
        elif features.get('driver_profile_confidence', 0) < 0.5:
            score -= 0.15

        # Penalty for extreme baseline
        if baseline_ratio > 1.15 or baseline_ratio < 0.95:
            score -= 0.1

        score = max(0.1, min(1.0, score))

        if score >= 0.8:
            level = 'HIGH'
        elif score >= 0.6:
            level = 'MEDIUM'
        elif score >= 0.4:
            level = 'LOW'
        else:
            level = 'VERY_LOW'

        return level, score

    def _generate_summary(self, breakdown: PredictionBreakdown, stage_name: str) -> str:
        """Generate one-line summary."""
        diff_pct = (breakdown.final_ratio - 1) * 100

        if abs(diff_pct) < 1:
            speed_desc = "sınıf en iyisiyle benzer"
        elif diff_pct > 0:
            speed_desc = f"sınıf en iyisinden %{diff_pct:.1f} yavaş"
        else:
            speed_desc = f"sınıf en iyisinden %{abs(diff_pct):.1f} hızlı"

        return (
            f"{breakdown.driver_name} - {stage_name}: "
            f"Tahmini {self._format_time(breakdown.final_time)} "
            f"({speed_desc}) - Güven: {breakdown.confidence_level}"
        )

    def _generate_detailed_explanation(
        self,
        breakdown: PredictionBreakdown,
        stage_name: str,
        features: Optional[Dict]
    ) -> str:
        """Generate detailed multi-line explanation."""
        lines = []

        lines.append("=" * 60)
        lines.append(f"TAHMİN RAPORU: {breakdown.driver_name}")
        lines.append("=" * 60)
        lines.append("")

        # Basic info
        lines.append(f"Etap: {stage_name}")
        lines.append(f"Sınıf: {breakdown.car_class}")
        lines.append(f"Tarih: {breakdown.generated_at[:10]}")
        lines.append("")

        # Prediction result
        lines.append("-" * 40)
        lines.append("TAHMİN SONUCU")
        lines.append("-" * 40)
        lines.append(f"Tahmini Süre: {self._format_time(breakdown.final_time)}")
        lines.append(f"Final Ratio: {breakdown.final_ratio:.4f}")
        lines.append(f"Güven Seviyesi: {breakdown.confidence_level} ({breakdown.confidence_score:.0%})")
        lines.append("")

        # Breakdown
        lines.append("-" * 40)
        lines.append("TAHMİN ADIMLARI")
        lines.append("-" * 40)

        lines.append(f"1. Baseline Ratio: {breakdown.baseline_ratio:.4f}")
        lines.append(f"   (Tarihi ortalama performans)")
        lines.append(f"   -> Baseline süre: {self._format_time(breakdown.baseline_time)}")
        lines.append("")

        mom_effect = (breakdown.momentum_factor - 1) * 100
        mom_dir = "artış" if mom_effect > 0 else "azalış"
        lines.append(f"2. Rally Momentum: {breakdown.momentum_factor:.4f}")
        lines.append(f"   ({abs(mom_effect):.1f}% {mom_dir} - ralliye özgü form)")
        lines.append(f"   -> Adjusted: {breakdown.momentum_adjusted_ratio:.4f}")
        lines.append("")

        surf_effect = (breakdown.surface_adjustment - 1) * 100
        surf_dir = "artış" if surf_effect > 0 else "azalış"
        lines.append(f"3. Zemin Düzeltmesi: {breakdown.surface_adjustment:.4f}")
        lines.append(f"   ({abs(surf_effect):.1f}% {surf_dir} - zemin performansı)")
        lines.append(f"   -> Adjusted: {breakdown.surface_adjusted_ratio:.4f}")
        lines.append("")

        geo_effect = (breakdown.geometric_correction - 1) * 100
        geo_dir = "artış" if geo_effect > 0 else "azalış"
        lines.append(f"4. Geometrik Düzeltme: {breakdown.geometric_correction:.4f}")
        lines.append(f"   ({abs(geo_effect):.1f}% {geo_dir} - etap geometrisi)")
        lines.append(f"   Mode: {breakdown.geometric_mode}")
        lines.append(f"   -> Final Ratio: {breakdown.final_ratio:.4f}")
        lines.append("")

        # Stage geometry if available
        if features:
            lines.append("-" * 40)
            lines.append("ETAP GEOMETRİSİ")
            lines.append("-" * 40)

            if features.get('distance_km'):
                lines.append(f"Mesafe: {features['distance_km']:.2f} km")
            if features.get('hairpin_count'):
                lines.append(f"Viraj Sayısı: {features['hairpin_count']:.0f}")
            if features.get('hairpin_density'):
                lines.append(f"Viraj Yoğunluğu: {features['hairpin_density']:.2f} per km")
            if features.get('total_ascent'):
                lines.append(f"Toplam Tırmanış: {features['total_ascent']:.0f} m")
            if features.get('max_grade'):
                lines.append(f"Maks Eğim: %{features['max_grade']:.1f}")
            lines.append("")

        # SHAP explanation if available
        if breakdown.shap_explanation:
            lines.append("-" * 40)
            lines.append("SHAP ANALİZİ")
            lines.append("-" * 40)
            lines.append(breakdown.shap_explanation.explanation_text)

        return "\n".join(lines)

    def _create_visualization_data(
        self,
        breakdown: PredictionBreakdown,
        features: Optional[Dict]
    ) -> Dict:
        """Create data for UI visualization."""
        data = {
            'prediction': {
                'time_seconds': breakdown.final_time,
                'time_formatted': self._format_time(breakdown.final_time),
                'ratio': breakdown.final_ratio,
                'confidence': breakdown.confidence_level,
                'confidence_score': breakdown.confidence_score
            },
            'waterfall': {
                'steps': [
                    {
                        'name': 'Baseline',
                        'value': breakdown.baseline_ratio,
                        'cumulative': breakdown.baseline_ratio
                    },
                    {
                        'name': 'Momentum',
                        'value': breakdown.momentum_factor - 1,
                        'cumulative': breakdown.momentum_adjusted_ratio
                    },
                    {
                        'name': 'Zemin',
                        'value': breakdown.surface_adjustment - 1,
                        'cumulative': breakdown.surface_adjusted_ratio
                    },
                    {
                        'name': 'Geometri',
                        'value': breakdown.geometric_correction - 1,
                        'cumulative': breakdown.final_ratio
                    }
                ]
            },
            'factors': {
                'baseline': breakdown.baseline_ratio,
                'momentum': breakdown.momentum_factor,
                'surface': breakdown.surface_adjustment,
                'geometric': breakdown.geometric_correction
            }
        }

        # Add geometry data if available
        if features:
            data['geometry'] = {
                'distance_km': features.get('distance_km', 0),
                'hairpin_count': features.get('hairpin_count', 0),
                'hairpin_density': features.get('hairpin_density', 0),
                'total_ascent': features.get('total_ascent', 0),
                'max_grade': features.get('max_grade', 0),
                'avg_curvature': features.get('avg_curvature', 0)
            }

            data['driver_profile'] = {
                'hairpin_perf': features.get('driver_hairpin_perf', 1.0),
                'climb_perf': features.get('driver_climb_perf', 1.0),
                'curvature_sens': features.get('driver_curvature_sens', 1.0),
                'profile_confidence': features.get('driver_profile_confidence', 0)
            }

        # Add SHAP data if available
        if breakdown.shap_explanation:
            data['shap'] = {
                'base_value': breakdown.shap_explanation.base_value,
                'final_value': breakdown.shap_explanation.correction_factor,
                'top_positive': [
                    {
                        'feature': c.feature_name,
                        'value': c.feature_value,
                        'shap': c.shap_value,
                        'pct': c.contribution_pct
                    }
                    for c in breakdown.shap_explanation.top_positive
                ],
                'top_negative': [
                    {
                        'feature': c.feature_name,
                        'value': c.feature_value,
                        'shap': c.shap_value,
                        'pct': c.contribution_pct
                    }
                    for c in breakdown.shap_explanation.top_negative
                ]
            }

        return data

    def _format_time(self, seconds: float) -> str:
        """Format seconds as MM:SS.sss"""
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}:{secs:06.3f}"

    def to_json(self, report: StageExplanationReport) -> str:
        """Convert report to JSON string."""
        return json.dumps({
            'driver_id': report.driver_id,
            'driver_name': report.driver_name,
            'stage_id': report.stage_id,
            'stage_name': report.stage_name,
            'predicted_time_seconds': report.predicted_time_seconds,
            'predicted_time_formatted': report.predicted_time_formatted,
            'confidence': report.confidence,
            'breakdown': {
                'baseline_ratio': report.breakdown.baseline_ratio,
                'momentum_factor': report.breakdown.momentum_factor,
                'surface_adjustment': report.breakdown.surface_adjustment,
                'geometric_correction': report.breakdown.geometric_correction,
                'geometric_mode': report.breakdown.geometric_mode,
                'final_ratio': report.breakdown.final_ratio,
                'confidence_score': report.breakdown.confidence_score
            },
            'summary': report.summary_text,
            'visualization_data': report.visualization_data
        }, indent=2, ensure_ascii=False)


def main():
    """Test explanation generator."""
    import argparse
    from pathlib import Path
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent.parent))

    parser = argparse.ArgumentParser(description="Explanation Generator Test")
    parser.add_argument('--db-path', default='data/raw/rally_results.db',
                       help='Database path')
    parser.add_argument('--model-path', type=str,
                       help='Path to trained model')
    parser.add_argument('--driver-id', type=str,
                       help='Driver ID to test')
    parser.add_argument('--stage-id', type=str,
                       help='Stage ID to test')

    args = parser.parse_args()

    print("Initializing Explanation Generator...")
    generator = ExplanationGenerator(
        db_path=args.db_path,
        model_path=args.model_path
    )

    # Use provided IDs or defaults for testing
    driver_id = args.driver_id or 'test_driver'
    stage_id = args.stage_id or 'test_stage'

    print(f"\nGenerating explanation for {driver_id} / {stage_id}...")

    report = generator.generate_explanation(
        driver_id=driver_id,
        driver_name='Test Pilot',
        stage_id=stage_id,
        stage_name='SS1 - Test Etabı',
        class_best_time=300.0,  # 5 minutes
        baseline_ratio=1.05,
        momentum_factor=1.01,
        surface_adjustment=0.98,
        surface='gravel',
        normalized_class='Rally2',
        include_shap=args.model_path is not None
    )

    print("\n" + "=" * 60)
    print("GENERATED REPORT")
    print("=" * 60)
    print(f"\nSummary: {report.summary_text}")
    print(f"\nPredicted Time: {report.predicted_time_formatted}")
    print(f"Confidence: {report.confidence}")

    print("\n" + "-" * 40)
    print("DETAILED EXPLANATION")
    print("-" * 40)
    print(report.detailed_text)

    print("\n" + "-" * 40)
    print("JSON OUTPUT")
    print("-" * 40)
    print(generator.to_json(report))


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
