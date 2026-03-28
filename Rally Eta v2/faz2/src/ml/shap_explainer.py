from __future__ import annotations

"""
SHAP-based explanation for geometric correction predictions.

Provides:
- Feature contribution analysis
- Human-readable explanations
- Waterfall visualization data
"""
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

try:
    import numpy as np
except ImportError:
    np = None

try:
    import pandas as pd
except ImportError:
    pd = None

try:
    import shap
    SHAP_AVAILABLE = True
except ImportError:
    SHAP_AVAILABLE = False
    shap = None

from src.ml.geometric_correction_model import GeometricCorrectionModel

logger = logging.getLogger(__name__)


def _require_shap_dependencies():
    """Raise a clear error when optional explanation dependencies are missing."""
    missing = []
    if np is None:
        missing.append('numpy')
    if pd is None:
        missing.append('pandas')
    if not SHAP_AVAILABLE:
        missing.append('shap')

    if missing:
        raise ImportError(
            "SHAPExplainer requires optional dependencies: " + ", ".join(missing)
        )


@dataclass
class FeatureContribution:
    """Single feature's contribution to prediction."""
    feature_name: str
    feature_value: float
    shap_value: float
    contribution_pct: float
    direction: str  # 'increases' or 'decreases'


@dataclass
class PredictionExplanation:
    """Complete explanation for a prediction."""
    correction_factor: float
    base_value: float  # Expected value (average)
    contributions: List[FeatureContribution]
    top_positive: List[FeatureContribution]
    top_negative: List[FeatureContribution]
    explanation_text: str


