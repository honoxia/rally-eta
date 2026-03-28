"""
Rally momentum analysis - within-rally form tracking.
Supports both DB-backed and live TOSFED data.
"""
import sqlite3
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class RallyMomentumAnalyzer:
    """
    Analyze driver's form within current rally.
    Tracks in-class ranking trend across stages.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path

    def calculate_momentum(self, driver_name: str, rally_id: str,
                          current_stage: int,
                          driver_baseline: float) -> dict:
        """
        Calculate rally momentum from DB data.

        Args:
            driver_name: Driver name
            rally_id: Rally ID
            current_stage: Current stage number (for prediction)
            driver_baseline: Driver's historical baseline ratio

        Returns:
            {
                'momentum': +0.02,
                'momentum_factor': 0.98,
                'status': 'Good form',
                'rally_avg': 1.042,
                'baseline': 1.052,
                'stages_analyzed': 2,
                'class_positions': [3, 2, 1],
                'position_trend': 'yukseliyor',
                'explanation': "..."
            }
        """
        rally_stages = self._get_rally_stages(driver_name, rally_id, current_stage)

        if len(rally_stages) < 1:
            return {
                'momentum': 0.0,
                'momentum_factor': 1.0,
                'status': 'Ralli henuz baslamadi',
                'rally_avg': None,
                'baseline': driver_baseline,
                'stages_analyzed': 0,
                'class_positions': [],
                'position_trend': 'bilinmiyor',
                'explanation': 'Ilk etap - momentum verisi yok'
            }

        return self._calculate_from_stages(rally_stages, driver_baseline)

    def calculate_momentum_from_live_data(self, stages_data: List[Dict],
                                          driver_name: str,
                                          normalized_class: str,
                                          driver_baseline: float) -> dict:
        """
        Calculate momentum from live TOSFED data (not in DB).

        Args:
            stages_data: List of stage dicts from TOSFED scraper:
                [{'stage_number': 1, 'results': [{'driver_name': ..., 'time_seconds': ..., 'car_class': ...}]}]
            driver_name: Target driver name
            normalized_class: Driver's normalized car class
            driver_baseline: Driver's historical baseline ratio

        Returns:
            Same dict format as calculate_momentum()
        """
        # Her etap icin pilotun sinif ici ratio ve siralamasini hesapla
        rally_stages = []

        # Normalizer yukle (bir kez)
        try:
            from src.data.car_class_normalizer import CarClassNormalizer
            _normalizer = CarClassNormalizer()
        except Exception:
            _normalizer = None

        for stage in stages_data:
            stage_num = stage.get('stage_number', 0)
            results = stage.get('results', [])

            # Sinif ici sonuclari filtrele
            class_results = []
            driver_time = None

            for r in results:
                r_class = r.get('car_class', '')
                r_time = r.get('time_seconds', 0)
                r_name = r.get('driver_name', '')

                if not r_time or r_time <= 0:
                    continue

                # Sinif eslesmesi - her iki tarafi da normalize ederek karsilastir
                r_class_normalized = _normalizer.normalize(r_class) if _normalizer and r_class else r_class
                if r_class_normalized == normalized_class or r_class == normalized_class:
                    class_results.append({'name': r_name, 'time': r_time})
                    if r_name == driver_name:
                        driver_time = r_time

            if not driver_time or not class_results:
                continue

            # Class best ve ratio hesapla
            class_best = min(r['time'] for r in class_results)
            ratio = driver_time / class_best if class_best > 0 else 1.0

            # Sinif ici siralama
            sorted_results = sorted(class_results, key=lambda x: x['time'])
            position = next((i+1 for i, r in enumerate(sorted_results) if r['name'] == driver_name), len(sorted_results))

            rally_stages.append({
                'stage_number': stage_num,
                'ratio_to_class_best': ratio,
                'class_position': position,
                'class_size': len(class_results)
            })

        if not rally_stages:
            return {
                'momentum': 0.0,
                'momentum_factor': 1.0,
                'status': 'Canli veri alinamadi',
                'rally_avg': None,
                'baseline': driver_baseline,
                'stages_analyzed': 0,
                'class_positions': [],
                'position_trend': 'bilinmiyor',
                'explanation': 'Pilot bu rallide bulunamadi veya sinif eslesmesi yapilamadi'
            }

        return self._calculate_from_stages(rally_stages, driver_baseline)

    def _calculate_from_stages(self, rally_stages: List[Dict], driver_baseline: float) -> dict:
        """Common momentum calculation from stage data."""
        ratios = [s['ratio_to_class_best'] for s in rally_stages]
        positions = [s['class_position'] for s in rally_stages]
        rally_avg = sum(ratios) / len(ratios) if ratios else 0.0

        # Momentum = baseline'dan ne kadar farkli
        # Pozitif = baseline'dan daha iyi
        momentum = (driver_baseline - rally_avg) / driver_baseline if driver_baseline > 0 else 0.0

        # Momentum factor (tahmine uygulanacak carpan)
        # momentum > 0 -> iyi form -> factor < 1 (daha hizli)
        # momentum < 0 -> kotu form -> factor > 1 (daha yavas)
        momentum_factor = 1.0 - momentum
        momentum_factor = max(0.90, min(momentum_factor, 1.10))  # Max %10 etki

        # Siralama trendi
        position_trend = self._calculate_position_trend(positions)

        # Status
        if momentum > 0.03:
            status = 'Mukemmel form'
        elif momentum > 0.01:
            status = 'Iyi form'
        elif momentum > -0.01:
            status = 'Normal form'
        elif momentum > -0.03:
            status = 'Dusuk form'
        else:
            status = 'Kotu form'

        explanation = self._generate_explanation(
            rally_stages=rally_stages,
            rally_avg=rally_avg,
            baseline=driver_baseline,
            momentum=momentum,
            momentum_factor=momentum_factor,
            status=status,
            position_trend=position_trend
        )

        return {
            'momentum': momentum,
            'momentum_factor': momentum_factor,
            'status': status,
            'rally_avg': rally_avg,
            'baseline': driver_baseline,
            'stages_analyzed': len(rally_stages),
            'class_positions': positions,
            'position_trend': position_trend,
            'explanation': explanation
        }

    def _get_rally_stages(self, driver_name: str, rally_id: str,
                          current_stage: int) -> list:
        """Get driver's stages in current rally (before current_stage) from DB."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = """
            SELECT
                stage_number,
                ratio_to_class_best,
                class_position
            FROM stage_results
            WHERE COALESCE(driver_id, driver_name) = ?
            AND rally_id = ?
            AND stage_number < ?
            AND time_seconds > 0
            AND ratio_to_class_best IS NOT NULL
            ORDER BY stage_number ASC
        """

        cursor.execute(query, [driver_name, str(rally_id), current_stage])
        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]

    def _calculate_position_trend(self, positions: List[int]) -> str:
        """Siralama trendini hesapla."""
        if len(positions) < 2:
            return 'yetersiz veri'

        # Son 3 etabin trendi
        recent = positions[-3:] if len(positions) >= 3 else positions
        if len(recent) < 2:
            return 'yetersiz veri'

        # Basit trend: son pozisyon vs ilk pozisyon
        first = recent[0]
        last = recent[-1]

        if last < first:
            return 'yukseliyor'  # Daha iyi siralama (kucuk sayi = daha iyi)
        elif last > first:
            return 'dusuyor'
        else:
            return 'sabit'

    def _generate_explanation(self, rally_stages, rally_avg, baseline,
                             momentum, momentum_factor, status, position_trend):
        """Generate explanation."""

        explanation = f"""
