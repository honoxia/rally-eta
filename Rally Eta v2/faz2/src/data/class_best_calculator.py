"""
Calculate class best times for rally stages.
"""
import sqlite3
import logging
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class ClassBestTimeCalculator:
    """
    Calculate class best time for a specific rally stage and car class.

    Uses normalized_class column (requires Faz 1A migration).
    """

    def __init__(self, db_path: str):
        """
        Initialize calculator.

        Args:
            db_path: Path to rally results database
        """
        self.db_path = db_path

    def get_class_best(self, rally_id: str, stage_id: str,
                       normalized_class: str) -> Optional[dict]:
        """
        Get class best time for a specific stage and class.

        Args:
            rally_id: Rally ID
            stage_id: Stage ID (e.g., 'SS3', 'ss1')
            normalized_class: Normalized car class (e.g., 'Rally2')

        Returns:
            {
                'class_best_time': 630.5,  # seconds
                'class_best_driver': 'Pilot A',
                'finisher_count': 15,
                'normalized_class': 'Rally2'
            }

            Returns None if no finishers in that class.

        Example:
            >>> calc = ClassBestTimeCalculator('data/raw/rally_results.db')
            >>> result = calc.get_class_best('bodrum_2025', 'SS3', 'Rally2')
            >>> print(result['class_best_time'])
            630.5
        """
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            query = """
                WITH filtered AS (
                    SELECT
                        time_seconds,
                        COALESCE(raw_driver_name, driver_name) as driver_name
                    FROM stage_results
                    WHERE (stage_id = ? OR (rally_id = ? AND stage_number = ?))
                      AND COALESCE(normalized_class, car_class) = ?
                      AND time_seconds > 0
                ),
                summary AS (
                    SELECT
                        MIN(time_seconds) as class_best_time,
                        COUNT(*) as finisher_count
                    FROM filtered
                )
                SELECT
                    summary.class_best_time,
                    (
                        SELECT driver_name
                        FROM filtered
                        WHERE time_seconds = summary.class_best_time
                        ORDER BY driver_name
                        LIMIT 1
                    ) as class_best_driver,
                    summary.finisher_count
                FROM summary
                WHERE summary.class_best_time IS NOT NULL
            """

            stage_num = self._extract_stage_number(stage_id)
            cursor.execute(query, [stage_id, rally_id, stage_num, normalized_class])
            row = cursor.fetchone()
        finally:
            conn.close()

        if not row or row[0] is None:
            logger.warning(
                f"No finishers found for {normalized_class} in {rally_id}/{stage_id}"
            )
            return None

        class_best_time, class_best_driver, finisher_count = row

        return {
            'class_best_time': class_best_time,
            'class_best_driver': class_best_driver,
            'finisher_count': finisher_count,
            'normalized_class': normalized_class
        }

    def get_all_class_bests(self, rally_id: str, stage_id: str) -> dict:
        """
        Get class best times for ALL classes in a stage.

        Returns:
            {
                'Rally2': {'class_best_time': 630.5, ...},
                'Rally3': {'class_best_time': 645.2, ...},
                ...
            }
        """
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            query = """
                WITH filtered AS (
                    SELECT
                        COALESCE(normalized_class, car_class) as nclass,
                        time_seconds,
                        COALESCE(raw_driver_name, driver_name) as driver_name
                    FROM stage_results
                    WHERE (stage_id = ? OR (rally_id = ? AND stage_number = ?))
                      AND COALESCE(normalized_class, car_class) IS NOT NULL
                      AND time_seconds > 0
                ),
                summary AS (
                    SELECT
                        nclass,
                        MIN(time_seconds) as class_best_time,
                        COUNT(*) as finisher_count
                    FROM filtered
                    GROUP BY nclass
                )
                SELECT
                    summary.nclass,
                    summary.class_best_time,
                    (
                        SELECT driver_name
                        FROM filtered
                        WHERE filtered.nclass = summary.nclass
                          AND filtered.time_seconds = summary.class_best_time
                        ORDER BY driver_name
                        LIMIT 1
                    ) as class_best_driver,
                    summary.finisher_count
                FROM summary
            """

            stage_num = self._extract_stage_number(stage_id)
            cursor.execute(query, [stage_id, rally_id, stage_num])
            rows = cursor.fetchall()
        finally:
            conn.close()

        results = {}
        for row in rows:
            car_class, class_best_time, class_best_driver, finisher_count = row
            results[car_class] = {
                'class_best_time': class_best_time,
                'class_best_driver': class_best_driver,
                'finisher_count': finisher_count,
                'normalized_class': car_class
            }

        return results

    def _extract_stage_number(self, stage_id: str) -> int:
        import re

        stage_str = str(stage_id)
        ss_match = re.search(r"[sS]{2}(\d+)", stage_str)
        if ss_match:
            return int(ss_match.group(1))

        num_match = re.search(r"(\d+)", stage_str)
        return int(num_match.group(1)) if num_match else int(stage_id)


def main():
    """Test class best calculator."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--db-path', default='data/raw/rally_results.db')
    parser.add_argument('--rally-id', required=True, help='Rally ID')
    parser.add_argument('--stage-id', required=True, help='Stage ID (e.g., SS3)')

    args = parser.parse_args()

    calc = ClassBestTimeCalculator(args.db_path)

    print(f"\nClass Best Times for {args.rally_id}/{args.stage_id}")
    print("=" * 60)

    all_bests = calc.get_all_class_bests(args.rally_id, args.stage_id)

    for class_name, data in sorted(all_bests.items()):
        minutes = int(data['class_best_time'] // 60)
        seconds = data['class_best_time'] % 60

        print(f"\n{class_name}:")
        print(f"  Best time: {minutes}:{seconds:05.2f}")
        print(f"  Driver: {data['class_best_driver']}")
        print(f"  Finishers: {data['finisher_count']}")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