class SHAPExplainer:
    """
    SHAP-based explainer for geometric correction model.

    Provides interpretable explanations for why a specific
    correction factor was predicted.
    """

    # Human-readable feature names
    FEATURE_NAMES_TR = {
        'hairpin_count': 'Viraj sayısı',
        'hairpin_density': 'Viraj yoğunluğu (per km)',
        'turn_count': 'Dönüş sayısı',
        'turn_density': 'Dönüş yoğunluğu',
        'total_ascent': 'Toplam tırmanış (m)',
        'total_descent': 'Toplam iniş (m)',
        'elevation_gain': 'Yükselik farkı (m)',
        'max_grade': 'Maks eğim (%)',
        'avg_abs_grade': 'Ort. eğim (%)',
        'distance_km': 'Etap uzunluğu (km)',
        'avg_curvature': 'Ort. eğrilik',
        'max_curvature': 'Maks eğrilik',
        'p95_curvature': 'P95 eğrilik',
        'curvature_density': 'Eğrilik yoğunluğu',
        'straight_percentage': 'Düz yol oranı (%)',
        'curvy_percentage': 'Virajlı yol oranı (%)',
        'driver_hairpin_perf': 'Pilot viraj performansı',
        'driver_climb_perf': 'Pilot tırmanış performansı',
        'driver_curvature_sens': 'Pilot eğrilik hassasiyeti',
        'driver_grade_perf': 'Pilot eğim performansı',
        'driver_profile_confidence': 'Pilot profil güveni',
        'baseline_ratio': 'Baseline ratio',
        'momentum_factor': 'Rally momentum',
        'surface_adjustment': 'Zemin düzeltmesi',
        'hairpin_x_driver': 'Viraj × Pilot etkileşimi',
        'climb_x_driver': 'Tırmanış × Pilot etkileşimi',
        'curvature_x_driver': 'Eğrilik × Pilot etkileşimi',
        'surface': 'Zemin tipi',
        'normalized_class': 'Araç sınıfı'
    }

    def __init__(self, model: GeometricCorrectionModel):
        """
        Initialize explainer.

        Args:
            model: Trained GeometricCorrectionModel
        """
        _require_shap_dependencies()

        if model.model is None:
            raise ValueError("Model must be trained before creating explainer")

        self.model = model
        self.explainer = shap.TreeExplainer(model.model)
        self.expected_value = float(self.explainer.expected_value)

        logger.info(f"SHAP Explainer initialized. Base value: {self.expected_value:.4f}")

    def explain(self, features: Dict) -> PredictionExplanation:
        """
        Generate explanation for a prediction.

        Args:
            features: Feature dictionary

        Returns:
            PredictionExplanation with all details
        """
        _require_shap_dependencies()
        # Convert to DataFrame
        X = pd.DataFrame([features])

        # Ensure correct column order
        for col in self.model.feature_names:
            if col not in X.columns:
                X[col] = 0

        X = X[self.model.feature_names]

        # Encode categoricals to numeric and cast entire frame to float64
        # so SHAP's isnan check never encounters non-numeric dtypes
        X = self._encode_categoricals(X)
        X_numeric = X.astype(np.float64)

        # Get SHAP values using pure numeric array
        shap_values = self.explainer.shap_values(X_numeric)[0]

        # Get prediction from original model (uses its own encoding)
        X_for_pred = pd.DataFrame([features])
        for col in self.model.feature_names:
            if col not in X_for_pred.columns:
                X_for_pred[col] = 0
        X_for_pred = X_for_pred[self.model.feature_names]
        correction_factor = float(self.model.predict(X_for_pred)[0])

        # Build contributions list
        contributions = []
        total_shap = sum(abs(sv) for sv in shap_values)

        for i, (feat_name, shap_val) in enumerate(zip(self.model.feature_names, shap_values)):
            feat_value = X.iloc[0, i]

            # Convert to native Python types
            if hasattr(feat_value, 'item'):
                feat_value = feat_value.item()
            shap_val = float(shap_val)

            contribution_pct = (abs(shap_val) / total_shap * 100) if total_shap > 0 else 0
            direction = 'increases' if shap_val > 0 else 'decreases'

            contributions.append(FeatureContribution(
                feature_name=feat_name,
                feature_value=feat_value,
                shap_value=shap_val,
                contribution_pct=contribution_pct,
                direction=direction
            ))

        # Sort by absolute SHAP value
        contributions.sort(key=lambda x: abs(x.shap_value), reverse=True)

        # Top positive and negative
        top_positive = [c for c in contributions if c.shap_value > 0][:5]
        top_negative = [c for c in contributions if c.shap_value < 0][:5]

        # Generate text explanation
        explanation_text = self._generate_explanation_text(
            correction_factor=correction_factor,
            base_value=self.expected_value,
            top_positive=top_positive,
            top_negative=top_negative
        )

        return PredictionExplanation(
            correction_factor=correction_factor,
            base_value=self.expected_value,
            contributions=contributions,
            top_positive=top_positive,
            top_negative=top_negative,
            explanation_text=explanation_text
        )

    def _generate_explanation_text(self, correction_factor: float,
                                   base_value: float,
                                   top_positive: List[FeatureContribution],
                                   top_negative: List[FeatureContribution]) -> str:
        """Generate human-readable explanation."""
        diff_pct = (correction_factor - 1) * 100

        if abs(diff_pct) < 0.5:
            adjustment_desc = "neredeyse değişmedi"
        elif diff_pct > 0:
            adjustment_desc = f"%{diff_pct:.1f} artırıldı (daha yavaş tahmin)"
        else:
            adjustment_desc = f"%{abs(diff_pct):.1f} azaltıldı (daha hızlı tahmin)"

        text = f"""
GEOMETRİK DÜZELTME AÇIKLAMASI
{'=' * 50}

Düzeltme Faktörü: {correction_factor:.4f}
Base değer (ortalama): {base_value:.4f}
Sonuç: Baseline tahmin {adjustment_desc}

"""

        if top_positive:
            text += "TAHMİNİ ARTTIRAN FAKTÖRLER (daha yavaş):\n"
            text += "-" * 40 + "\n"

            for contrib in top_positive[:5]:
                feat_name_tr = self.FEATURE_NAMES_TR.get(
                    contrib.feature_name, contrib.feature_name
                )

                if isinstance(contrib.feature_value, (int, float)):
                    val_str = f"{contrib.feature_value:.2f}"
                else:
                    val_str = str(contrib.feature_value)

                text += f"  + {feat_name_tr}: {val_str}\n"
                text += f"    Katkı: +{contrib.shap_value*100:.2f}% ({contrib.contribution_pct:.1f}%)\n"

        if top_negative:
            text += "\nTAHMİNİ AZALTAN FAKTÖRLER (daha hızlı):\n"
            text += "-" * 40 + "\n"

            for contrib in top_negative[:5]:
                feat_name_tr = self.FEATURE_NAMES_TR.get(
                    contrib.feature_name, contrib.feature_name
                )

                if isinstance(contrib.feature_value, (int, float)):
                    val_str = f"{contrib.feature_value:.2f}"
                else:
                    val_str = str(contrib.feature_value)

                text += f"  - {feat_name_tr}: {val_str}\n"
                text += f"    Katkı: {contrib.shap_value*100:.2f}% ({contrib.contribution_pct:.1f}%)\n"

        # Summary
        text += f"\n{'=' * 50}\n"
        text += "ÖZET\n"
        text += f"{'=' * 50}\n\n"

        # Dominant factors
        all_contribs = top_positive + top_negative
        if all_contribs:
            dominant = all_contribs[0]
            dominant_name_tr = self.FEATURE_NAMES_TR.get(
                dominant.feature_name, dominant.feature_name
            )
            text += f"En etkili faktör: {dominant_name_tr}\n"
            text += f"  Değer: {dominant.feature_value}\n"
            text += f"  Katkı: {dominant.shap_value*100:+.2f}%\n"

        return text

    # Sabit sözlükler: eğitim ve tahmin arasında tutarlı kodlama sağlar
    _SURFACE_MAP = {'asphalt': 0, 'gravel': 1, 'mixed': 2, 'snow': 3, 'unknown': 4}
    _CLASS_MAP = {
        'Rally2': 0, 'Rally3': 1, 'Rally4': 2, 'Rally5': 3,
        'K1': 4, 'K2': 5, 'K3': 6, 'K4': 7,
        'H1': 8, 'H2': 9, 'N': 10, 'Unknown': 11
    }

    def _encode_categoricals(self, X: pd.DataFrame) -> pd.DataFrame:
        """Encode categorical features to numeric codes for SHAP compatibility."""
        _require_shap_dependencies()
        X = X.copy()

        if 'surface' in X.columns:
            X['surface'] = X['surface'].map(self._SURFACE_MAP).fillna(
                len(self._SURFACE_MAP)
            ).astype(float)

        if 'normalized_class' in X.columns:
            X['normalized_class'] = X['normalized_class'].map(self._CLASS_MAP).fillna(
                len(self._CLASS_MAP)
            ).astype(float)

        return X

    def get_waterfall_data(self, features: Dict) -> Dict:
        """
        Get data for waterfall visualization.

        Returns dict suitable for plotting.
        """
        explanation = self.explain(features)

        # Build waterfall data
        data = {
            'base_value': explanation.base_value,
            'final_value': explanation.correction_factor,
            'features': [],
            'values': [],
            'shap_values': [],
            'cumulative': []
        }

        cumsum = explanation.base_value

        for contrib in explanation.contributions[:10]:  # Top 10
            data['features'].append(contrib.feature_name)
            data['values'].append(contrib.feature_value)
            data['shap_values'].append(contrib.shap_value)
            cumsum += contrib.shap_value
            data['cumulative'].append(cumsum)

        return data

    def get_summary_stats(self, X: pd.DataFrame) -> Dict:
        """
        Get summary statistics for a dataset of predictions.

        Args:
            X: Feature DataFrame

        Returns:
            Dictionary with mean absolute SHAP values per feature
        """
        _require_shap_dependencies()
        X_encoded = self._encode_categoricals(X).astype(np.float64)
        shap_values = self.explainer.shap_values(X_encoded)

        mean_abs_shap = np.mean(np.abs(shap_values), axis=0)

        return dict(sorted(
            zip(self.model.feature_names, mean_abs_shap),
            key=lambda x: x[1],
            reverse=True
        ))


