"""
Stage metadata database manager.

Manages storage and retrieval of geometric stage data.
"""
import sqlite3
import logging
from typing import Optional, List, Dict
from pathlib import Path

from src.data.geometric_analyzer import StageGeometry, GeometricAnalyzer
from src.data.master_schema import ensure_stage_geometry_table

logger = logging.getLogger(__name__)


class StageMetadataManager:
    """
    Manage stage metadata in database.

    Handles:
    - Table creation
    - Inserting/updating stage geometry
    - Querying stage metadata
    """

    TABLE_NAME = 'stage_geometry'

    CREATE_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS stage_geometry (
            -- Primary key
            stage_id TEXT PRIMARY KEY,

            -- Rally info
            rally_id TEXT,
            rally_name TEXT,
            stage_name TEXT,
            stage_number INTEGER,
            surface TEXT,

            -- Basic metrics
            distance_km REAL,

            -- Elevation
            total_ascent REAL,
            total_descent REAL,
            min_altitude REAL,
            max_altitude REAL,
            elevation_gain REAL,

            -- Grade (slope)
            max_grade REAL,
            avg_grade REAL,
            avg_abs_grade REAL,

            -- Turns
            hairpin_count INTEGER,
            turn_count INTEGER,
            hairpin_density REAL,
            turn_density REAL,

            -- Curvature
            avg_curvature REAL,
            max_curvature REAL,
            p95_curvature REAL,
            curvature_density REAL,

            -- Segments
            straight_percentage REAL,
            curvy_percentage REAL,

            -- Source info
            source_kml TEXT,
            analysis_version TEXT,
            analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            elevation_status TEXT DEFAULT 'unknown',
            geometry_status TEXT DEFAULT 'pending',
            geometry_hash TEXT,
            validated_at TEXT,
            is_active INTEGER DEFAULT 1
        )
    """

    CREATE_INDEX_SQL = [
        "CREATE INDEX IF NOT EXISTS idx_stages_rally_id ON stage_geometry(rally_id)",
        "CREATE INDEX IF NOT EXISTS idx_stages_surface ON stage_geometry(surface)",
        "CREATE INDEX IF NOT EXISTS idx_stages_hairpin ON stage_geometry(hairpin_count)",
    ]

    def __init__(self, db_path: str):
        """
        Initialize manager.

        Args:
            db_path: Path to database
        """
        self.db_path = db_path
        self._ensure_table_exists()

    def _ensure_table_exists(self):
        """Create table if it doesn't exist."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        ensure_stage_geometry_table(conn)
        cursor.execute(self.CREATE_TABLE_SQL)

        for index_sql in self.CREATE_INDEX_SQL:
            cursor.execute(index_sql)

        conn.commit()
        conn.close()

        logger.info(f"Ensured {self.TABLE_NAME} table exists in {self.db_path}")

    def insert_from_geometry(self, geometry: StageGeometry, stage_id: str,
                            rally_id: str, rally_name: str = None,
                            stage_number: int = None, surface: str = None,
                            kml_file: str = None) -> bool:
        """
        Insert stage geometry into database.

        Args:
            geometry: StageGeometry object from analyzer
            stage_id: Unique stage identifier
            rally_id: Rally identifier
            rally_name: Optional rally name
            stage_number: Optional stage number (1, 2, 3...)
            surface: Optional surface type (gravel, asphalt, snow)
            kml_file: Optional source KML file path

        Returns:
            True if successful
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT OR REPLACE INTO stage_geometry (
                    stage_id, rally_id, rally_name, stage_name, stage_number, surface,
                    distance_km, total_ascent, total_descent, min_altitude, max_altitude,
                    elevation_gain, max_grade, avg_grade, avg_abs_grade,
                    hairpin_count, turn_count, hairpin_density, turn_density,
                    avg_curvature, max_curvature, p95_curvature, curvature_density,
                    straight_percentage, curvy_percentage, source_kml, analysis_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                stage_id, rally_id, rally_name, geometry.name, stage_number, surface,
                geometry.distance_km, geometry.total_ascent, geometry.total_descent,
                geometry.min_altitude, geometry.max_altitude, geometry.elevation_gain,
                geometry.max_grade, geometry.avg_grade, geometry.avg_abs_grade,
                geometry.hairpin_count, geometry.turn_count, geometry.hairpin_density,
                geometry.turn_density, geometry.avg_curvature, geometry.max_curvature,
                geometry.p95_curvature, geometry.curvature_density,
                geometry.straight_percentage, geometry.curvy_percentage, kml_file, "stage_metadata_manager_v2"
            ))

            conn.commit()
            logger.info(f"Inserted stage metadata: {stage_id}")
            return True

        except Exception as e:
            logger.error(f"Error inserting stage metadata: {e}")
            conn.rollback()
            return False

        finally:
            conn.close()

    def get_stage(self, stage_id: str) -> Optional[Dict]:
        """
        Get stage metadata by ID.

        Args:
            stage_id: Stage identifier

        Returns:
            Dict with stage data, or None if not found
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM stage_geometry WHERE stage_id = ?
        """, [stage_id])

        row = cursor.fetchone()
        conn.close()

        if row:
            return dict(row)
        return None

    def get_rally_stages(self, rally_id: str) -> List[Dict]:
        """
        Get all stages for a rally.

        Args:
            rally_id: Rally identifier

        Returns:
            List of stage metadata dicts
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM stage_geometry
            WHERE rally_id = ?
            ORDER BY stage_number
        """, [rally_id])

        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]

    def get_similar_stages(self, stage_id: str, limit: int = 10) -> List[Dict]:
        """
        Find stages with similar geometry.

        Useful for finding comparable stages for driver profiling.

        Args:
            stage_id: Reference stage ID
            limit: Maximum results

        Returns:
            List of similar stages with similarity score
        """
        # Get reference stage
        ref = self.get_stage(stage_id)

        if not ref:
            return []

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Simple similarity based on hairpin density, distance, and elevation
        cursor.execute("""
            SELECT *,
                ABS(hairpin_density - ?) +
                ABS(distance_km - ?) / 10 +
                ABS(total_ascent - ?) / 100
                AS similarity_score
            FROM stage_geometry
            WHERE stage_id != ?
            ORDER BY similarity_score ASC
            LIMIT ?
        """, [
            ref['hairpin_density'],
            ref['distance_km'],
            ref['total_ascent'],
            stage_id,
            limit
        ])

        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]

    def get_stages_by_surface(self, surface: str) -> List[Dict]:
        """Get all stages with specific surface type."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM stage_geometry
            WHERE LOWER(surface) = LOWER(?)
            ORDER BY rally_id, stage_number
        """, [surface])

        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]

    def get_high_hairpin_stages(self, min_hairpin_density: float = 1.0) -> List[Dict]:
        """Get stages with high hairpin density."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM stage_geometry
            WHERE hairpin_density >= ?
            ORDER BY hairpin_density DESC
        """, [min_hairpin_density])

        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]

    def get_statistics(self) -> Dict:
        """Get overall statistics about stored stages."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                COUNT(*) as total_stages,
                COUNT(DISTINCT rally_id) as total_rallies,
                AVG(distance_km) as avg_distance,
                AVG(hairpin_count) as avg_hairpins,
                AVG(total_ascent) as avg_ascent,
                MIN(distance_km) as min_distance,
                MAX(distance_km) as max_distance
            FROM stage_geometry
        """)

        row = cursor.fetchone()
        conn.close()

        return {
            'total_stages': row[0],
            'total_rallies': row[1],
            'avg_distance_km': row[2],
            'avg_hairpins': row[3],
            'avg_ascent_m': row[4],
            'min_distance_km': row[5],
            'max_distance_km': row[6]
        }

    def delete_stage(self, stage_id: str) -> bool:
        """Delete a stage from the database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            DELETE FROM stage_geometry WHERE stage_id = ?
        """, [stage_id])

        affected = cursor.rowcount
        conn.commit()
        conn.close()

        return affected > 0


def main():
    """Test stage metadata manager."""
    import argparse

    parser = argparse.ArgumentParser(description="Stage metadata manager")
    parser.add_argument('--db-path', default='data/raw/rally_results.db',
                       help='Database path')
    parser.add_argument('--stats', action='store_true', help='Show statistics')
    parser.add_argument('--stage', type=str, help='Get specific stage')
    parser.add_argument('--rally', type=str, help='Get stages for rally')

    args = parser.parse_args()

    manager = StageMetadataManager(args.db_path)

    if args.stats:
        stats = manager.get_statistics()
        print("\nStage Metadata Statistics")
        print("=" * 50)
        print(f"  Total Stages: {stats['total_stages']}")
        print(f"  Total Rallies: {stats['total_rallies']}")
        print(f"  Avg Distance: {stats['avg_distance_km']:.2f} km")
        print(f"  Avg Hairpins: {stats['avg_hairpins']:.1f}")
        print(f"  Avg Ascent: {stats['avg_ascent_m']:.0f} m")

    elif args.stage:
        stage = manager.get_stage(args.stage)
        if stage:
            print(f"\nStage: {stage['stage_id']}")
            print("=" * 50)
            for key, value in stage.items():
                print(f"  {key}: {value}")
        else:
            print(f"Stage not found: {args.stage}")

    elif args.rally:
        stages = manager.get_rally_stages(args.rally)
        print(f"\nStages for Rally: {args.rally}")
        print("=" * 50)
        for stage in stages:
            print(f"  SS{stage['stage_number']}: {stage['stage_name']} "
                  f"({stage['distance_km']:.1f}km, {stage['hairpin_count']} hairpins)")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
