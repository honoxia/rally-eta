"""
Bulk KML/KMZ file processor.

Processes multiple KML files and stores geometric data in database.
"""
import logging
import argparse
import re
from pathlib import Path
import sys

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.data.geometric_analyzer import GeometricAnalyzer
from src.data.stage_metadata_manager import StageMetadataManager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def parse_stage_info_from_filename(filename: str) -> dict:
    """
    Extract stage information from filename.

    Expected formats:
    - SS1_Bodrum.kml
    - bodrum_2025_ss3.kml
    - rally97_stage2.kmz
    - SS01.kml

    Returns:
        {
            'stage_number': 1,
            'stage_name': 'Bodrum',
            'rally_hint': '97'  # if found
        }
    """
    name = Path(filename).stem

    result = {
        'stage_number': None,
        'stage_name': name,
        'rally_hint': None
    }

    # Try to extract SS number
    ss_match = re.search(r'[Ss][Ss](\d+)', name)
    if ss_match:
        result['stage_number'] = int(ss_match.group(1))

    # Try stage_N pattern
    stage_match = re.search(r'stage[_-]?(\d+)', name, re.IGNORECASE)
    if stage_match and not result['stage_number']:
        result['stage_number'] = int(stage_match.group(1))

    # Try to extract rally identifier
    rally_match = re.search(r'rally[_-]?(\d+)', name, re.IGNORECASE)
    if rally_match:
        result['rally_hint'] = rally_match.group(1)

    # Year pattern
    year_match = re.search(r'(20\d{2})', name)
    if year_match:
        result['year'] = year_match.group(1)

    return result


def process_single_file(kml_path: Path, analyzer: GeometricAnalyzer,
                       manager: StageMetadataManager, rally_id: str,
                       surface: str = None, dry_run: bool = False) -> bool:
    """
    Process a single KML file.

    Args:
        kml_path: Path to KML/KMZ file
        analyzer: GeometricAnalyzer instance
        manager: StageMetadataManager instance
        rally_id: Rally identifier
        surface: Surface type (gravel, asphalt, snow)
        dry_run: If True, don't write to database

    Returns:
        True if successful
    """
    logger.info(f"Processing: {kml_path.name}")

    # Analyze file
    geometry = analyzer.analyze_file(str(kml_path))

    if not geometry:
        logger.warning(f"Failed to analyze: {kml_path.name}")
        return False

    # Parse stage info from filename
    stage_info = parse_stage_info_from_filename(kml_path.name)

    # Create stage ID
    stage_number = stage_info['stage_number'] or 0
    stage_id = f"{rally_id}_ss{stage_number}"

    # Print summary
    print(f"\n{'=' * 60}")
    print(f"Stage: {geometry.name}")
    print(f"Stage ID: {stage_id}")
    print(f"{'=' * 60}")
    print(f"  Distance: {geometry.distance_km:.2f} km")
    print(f"  Hairpins: {geometry.hairpin_count} ({geometry.hairpin_density:.2f}/km)")
    print(f"  Turns: {geometry.turn_count} ({geometry.turn_density:.2f}/km)")
    print(f"  Ascent: {geometry.total_ascent:.0f} m")
    print(f"  Descent: {geometry.total_descent:.0f} m")
    print(f"  Max Grade: {geometry.max_grade:.1f}%")
    print(f"  Curvature (P95): {geometry.p95_curvature:.4f}")

    if dry_run:
        print("  [DRY RUN - Not saving to database]")
        return True

    # Save to database
    success = manager.insert_from_geometry(
        geometry=geometry,
        stage_id=stage_id,
        rally_id=rally_id,
        stage_number=stage_number,
        surface=surface,
        kml_file=str(kml_path)
    )

    if success:
        print(f"  ✓ Saved to database")
    else:
        print(f"  ✗ Failed to save")

    return success