def main():
    """Test SHAP explainer."""
    import argparse
    from pathlib import Path
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent.parent))

    parser = argparse.ArgumentParser(description="SHAP Explainer Test")
    parser.add_argument('--model', type=str, required=True,
                       help='Path to trained model (.pkl)')

    args = parser.parse_args()

    # Load model
    print(f"Loading model from {args.model}...")
    model = GeometricCorrectionModel()
    model.load(args.model)

    # Create explainer
    print("Creating SHAP explainer...")
    explainer = SHAPExplainer(model)

    # Test with sample features
    print("\nTesting with sample features...")
    sample_features = {
        'distance_km': 15.5,
        'hairpin_count': 12,
        'hairpin_density': 0.77,
        'turn_count': 45,
        'turn_density': 2.9,
        'total_ascent': 521,
        'total_descent': 480,
        'elevation_gain': 320,
        'max_grade': 12.5,
        'avg_abs_grade': 5.2,
        'avg_curvature': 0.003,
        'max_curvature': 0.025,
        'p95_curvature': 0.012,
        'curvature_density': 3.2,
        'straight_percentage': 35,
        'curvy_percentage': 25,
        'driver_hairpin_perf': 1.004,
        'driver_climb_perf': 1.014,
        'driver_curvature_sens': 0.998,
        'driver_grade_perf': 1.008,
        'driver_profile_confidence': 0.8,
        'baseline_ratio': 1.052,
        'momentum_factor': 1.01,
        'surface_adjustment': 0.98,
        'hairpin_x_driver': 0.77 * 1.004,
        'climb_x_driver': 521 * 1.014,
        'curvature_x_driver': 0.012 * 0.998,
        'surface': 'gravel',
        'normalized_class': 'Rally2'
    }

    explanation = explainer.explain(sample_features)
    print(explanation.explanation_text)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
