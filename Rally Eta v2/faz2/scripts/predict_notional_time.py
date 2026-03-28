"""
Main entry point for Notional Time Prediction.

Usage:
    # Single prediction
    python scripts/predict_notional_time.py \
        --driver-id "kerem_kazaz" \
        --driver-name "Kerem Kazaz" \
        --rally-id "bodrum_2025" \
        --stage-id "SS3" \
        --stage-name "SS3 - Catalca" \
        --stage-number 3 \
        --car-class "Rally2"

    # Batch prediction from file
    python scripts/predict_notional_time.py \
        --batch drivers.json \
        --rally-id "bodrum_2025" \
        --stage-id "SS3" \
        --output predictions.xlsx
"""
import logging
import argparse
import json
from pathlib import Path
import sys

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.prediction.notional_time_predictor import NotionalTimePredictor
from src.export.excel_exporter import ExcelExporter

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def predict_single(args):
    """Run single prediction."""
    print("\n" + "=" * 60)
    print("RALLY ETA v2.0 - NOTIONAL TIME PREDICTION")
    print("=" * 60)

    print(f"\nDatabase: {args.db_path}")
    print(f"Model: {args.model_path or 'None (baseline-only mode)'}")
    print(f"Driver: {args.driver_name}")
    print(f"Stage: {args.stage_name}")

    # Initialize predictor
    predictor = NotionalTimePredictor(
        db_path=args.db_path,
        model_path=args.model_path
    )

    # Run prediction
    print("\n" + "-" * 40)
    print("Running prediction...")
    print("-" * 40)

    try:
        result = predictor.predict(
            driver_id=args.driver_id,
            driver_name=args.driver_name,
            rally_id=args.rally_id,
            stage_id=args.stage_id,
            stage_name=args.stage_name,
            current_stage_number=args.stage_number,
            normalized_class=args.car_class,
            surface=args.surface
        )

        # Display results
        print("\n" + "=" * 60)
        print("PREDICTION RESULT")
        print("=" * 60)

        print(f"\n{result.summary_text}")

        print("\n" + "-" * 40)
        print("PREDICTION DETAILS")
        print("-" * 40)
        print(f"Predicted Time: {result.predicted_time_str}")
        print(f"Final Ratio: {result.predicted_ratio:.4f}")
        print(f"Class Best: {result.class_best_str} ({result.class_best_driver})")

        print("\n" + "-" * 40)
        print("COMPONENT BREAKDOWN")
        print("-" * 40)
        print(f"Baseline Ratio: {result.baseline_ratio:.4f}")
        print(f"Momentum Factor: {result.momentum_factor:.4f}")
        print(f"Surface Adjustment: {result.surface_adjustment:.4f}")
        print(f"Geometric Correction: {result.geometric_correction:.4f} ({result.geometric_mode})")

        print("\n" + "-" * 40)
        print("CONFIDENCE")
        print("-" * 40)
        print(f"Level: {result.confidence.level} ({result.confidence.score}/100) {result.confidence.emoji}")
        for reason in result.confidence.reasons:
            if reason:
                print(f"  - {reason}")

        # Export to Excel if requested
        if args.output:
            exporter = ExcelExporter()
            exporter.export_prediction(result, args.output)
            print(f"\nExcel exported to: {args.output}")

        # Show detailed explanation if verbose
        if args.verbose:
            print("\n" + "=" * 60)
            print("DETAILED EXPLANATION")
            print("=" * 60)
            print(result.detailed_text)

        return result

    except Exception as e:
        logger.error(f"Prediction failed: {e}")
        raise