RALLY MOMENTUM
{'=' * 50}

Bu rallide performans:
"""

        for stage in rally_stages:
            pos = stage.get('class_position', '?')
            size = stage.get('class_size', '?')
            explanation += f"  * SS{stage['stage_number']}: {stage['ratio_to_class_best']:.3f} "
            explanation += f"(sinif {pos}./{size})\n" if size != '?' else f"(sinif {pos}.)\n"

        explanation += f"""
Analiz:
  * Rally ortalamasi: {rally_avg:.3f}
  * Historical baseline: {baseline:.3f}
  * Fark: {momentum*100:+.1f}%
  * Momentum factor: {momentum_factor:.3f}
  * Siralama trendi: {position_trend}
  * Durum: {status}

Aciklama:
  Pilot bu rallide baseline'dan %{abs(momentum)*100:.1f} {'daha iyi' if momentum > 0 else 'daha kotu'} performans gosteriyor.
  Tahmine uygulanacak carpan: {momentum_factor:.3f}
"""

        return explanation


def main():
    """Test rally momentum."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--db-path', default='data/raw/rally_results.db')
    parser.add_argument('--driver-name', required=True)
    parser.add_argument('--rally-id', required=True)
    parser.add_argument('--current-stage', type=int, required=True)
    parser.add_argument('--baseline', type=float, required=True)

    args = parser.parse_args()

    analyzer = RallyMomentumAnalyzer(args.db_path)
    result = analyzer.calculate_momentum(
        driver_name=args.driver_name,
        rally_id=args.rally_id,
        current_stage=args.current_stage,
        driver_baseline=args.baseline
    )

    print(result['explanation'])
    print(f"\n{result['status']}")
    print(f"Momentum: {result['momentum']*100:+.1f}%")
    print(f"Factor: {result['momentum_factor']:.3f}")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
