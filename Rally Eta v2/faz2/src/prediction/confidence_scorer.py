"""
Confidence Scorer for Rally ETA Predictions.

Calculates prediction confidence based on:
- Historical data availability
- Surface experience
- Geometric similarity
- Rally momentum data
"""
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class ConfidenceLevel(Enum):
    """Confidence level categories."""
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    VERY_LOW = "VERY_LOW"


@dataclass
class ConfidenceResult:
    """Confidence calculation result."""
    level: str  # HIGH, MEDIUM, LOW, VERY_LOW
    score: int  # 0-100
    emoji: str  # Visual indicator
    reasons: List[str]  # Explanation reasons
    breakdown: Dict[str, int]  # Score per category


class ConfidenceScorer:
    """
    Calculate prediction confidence based on multiple factors.

    Scoring breakdown:
    - Historical data: max 40 points
    - Surface experience: max 25 points
    - Geometric similarity: max 20 points
    - Rally momentum: max 15 points

    Total: 100 points
    """

    # Thresholds for confidence levels
    THRESHOLDS = {
        'HIGH': 75,
        'MEDIUM': 55,
        'LOW': 35
        # Below 35 = VERY_LOW
    }

    # Scoring weights
    WEIGHTS = {
        'historical': 40,
        'surface': 25,
        'geometry': 20,
        'momentum': 15
    }

    def __init__(self):
        """Initialize scorer."""
        pass

    def calculate(
        self,
        driver_history_count: int,
        surface_experience: int,
        geometry_data_available: bool,
        driver_profile_confidence: float,
        rally_stages_count: int,
        baseline_ratio: float,
        geometric_mode: str = 'fallback'
    ) -> ConfidenceResult:
        """
        Calculate confidence score.

        Args:
            driver_history_count: Number of historical stages for driver
            surface_experience: Number of stages on target surface
            geometry_data_available: Whether KML data exists for stage
            driver_profile_confidence: Driver geometry profile confidence (0-1)
            rally_stages_count: Number of stages completed in current rally
            baseline_ratio: Calculated baseline ratio
            geometric_mode: 'geometric' or 'fallback'

        Returns:
            ConfidenceResult with score, level, and reasons
        """
        breakdown = {}
        reasons = []

        # 1. Historical data score (max 40)
        hist_score, hist_reason = self._score_historical(driver_history_count)
        breakdown['historical'] = hist_score
        reasons.append(hist_reason)

        # 2. Surface experience score (max 25)
        surf_score, surf_reason = self._score_surface(surface_experience)
        breakdown['surface'] = surf_score
        reasons.append(surf_reason)

        # 3. Geometry score (max 20)
        geo_score, geo_reason = self._score_geometry(
            geometry_data_available,
            driver_profile_confidence,
            geometric_mode
        )
        breakdown['geometry'] = geo_score
        reasons.append(geo_reason)

        # 4. Rally momentum score (max 15)
        mom_score, mom_reason = self._score_momentum(rally_stages_count)
        breakdown['momentum'] = mom_score
        reasons.append(mom_reason)

        # 5. Penalty for extreme baseline
        penalty, penalty_reason = self._baseline_penalty(baseline_ratio)
        if penalty > 0:
            breakdown['penalty'] = -penalty
            reasons.append(penalty_reason)

        # Calculate total score
        total_score = sum([
            breakdown['historical'],
            breakdown['surface'],
            breakdown['geometry'],
            breakdown['momentum']
        ]) - penalty

        total_score = max(0, min(100, total_score))

        # Determine level
        if total_score >= self.THRESHOLDS['HIGH']:
            level = ConfidenceLevel.HIGH.value
            emoji = "🟢"
        elif total_score >= self.THRESHOLDS['MEDIUM']:
            level = ConfidenceLevel.MEDIUM.value
            emoji = "🟡"
        elif total_score >= self.THRESHOLDS['LOW']:
            level = ConfidenceLevel.LOW.value
            emoji = "🟠"
        else:
            level = ConfidenceLevel.VERY_LOW.value
            emoji = "🔴"

        return ConfidenceResult(
            level=level,
            score=total_score,
            emoji=emoji,
            reasons=reasons,
            breakdown=breakdown
        )

    def _score_historical(self, count: int) -> Tuple[int, str]:
        """Score historical data availability."""
        max_score = self.WEIGHTS['historical']

        if count >= 20:
            score = max_score
            reason = f"Yeterli gecmis veri ({count} etap)"
        elif count >= 15:
            score = int(max_score * 0.9)
            reason = f"Iyi gecmis veri ({count} etap)"
        elif count >= 10:
            score = int(max_score * 0.75)
            reason = f"Orta seviye veri ({count} etap)"
        elif count >= 5:
            score = int(max_score * 0.5)
            reason = f"Az veri ({count} etap)"
        elif count >= 2:
            score = int(max_score * 0.25)
            reason = f"Cok az veri ({count} etap)"
        else:
            score = int(max_score * 0.1)
            reason = f"Yetersiz veri ({count} etap)"

        return score, reason

    def _score_surface(self, count: int) -> Tuple[int, str]:
        """Score surface experience."""
        max_score = self.WEIGHTS['surface']

        if count >= 15:
            score = max_score
            reason = f"Yeterli surface deneyimi ({count} etap)"
        elif count >= 10:
            score = int(max_score * 0.85)
            reason = f"Iyi surface deneyimi ({count} etap)"
        elif count >= 5:
            score = int(max_score * 0.65)
            reason = f"Orta surface deneyimi ({count} etap)"
        elif count >= 2:
            score = int(max_score * 0.4)
            reason = f"Az surface deneyimi ({count} etap)"
        else:
            score = int(max_score * 0.2)
            reason = f"Yetersiz surface deneyimi ({count} etap)"

        return score, reason

    def _score_geometry(
        self,
        available: bool,
        profile_confidence: float,
        mode: str
    ) -> Tuple[int, str]:
        """Score geometry data availability."""
        max_score = self.WEIGHTS['geometry']

        if not available or mode == 'fallback':
            score = int(max_score * 0.3)
            reason = "Geometrik veri yok - baseline modu"
        elif profile_confidence >= 0.8:
            score = max_score
            reason = "Geometrik duzeltme aktif (yuksek guven)"
        elif profile_confidence >= 0.5:
            score = int(max_score * 0.75)
            reason = "Geometrik duzeltme aktif (orta guven)"
        else:
            score = int(max_score * 0.5)
            reason = "Geometrik duzeltme aktif (dusuk guven)"

        return score, reason

    def _score_momentum(self, count: int) -> Tuple[int, str]:
        """Score rally momentum data."""
        max_score = self.WEIGHTS['momentum']

        if count >= 4:
            score = max_score
            reason = f"Rally form verisi yeterli ({count} etap)"
        elif count >= 2:
            score = int(max_score * 0.7)
            reason = f"Rally form verisi var ({count} etap)"
        elif count == 1:
            score = int(max_score * 0.4)
            reason = "Rally henuz basinda (1 etap)"
        else:
            score = int(max_score * 0.2)
            reason = "Rally form verisi yok (ilk etap)"

        return score, reason

    def _baseline_penalty(self, baseline_ratio: float) -> Tuple[int, str]:
        """Apply penalty for extreme baseline ratios."""
        if baseline_ratio > 1.20:
            penalty = 10
            reason = f"Uyari: Yuksek baseline ratio ({baseline_ratio:.3f})"
        elif baseline_ratio < 0.95:
            penalty = 5
            reason = f"Uyari: Dusuk baseline ratio ({baseline_ratio:.3f})"
        else:
            penalty = 0
            reason = ""

        return penalty, reason

    def generate_explanation(self, result: ConfidenceResult) -> str:
        """Generate human-readable explanation."""
        lines = []
        lines.append("=" * 50)
        lines.append(f"GUVENILIRLIK: {result.level} ({result.score}/100) {result.emoji}")
        lines.append("=" * 50)
        lines.append("")

        lines.append("SKOR DAGILIMI:")
        lines.append("-" * 30)

        for category, score in result.breakdown.items():
            if category == 'penalty':
                lines.append(f"  Ceza: {score}")
            else:
                max_score = self.WEIGHTS.get(category, 0)
                lines.append(f"  {category.capitalize()}: {score}/{max_score}")

        lines.append("")
        lines.append("DETAYLAR:")
        lines.append("-" * 30)

        for reason in result.reasons:
            if reason:  # Skip empty reasons
                lines.append(f"  - {reason}")

        lines.append("")

        # Add recommendation based on level
        if result.level == ConfidenceLevel.HIGH.value:
            lines.append("Oneri: Tahmin guvenilir, direkt kullanilabilir.")
        elif result.level == ConfidenceLevel.MEDIUM.value:
            lines.append("Oneri: Tahmin makul, dikkatli degerlendirilmeli.")
        elif result.level == ConfidenceLevel.LOW.value:
            lines.append("Oneri: Tahmin belirsiz, alternatif degerler gozden gecirilmeli.")
        else:
            lines.append("Oneri: Tahmin cok belirsiz, manuel dogrulama gerekli!")

        return "\n".join(lines)