def predict_batch(args):
    """Run batch prediction from file."""
    print("\n" + "=" * 60)
    print("RALLY ETA v2.0 - BATCH PREDICTION")
    print("=" * 60)

    # Load drivers from file
    with open(args.batch, 'r', encoding='utf-8') as f:
        data = json.load(f)

    drivers = data.get('drivers', data)
    rally_id = args.rally_id or data.get('rally_id')
    stage_id = args.stage_id or data.get('stage_id')
    stage_name = args.stage_name or data.get('stage_name', stage_id)
    stage_number = args.stage_number or data.get('stage_number', 3)

    print(f"\nRally: {rally_id}")
    print(f"Stage: {stage_name}")
    print(f"Drivers: {len(drivers)}")

    # Initialize predictor
    predictor = NotionalTimePredictor(
        db_path=args.db_path,
        model_path=args.model_path
    )

    # Run predictions
    print("\n" + "-" * 40)
    print("Running predictions...")
    print("-" * 40)

    results = predictor.predict_batch(
        drivers=drivers,
        rally_id=rally_id,
        stage_id=stage_id,
        stage_name=stage_name,
        current_stage_number=stage_number
    )

    # Display summary
    print("\n" + "=" * 60)
    print("BATCH PREDICTION SUMMARY")
    print("=" * 60)

    print(f"\nTotal predictions: {len(results)}")

    for result in results:
        print(f"\n  {result.driver_name}:")
        print(f"    Time: {result.predicted_time_str}")
        print(f"    Ratio: {result.predicted_ratio:.3f}")
        print(f"    Confidence: {result.confidence.level}")

    # Export to Excel
    if args.output:
        exporter = ExcelExporter()

        rally_name = data.get('rally_name', rally_id)
        exporter.export_batch(
            results,
            rally_name=rally_name,
            stage_name=stage_name,
            output_path=args.output
        )
        print(f"\nExcel exported to: {args.output}")

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Rally ETA v2.0 - Notional Time Prediction",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single prediction
  python scripts/predict_notional_time.py \\
      --driver-id "kerem_kazaz" \\
      --driver-name "Kerem Kazaz" \\
      --rally-id "97" \\
      --stage-id "SS3" \\
      --car-class "Rally2"

  # Batch prediction
  python scripts/predict_notional_time.py \\
      --batch drivers.json \\
      --output predictions.xlsx

  # With trained model
  python scripts/predict_notional_time.py \\
      --driver-id "test" \\
      --driver-name "Test Pilot" \\
      --rally-id "97" \\
      --stage-id "SS3" \\
      --car-class "Rally2" \\
      --model-path models/geometric_correction
        """
    )

    # Database and model
    parser.add_argument('--db-path', type=str,
                       default='data/raw/rally_results.db',
                       help='Path to database')
    parser.add_argument('--model-path', type=str,
                       help='Path to trained model (without extension)')

    # Single prediction arguments
    parser.add_argument('--driver-id', type=str,
                       help='Driver ID')
    parser.add_argument('--driver-name', type=str,
                       help='Driver name')
    parser.add_argument('--rally-id', type=str,
                       help='Rally ID')
    parser.add_argument('--stage-id', type=str,
                       help='Stage ID')
    parser.add_argument('--stage-name', type=str,
                       help='Stage name (default: stage-id)')
    parser.add_argument('--stage-number', type=int, default=3,
                       help='Stage number in rally')
    parser.add_argument('--car-class', type=str, default='Rally2',
                       help='Car class')
    parser.add_argument('--surface', type=str,
                       choices=['gravel', 'asphalt', 'snow'],
                       help='Stage surface (auto-detected if not provided)')

    # Batch prediction
    parser.add_argument('--batch', type=str,
                       help='Path to JSON file with drivers list')

    # Output
    parser.add_argument('--output', '-o', type=str,
                       help='Output Excel file path')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Show detailed explanation')

    args = parser.parse_args()

    # Validate arguments
    if args.batch:
        # Batch mode
        if not Path(args.batch).exists():
            print(f"Error: Batch file not found: {args.batch}")
            return

        predict_batch(args)

    elif args.driver_id and args.rally_id and args.stage_id:
        # Single mode
        if not args.driver_name:
            args.driver_name = args.driver_id

        if not args.stage_name:
            args.stage_name = args.stage_id

        predict_single(args)

    else:
        parser.print_help()
        print("\nError: Provide either --batch or (--driver-id, --rally-id, --stage-id)")


if __name__ == '__main__':
    main()
