"""
Driver performance analysis for baseline calculation.
Rally-based weighted form (son 3-5 ralli agirliklı ortalama).
"""
import sqlite3
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


def _mean(values: List[float]) -> float:
    """Return arithmetic mean using stdlib only."""
    return sum(values) / len(values) if values else 0.0


def _weighted_average(values: List[float], weights: List[float]) -> float:
    """Return weighted average using stdlib only."""
    total_weight = sum(weights)
    if not values:
        return 0.0
    if total_weight <= 0:
        return _mean(values)
    return sum(value * weight for value, weight in zip(values, weights)) / total_weight


class DriverPerformanceAnalyzer:
    """
    Analyze driver historical performance.

    Calculates baseline ratio from recent rally-level averages
    with weighted form: %40 son ralli, %30 onceki, %20, %10.
    """

    # Ralli bazli agirliklar (en yeni -> en eski)
    RALLY_WEIGHTS = [0.40, 0.30, 0.20, 0.10]

    def __init__(self, db_path: str):
        self.db_path = db_path

    def get_driver_history(self, driver_name: str, limit_rallies: int = 5) -> List[dict]:
        """
        Get driver's recent rally-level performance summary.

        Args:
            driver_name: Driver name (used as identifier)
            limit_rallies: Number of recent rallies to consider

        Returns:
            List of rally performance dicts, most recent first:
            [{'rally_id': '171', 'rally_name': '...', 'avg_ratio': 1.05, 'stage_count': 8}, ...]
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Ralli bazli ortalama ratio_to_class_best hesapla
        query = """
            SELECT
                rally_id,
                rally_name,
                COALESCE(normalized_class, car_class) as nclass,
                AVG(ratio_to_class_best) as avg_ratio,
                COUNT(*) as stage_count,
                surface
            FROM stage_results
            WHERE COALESCE(driver_id, driver_name) = ?
            AND time_seconds > 0
            AND ratio_to_class_best IS NOT NULL
            AND ratio_to_class_best > 0
            GROUP BY rally_id
            ORDER BY CAST(rally_id AS INTEGER) DESC
            LIMIT ?
        """

        cursor.execute(query, [driver_name, limit_rallies])
        rows = cursor.fetchall()
        conn.close()

        history = [dict(row) for row in rows]
        logger.info(f"Retrieved {len(history)} rallies for driver {driver_name}")
        return history

    def calculate_baseline_ratio(self, driver_name: str,
                                 limit_rallies: int = 5) -> Optional[dict]:
        """
        Calculate baseline ratio from recent rally-level performance.

        Uses weighted averages:
        - Son ralli: %40
        - Onceki ralli: %30
        - 3. ralli: %20
        - 4-5. ralli: %10

        Args:
            driver_name: Driver name
            limit_rallies: Number of recent rallies to consider

        Returns:
            {
                'baseline_ratio': 1.052,
                'data_points': 4,  # ralli sayisi
                'total_stages': 28,
                'recent_rally_avg': 1.048,
                'all_avg': 1.052,
                'explanation': "..."
            }

            Returns None if insufficient data.
        """
        history = self.get_driver_history(driver_name, limit_rallies=limit_rallies)

        if len(history) == 0:
            logger.warning(f"No history found for driver {driver_name}")
            return None

        # Ralli ortalamalarini al
        rally_ratios = [r['avg_ratio'] for r in history]
        total_stages = sum(r['stage_count'] for r in history)

        # Agirlikli ortalama hesapla
        if len(rally_ratios) == 1:
            baseline_ratio = rally_ratios[0]
        else:
            weights = self._get_weights(len(rally_ratios))
            baseline_ratio = _weighted_average(rally_ratios, weights)

        # Stats
        recent_rally_avg = rally_ratios[0] if rally_ratios else 0
        all_avg = _mean(rally_ratios)

        # Explanation
        explanation = self._generate_explanation(
            driver_name=driver_name,
            history=history,
            baseline_ratio=baseline_ratio,
            recent_rally_avg=recent_rally_avg,
            all_avg=all_avg
        )

        return {
            'baseline_ratio': baseline_ratio,
            'data_points': len(history),
            'total_stages': total_stages,
            'recent_rally_avg': recent_rally_avg,
            'all_avg': all_avg,
            'explanation': explanation,
            'history': history
        }

    def _get_weights(self, n: int) -> List[float]:
        """
        Get rally weights for n rallies.
        Uses predefined weights: [0.40, 0.30, 0.20, 0.10]
        Extra rallies share the last weight.
        """
        if n <= len(self.RALLY_WEIGHTS):
            weights = list(self.RALLY_WEIGHTS[:n])
        else:
            # Fazla ralliler icin son agirligi paylas
            weights = list(
                self.RALLY_WEIGHTS +
                [self.RALLY_WEIGHTS[-1]] * (n - len(self.RALLY_WEIGHTS))
            )

        total = sum(weights)
        if total <= 0:
            return [1.0 / n] * n if n > 0 else []
        return [weight / total for weight in weights]

    def _generate_explanation(self, driver_name, history, baseline_ratio,
                             recent_rally_avg, all_avg):
        """Generate human-readable explanation."""

        explanation = f"""
BASELINE HESAPLAMA - {driver_name}
{'=' * 50}

Veri:
  * Son {len(history)} ralli (agirlikli ortalama)
  * Agirliklar: {', '.join(f'%{w*100:.0f}' for w in self._get_weights(len(history)))}

Ralli Bazli Performans:
"""

        for i, rally in enumerate(history):
            weight = self._get_weights(len(history))[i]
            explanation += f"  * R{rally['rally_id']}: {rally['rally_name'][:30]} "
            explanation += f"- ort: {rally['avg_ratio']:.3f} ({rally['stage_count']} etap, agirlik: %{weight*100:.0f})\n"

        explanation += f"""
Sonuc:
  * Son ralli ortalamasi: {recent_rally_avg:.3f}
  * Tum veri ortalamasi: {all_avg:.3f}
  * Baseline ratio (agirlikli): {baseline_ratio:.3f}

Aciklama:
  Pilot son {len(history)} rallide sinif liderinden ortalama %{(baseline_ratio - 1) * 100:.1f} yavaş.
"""

        if len(history) >= 2 and abs(recent_rally_avg - all_avg) > 0.01:
            trend = "iyiye gidiyor" if recent_rally_avg < all_avg else "kotuye gidiyor"
            explanation += f"\n  ! Form {trend} (son ralli: {recent_rally_avg:.3f} vs tum: {all_avg:.3f})\n"

        return explanation


def main():
    """Test driver performance analyzer."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--db-path', default='data/raw/rally_results.db')
    parser.add_argument('--driver-name', required=True)
    parser.add_argument('--rallies', type=int, default=5)

    args = parser.parse_args()

    analyzer = DriverPerformanceAnalyzer(args.db_path)
    result = analyzer.calculate_baseline_ratio(args.driver_name, args.rallies)

    if result:
        print(result['explanation'])
        print(f"\nBaseline Ratio: {result['baseline_ratio']:.3f}")
    else:
        print(f"No data found for {args.driver_name}")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