def main():
    """Test confidence scorer."""
    print("Testing Confidence Scorer...")
    print("=" * 60)

    scorer = ConfidenceScorer()

    # Test case 1: High confidence
    print("\n--- Test 1: High Confidence ---")
    result1 = scorer.calculate(
        driver_history_count=20,
        surface_experience=15,
        geometry_data_available=True,
        driver_profile_confidence=0.9,
        rally_stages_count=4,
        baseline_ratio=1.05,
        geometric_mode='geometric'
    )
    print(scorer.generate_explanation(result1))

    # Test case 2: Medium confidence
    print("\n--- Test 2: Medium Confidence ---")
    result2 = scorer.calculate(
        driver_history_count=12,
        surface_experience=8,
        geometry_data_available=True,
        driver_profile_confidence=0.6,
        rally_stages_count=2,
        baseline_ratio=1.08,
        geometric_mode='geometric'
    )
    print(scorer.generate_explanation(result2))

    # Test case 3: Low confidence
    print("\n--- Test 3: Low Confidence ---")
    result3 = scorer.calculate(
        driver_history_count=5,
        surface_experience=3,
        geometry_data_available=False,
        driver_profile_confidence=0.3,
        rally_stages_count=1,
        baseline_ratio=1.12,
        geometric_mode='fallback'
    )
    print(scorer.generate_explanation(result3))

    # Test case 4: Very low confidence
    print("\n--- Test 4: Very Low Confidence ---")
    result4 = scorer.calculate(
        driver_history_count=2,
        surface_experience=1,
        geometry_data_available=False,
        driver_profile_confidence=0.1,
        rally_stages_count=0,
        baseline_ratio=1.25,
        geometric_mode='fallback'
    )
    print(scorer.generate_explanation(result4))


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
