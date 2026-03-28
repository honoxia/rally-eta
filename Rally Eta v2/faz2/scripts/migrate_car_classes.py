"""
Database migration: Add normalized_class column and populate.
"""
import sqlite3
import logging
from pathlib import Path
import sys

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from src.data.car_class_normalizer import CarClassNormalizer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def migrate_car_classes(db_path: str, dry_run: bool = False):
    """
    Add normalized_class column and populate.

    Args:
        db_path: Path to database
        dry_run: If True, only show changes without applying
    """
    logger.info(f"Connecting to database: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check if column already exists
    cursor.execute("PRAGMA table_info(stage_results)")
    columns = [row[1] for row in cursor.fetchall()]

    if 'normalized_class' in columns:
        logger.warning("normalized_class column already exists")
        response = input("Drop and recreate? (y/n): ")
        if response.lower() != 'y':
            logger.info("Migration cancelled")
            conn.close()
            return
        cursor.execute("ALTER TABLE stage_results DROP COLUMN normalized_class")

    # Add column
    logger.info("Adding normalized_class column...")
    if not dry_run:
        cursor.execute("""
            ALTER TABLE stage_results
            ADD COLUMN normalized_class TEXT
        """)
        conn.commit()

    # Get all unique car classes
    cursor.execute("SELECT DISTINCT car_class FROM stage_results WHERE car_class IS NOT NULL")
    unique_classes = [row[0] for row in cursor.fetchall()]

    logger.info(f"Found {len(unique_classes)} unique car classes")

    # Normalize each class
    normalizer = CarClassNormalizer()
    normalization_map = {}

    print("\nNormalization Preview:")
    print("=" * 60)

    for raw_class in sorted(unique_classes):
        normalized = normalizer.normalize(raw_class)
        normalization_map[raw_class] = normalized
        print(f"  '{raw_class:30s}' → '{normalized}'")

    print("=" * 60)

    if dry_run:
        logger.info("DRY RUN - No changes applied")
        conn.close()
        return

    # Apply normalization
    logger.info("Applying normalization...")

    for raw_class, normalized in normalization_map.items():
        cursor.execute("""
            UPDATE stage_results
            SET normalized_class = ?
            WHERE car_class = ?
        """, [normalized, raw_class])

    conn.commit()

    # Create index
    logger.info("Creating index on normalized_class...")
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_normalized_class
        ON stage_results(normalized_class)
    """)
    conn.commit()

    # Generate summary report
    cursor.execute("""
        SELECT
            car_class,
            normalized_class,
            COUNT(*) as count
        FROM stage_results
        WHERE car_class IS NOT NULL
        GROUP BY car_class, normalized_class
        ORDER BY normalized_class, count DESC
    """)

    print("\n\nMigration Summary:")
    print("=" * 60)

    results = cursor.fetchall()
    for row in results:
        print(f"  {row[0]:30s} → {row[1]:10s} ({row[2]:5d} records)")

    # Count by normalized class
    cursor.execute("""
        SELECT
            normalized_class,
            COUNT(*) as total
        FROM stage_results
        WHERE normalized_class IS NOT NULL
        GROUP BY normalized_class
        ORDER BY total DESC
    """)

    print("\n\nBy Normalized Class:")
    print("=" * 60)

    for row in cursor.fetchall():
        print(f"  {row[0]:10s}: {row[1]:6d} records")

    conn.close()
    logger.info("Migration complete!")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Migrate car classes")
    parser.add_argument('--db-path', type=str,
                       default='data/raw/rally_results.db',
                       help='Database path')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show changes without applying')

    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        logger.error(f"Database not found: {db_path}")
        return

    migrate_car_classes(str(db_path), args.dry_run)


if __name__ == '__main__':
    main()
