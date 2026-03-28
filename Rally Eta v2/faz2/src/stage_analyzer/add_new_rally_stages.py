"""
RallyETA v2 - Add New Rally Stages
Analyzes KML files and adds stage metadata to the database.

Usage:
    python src/stage_analyzer/add_new_rally_stages.py --mapping-csv data/mappings/bodrum_2026_stages.csv

The mapping CSV should have columns:
    rally_id, stage_name, kml_file, base_stage_name, pass_number
"""

import argparse
import pandas as pd
import sqlite3
from pathlib import Path
from datetime import datetime
import sys

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from src.stage_analyzer.kml_analyzer import KMLAnalyzer


class StageMetadataManager:
    """Manages stage metadata extraction and database insertion."""

    def __init__(self, db_path: str):
        """
        Initialize the manager.

        Args:
            db_path: Path to the SQLite database
        """
        self.db_path = db_path
        self.analyzer = KMLAnalyzer(geom_step=10.0, smoothing_window=7)

    def process_mapping_csv(self, mapping_csv: str, dry_run: bool = False):
        """
        Process a mapping CSV and add all stages to the database.

        Args:
            mapping_csv: Path to mapping CSV file
            dry_run: If True, only analyze but don't insert to database
        """
        # Read mapping CSV
        df = pd.read_csv(mapping_csv)

        # Validate columns
        required_cols = ['rally_id', 'stage_name', 'kml_file', 'base_stage_name', 'pass_number']
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            raise ValueError(f"Missing required columns in CSV: {missing_cols}")

        print(f"\n{'='*60}")
        print(f"Processing {len(df)} stages from: {mapping_csv}")
        print(f"{'='*60}\n")

        # Process each stage
        results = []
        for idx, row in df.iterrows():
            print(f"[{idx+1}/{len(df)}] Analyzing: {row['stage_name']}")

            try:
                # Analyze KML
                kml_path = Path(row['kml_file'])
                if not kml_path.is_absolute():
                    # Relative to project root
                    kml_path = project_root / kml_path

                if not kml_path.exists():
                    print(f"  ⚠ Warning: KML file not found: {kml_path}")
                    print(f"  Skipping...\n")
                    continue

                features = self.analyzer.analyze_kml(str(kml_path))

                # Create stage_id
                rally_id = row['rally_id']
                stage_name_clean = row['stage_name'].lower().replace(' ', '_').replace('ss', '')
                stage_id = f"{rally_id}_ss{stage_name_clean}"

                # Prepare metadata
                metadata = {
                    'stage_id': stage_id,
                    'rally_id': rally_id,
                    'stage_name': row['stage_name'],
                    'base_stage_name': row['base_stage_name'],
                    'pass_number': int(row['pass_number']),
                    **features
                }

                results.append(metadata)

                # Print summary
                print(f"  ✓ Distance: {features['distance_km']:.2f} km")
                print(f"  ✓ Hairpins: {features['hairpin_count']} ({features['hairpin_density']:.2f}/km)")
                print(f"  ✓ Curvature Density: {features['curvature_density']:.3f} 1/km")
                print(f"  ✓ Geometry Samples: {features['geometry_samples']}\n")

            except Exception as e:
                print(f"  ✗ Error: {str(e)}\n")
                continue

        # Insert to database
        if not dry_run and results:
            print(f"{'='*60}")
            print(f"Inserting {len(results)} stages to database...")
            print(f"{'='*60}\n")

            self._insert_to_database(results)

            print(f"✓ Successfully added {len(results)} stages to database\n")
        elif dry_run:
            print(f"\n{'='*60}")
            print(f"DRY RUN: Would insert {len(results)} stages")
            print(f"{'='*60}\n")
        else:
            print(f"\n⚠ No stages to insert\n")

        return results

    def _insert_to_database(self, metadata_list: list):
        """
        Insert stage metadata to database.

        Args:
            metadata_list: List of metadata dictionaries
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Check if table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='stages_metadata'")
        if not cursor.fetchone():
            raise RuntimeError(
                "stages_metadata table does not exist. "
                "Run: python scripts/create_database_schema.py"
            )

        # Insert or replace each stage
        for metadata in metadata_list:
            # Check if stage already exists
            cursor.execute("SELECT stage_id FROM stages_metadata WHERE stage_id = ?", (metadata['stage_id'],))
            exists = cursor.fetchone()

            if exists:
                print(f"  ⚠ Stage {metadata['stage_id']} already exists, replacing...")

            # Insert or replace
            columns = list(metadata.keys())
            placeholders = ', '.join(['?' for _ in columns])
            column_names = ', '.join(columns)

            query = f"""
                INSERT OR REPLACE INTO stages_metadata ({column_names})
                VALUES ({placeholders})
            """

            cursor.execute(query, list(metadata.values()))

        conn.commit()
        conn.close()

    def list_stages(self, rally_id: str = None):
        """
        List stages in the database.

        Args:
            rally_id: Optional rally ID filter
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        if rally_id:
            query = "SELECT * FROM stages_metadata WHERE rally_id = ? ORDER BY stage_id"
            cursor.execute(query, (rally_id,))
        else:
            query = "SELECT * FROM stages_metadata ORDER BY rally_id, stage_id"
            cursor.execute(query)

        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]

        conn.close()

        if not rows:
            print("No stages found in database")
            return

        # Convert to DataFrame for nice display
        df = pd.DataFrame(rows, columns=columns)

        # Select key columns for display
        display_cols = [
            'stage_id', 'rally_id', 'stage_name', 'pass_number',
            'distance_km', 'hairpin_count', 'curvature_density',
            'total_ascent', 'total_descent'
        ]
        display_cols = [col for col in display_cols if col in df.columns]

        print(f"\n{'='*80}")
        print(f"STAGES IN DATABASE: {len(df)} total")
        print(f"{'='*80}\n")

        print(df[display_cols].to_string(index=False))
        print()


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description="Add new rally stages to RallyETA v2 database"
    )
    parser.add_argument(
        '--mapping-csv',
        type=str,
        help='Path to mapping CSV file'
    )
    parser.add_argument(
        '--list',
        action='store_true',
        help='List all stages in database'
    )
    parser.add_argument(
        '--rally-id',
        type=str,
        help='Filter by rally ID (use with --list)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Analyze KML files but do not insert to database'
    )
    parser.add_argument(
        '--db-path',
        type=str,
        default=None,
        help='Path to database (default: data/raw/rally_results.db)'
    )

    args = parser.parse_args()

    # Determine database path
    if args.db_path:
        db_path = Path(args.db_path)
    else:
        db_path = project_root / "data" / "raw" / "rally_results.db"

    if not db_path.exists():
        print(f"Error: Database not found at {db_path}")
        print("Run: python scripts/create_database_schema.py")
        sys.exit(1)

    manager = StageMetadataManager(str(db_path))

    # List mode
    if args.list:
        manager.list_stages(rally_id=args.rally_id)
        return

    # Process mode
    if not args.mapping_csv:
        print("Error: --mapping-csv is required (or use --list to view stages)")
        parser.print_help()
        sys.exit(1)

    mapping_csv = Path(args.mapping_csv)
    if not mapping_csv.exists():
        print(f"Error: Mapping CSV not found: {mapping_csv}")
        sys.exit(1)

    # Process mapping CSV
    manager.process_mapping_csv(str(mapping_csv), dry_run=args.dry_run)

    print("Done!")


if __name__ == "__main__":
    main()
