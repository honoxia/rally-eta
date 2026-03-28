"""
Complete baseline prediction orchestrator.
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.baseline.driver_performance import DriverPerformanceAnalyzer
from src.baseline.rally_momentum import RallyMomentumAnalyzer
from src.baseline.surface_adjustment import SurfaceAdjustmentCalculator
from src.data.class_best_calculator import ClassBestTimeCalculator
import logging

logger = logging.getLogger(__name__)


class BaselinePredictor:
    """
    STAGE 1: Baseline Prediction

    Combines:
    - Driver historical performance
    - Rally momentum
    - Surface adjustment
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.perf_analyzer = DriverPerformanceAnalyzer(db_path)
        self.momentum_analyzer = RallyMomentumAnalyzer(db_path)
        self.surface_calc = SurfaceAdjustmentCalculator(db_path)
        self.class_best_calc = ClassBestTimeCalculator(db_path)

    def predict(self, driver_id: str, rally_id: str, stage_id: str,
                current_stage: int, surface: str, normalized_class: str) -> dict:
        """
        Complete baseline prediction.

        Returns:
            {
                'baseline_ratio': 1.041,
                'predicted_time': 645.3,
                'predicted_time_str': '10:45.3',
                'components': {...},
                'explanation': "...",
                'confidence': 'MEDIUM'
            }
        """
        # 1. Driver performance
        perf = self.perf_analyzer.calculate_baseline_ratio(driver_id)

        if not perf:
            raise ValueError(f"No performance data for {driver_id}")

        # 2. Rally momentum (driver_name used as identifier)
        momentum = self.momentum_analyzer.calculate_momentum(
            driver_name=driver_id,
            rally_id=rally_id,
            current_stage=current_stage,
            driver_baseline=perf['baseline_ratio']
        )

        # 3. Surface adjustment (driver_name used as identifier)
        surface_adj = self.surface_calc.calculate_adjustment(driver_id, surface)

        # 4. Calculate final baseline
        baseline_ratio = (
            perf['baseline_ratio'] *
            (1 + momentum['momentum']) *
            surface_adj['adjustment']
        )

        # 5. Get class best time
        class_best = self.class_best_calc.get_class_best(
            rally_id=rally_id,
            stage_id=stage_id,
            normalized_class=normalized_class
        )

        if not class_best:
            raise ValueError(
                f"No class best for {normalized_class} in {rally_id}/{stage_id}"
            )

        # 6. Predicted time
        predicted_time = baseline_ratio * class_best['class_best_time']
        predicted_time_str = self._format_time(predicted_time)
        class_best_str = self._format_time(class_best['class_best_time'])

        # 7. Full explanation
        explanation = self._generate_explanation(
            driver_id=driver_id,
            perf=perf,
            momentum=momentum,
            surface_adj=surface_adj,
            baseline_ratio=baseline_ratio,
            class_best=class_best,
            predicted_time_str=predicted_time_str,
            class_best_str=class_best_str
        )

        return {
            'baseline_ratio': baseline_ratio,
            'predicted_time': predicted_time,
            'predicted_time_str': predicted_time_str,
            'class_best_time': class_best['class_best_time'],
            'class_best_str': class_best_str,
            'class_best_driver': class_best['class_best_driver'],
            'components': {
                'driver_baseline': perf['baseline_ratio'],
                'momentum_factor': 1 + momentum['momentum'],
                'surface_adjustment': surface_adj['adjustment']
            },
            'explanation': explanation,
            'confidence': self._assess_confidence(perf, momentum, surface_adj)
        }

    def _format_time(self, seconds: float) -> str:
        """Format seconds to MM:SS.s"""
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}:{secs:05.2f}"

    def _generate_explanation(self, driver_id, perf, momentum, surface_adj,
                             baseline_ratio, class_best, predicted_time_str,
                             class_best_str):
        """Generate full explanation."""

        return f"""
{'=' * 60}
BASELINE TAHMİN - {driver_id}
{'=' * 60}

{perf['explanation']}

{momentum['explanation']}

{surface_adj['explanation']}

{'=' * 60}
FINAL TAHMİN
{'=' * 60}

Hesaplama:
  • Driver baseline: {perf['baseline_ratio']:.3f}
  • × Momentum: {1 + momentum['momentum']:.3f} ({momentum['status']})
  • × Surface adj: {surface_adj['adjustment']:.3f}
  ─────────────────────
  = Baseline ratio: {baseline_ratio:.3f}

Zaman Tahmini:
  • Sınıf lideri ({class_best['class_best_driver']}): {class_best_str}
  • Tahmin: {predicted_time_str} ({baseline_ratio:.3f}×)
  • Fark: +{(baseline_ratio - 1) * class_best['class_best_time']:.1f} saniye

{'=' * 60}
"""

    def _assess_confidence(self, perf, momentum, surface_adj):
        """Quick confidence assessment."""
        if perf['data_points'] >= 15 and surface_adj['experience'] >= 10:
            return 'HIGH'
        elif perf['data_points'] >= 10:
            return 'MEDIUM'
        else:
            return 'LOW'
