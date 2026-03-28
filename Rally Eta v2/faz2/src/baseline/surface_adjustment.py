"""
Surface-based performance adjustment.
"""
import sqlite3
import logging

logger = logging.getLogger(__name__)


class SurfaceAdjustmentCalculator:
    """
    Calculate driver performance on different surfaces.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path

    def calculate_adjustment(self, driver_id: str, target_surface: str) -> dict:
        """
        Calculate surface adjustment factor.

        Args:
            driver_id: Driver ID
            target_surface: Target surface ('gravel', 'asphalt', 'snow')

        Returns:
            {
                'adjustment': 0.98,  # 2% better on this surface
                'target_surface': 'gravel',
                'target_avg': 1.048,
                'overall_avg': 1.052,
                'experience': 12,  # stages on this surface
                'explanation': "..."
            }
        """
        surface_stats = self._get_surface_stats(driver_id)

        if not surface_stats:
            logger.warning(f"No surface data for {driver_id}")
            return {
                'adjustment': 1.0,
                'target_surface': target_surface,
                'target_avg': None,
                'overall_avg': None,
                'experience': 0,
                'explanation': 'Insufficient data for surface adjustment'
            }

        # Normalize surface name
        target_surface = target_surface.lower()

        # Get target surface stats
        if target_surface not in surface_stats:
            logger.warning(f"No {target_surface} data for {driver_id}")
            return {
                'adjustment': 1.0,
                'target_surface': target_surface,
                'target_avg': None,
                'overall_avg': surface_stats['overall']['avg'],
                'experience': 0,
                'explanation': f'No experience on {target_surface}'
            }

        target_avg = surface_stats[target_surface]['avg']
        overall_avg = surface_stats['overall']['avg']
        experience = surface_stats[target_surface]['count']

        # Adjustment factor
        adjustment = target_avg / overall_avg

        # Explanation
        explanation = self._generate_explanation(
            driver_id=driver_id,
            surface_stats=surface_stats,
            target_surface=target_surface,
            adjustment=adjustment
        )

        return {
            'adjustment': adjustment,
            'target_surface': target_surface,
            'target_avg': target_avg,
            'overall_avg': overall_avg,
            'experience': experience,
            'explanation': explanation
        }

    def _get_surface_stats(self, driver_id: str) -> dict:
        """
        Get driver stats per surface.

        Returns:
            {
                'gravel': {'avg': 1.048, 'count': 12},
                'asphalt': {'avg': 1.058, 'count': 8},
                'overall': {'avg': 1.052, 'count': 20}
            }
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Per-surface stats
        query = """
            SELECT
                LOWER(surface) as surface,
                AVG(ratio_to_class_best) as avg_ratio,
                COUNT(*) as count
            FROM stage_results
            WHERE COALESCE(driver_id, driver_name) = ?
            AND time_seconds > 0
            AND ratio_to_class_best IS NOT NULL
            AND surface IS NOT NULL
            GROUP BY LOWER(surface)
        """

        cursor.execute(query, [driver_id])
        rows = cursor.fetchall()

        # Overall stats
        cursor.execute("""
            SELECT
                AVG(ratio_to_class_best) as avg_ratio,
                COUNT(*) as count
            FROM stage_results
            WHERE COALESCE(driver_id, driver_name) = ?
            AND time_seconds > 0
            AND ratio_to_class_best IS NOT NULL
        """, [driver_id])

        overall = cursor.fetchone()

        conn.close()

        if not overall or overall[1] == 0:
            return {}

        # Build stats dict
        stats = {
            'overall': {
                'avg': overall[0],
                'count': overall[1]
            }
        }

        for surface, avg_ratio, count in rows:
            stats[surface] = {
                'avg': avg_ratio,
                'count': count
            }

        return stats

    def _generate_explanation(self, driver_id, surface_stats, target_surface,
                             adjustment):
        """Generate explanation."""

        explanation = f"""
SURFACE PERFORMANSI - {driver_id}
{'=' * 50}

Hedef surface: {target_surface.upper()}

Tüm surface'ler:
"""

        for surface, stats in sorted(surface_stats.items()):
            if surface == 'overall':
                continue

            diff_pct = (stats['avg'] / surface_stats['overall']['avg'] - 1) * 100
            marker = '→' if surface == target_surface else ' '

            explanation += f"{marker} {surface.capitalize():10s}: {stats['avg']:.3f} "
            explanation += f"({stats['count']:2d} etap, {diff_pct:+.1f}%)\n"

        explanation += f"\nGenel ortalama: {surface_stats['overall']['avg']:.3f}\n"

        explanation += f"""
Adjustment:
  • {target_surface.capitalize()} performansı: {surface_stats[target_surface]['avg']:.3f}
  • Genel ortalama: {surface_stats['overall']['avg']:.3f}
  • Adjustment factor: {adjustment:.3f} ({(adjustment-1)*100:+.1f}%)

Açıklama:
  Pilot {target_surface}'da genel ortalamasından %{abs((adjustment-1)*100):.1f} {'daha iyi' if adjustment < 1 else 'daha kötü'}.
"""

        return explanation


def main():
    """Test surface adjustment."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--db-path', default='data/raw/rally_results.db')
    parser.add_argument('--driver-id', required=True)
    parser.add_argument('--surface', required=True,
                       choices=['gravel', 'asphalt', 'snow'])

    args = parser.parse_args()

    calc = SurfaceAdjustmentCalculator(args.db_path)
    result = calc.calculate_adjustment(args.driver_id, args.surface)

    print(result['explanation'])
    print(f"\n✅ Adjustment Factor: {result['adjustment']:.3f}")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