def process_directory(kml_dir: Path, analyzer: GeometricAnalyzer,
                     manager: StageMetadataManager, rally_id: str,
                     surface: str = None, dry_run: bool = False) -> dict:
    """
    Process all KML files in a directory.

    Args:
        kml_dir: Directory containing KML files
        analyzer: GeometricAnalyzer instance
        manager: StageMetadataManager instance
        rally_id: Rally identifier
        surface: Surface type
        dry_run: If True, don't write to database

    Returns:
        {
            'processed': 10,
            'success': 8,
            'failed': 2,
            'files': [...]
        }
    """
    # Find all KML/KMZ files
    kml_files = list(kml_dir.glob('*.kml')) + list(kml_dir.glob('*.kmz'))
    kml_files = sorted(kml_files)

    logger.info(f"Found {len(kml_files)} KML/KMZ files in {kml_dir}")

    results = {
        'processed': 0,
        'success': 0,
        'failed': 0,
        'files': []
    }

    for kml_path in kml_files:
        success = process_single_file(
            kml_path=kml_path,
            analyzer=analyzer,
            manager=manager,
            rally_id=rally_id,
            surface=surface,
            dry_run=dry_run
        )

        results['processed'] += 1
        results['files'].append({
            'file': kml_path.name,
            'success': success
        })

        if success:
            results['success'] += 1
        else:
            results['failed'] += 1

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Process KML/KMZ files and store geometric data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process single file
  python process_kml_files.py --file stage_ss1.kml --rally-id bodrum_2025 --surface gravel

  # Process directory
  python process_kml_files.py --dir ./kml_files/ --rally-id bodrum_2025 --surface gravel

  # Dry run (preview only)
  python process_kml_files.py --dir ./kml_files/ --rally-id test --dry-run
        """
    )

    parser.add_argument('--file', type=str, help='Single KML/KMZ file to process')
    parser.add_argument('--dir', type=str, help='Directory containing KML files')
    parser.add_argument('--rally-id', type=str, required=True, help='Rally identifier')
    parser.add_argument('--rally-name', type=str, help='Rally name')
    parser.add_argument('--surface', type=str, choices=['gravel', 'asphalt', 'snow'],
                       help='Surface type')
    parser.add_argument('--db-path', type=str, default='data/raw/rally_results.db',
                       help='Database path')
    parser.add_argument('--dry-run', action='store_true',
                       help='Preview without writing to database')

    args = parser.parse_args()

    if not args.file and not args.dir:
        parser.error("Either --file or --dir must be specified")

    # Initialize components
    analyzer = GeometricAnalyzer()
    manager = StageMetadataManager(args.db_path)

    if args.dry_run:
        print("\n" + "=" * 60)
        print("DRY RUN MODE - No changes will be saved to database")
        print("=" * 60)

    if args.file:
        # Process single file
        kml_path = Path(args.file)
        if not kml_path.exists():
            logger.error(f"File not found: {args.file}")
            return

        success = process_single_file(
            kml_path=kml_path,
            analyzer=analyzer,
            manager=manager,
            rally_id=args.rally_id,
            surface=args.surface,
            dry_run=args.dry_run
        )

        if success:
            print("\n✓ Processing complete")
        else:
            print("\n✗ Processing failed")

    elif args.dir:
        # Process directory
        kml_dir = Path(args.dir)
        if not kml_dir.exists():
            logger.error(f"Directory not found: {args.dir}")
            return

        results = process_directory(
            kml_dir=kml_dir,
            analyzer=analyzer,
            manager=manager,
            rally_id=args.rally_id,
            surface=args.surface,
            dry_run=args.dry_run
        )

        # Summary
        print("\n" + "=" * 60)
        print("PROCESSING SUMMARY")
        print("=" * 60)
        print(f"  Total files: {results['processed']}")
        print(f"  Successful: {results['success']}")
        print(f"  Failed: {results['failed']}")

        if not args.dry_run:
            stats = manager.get_statistics()
            print(f"\nDatabase now contains:")
            print(f"  {stats['total_stages']} stages from {stats['total_rallies']} rallies")


if __name__ == '__main__':
    main()
