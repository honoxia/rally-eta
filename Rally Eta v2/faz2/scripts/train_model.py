"""
Train LightGBM Geometric Correction Model.

Usage:
    python scripts/train_model.py --db-path data/raw/rally_results.db
    python scripts/train_model.py --db-path data/raw/rally_results.db --output models/correction_model
"""
import logging
import argparse
from pathlib import Path
import sys
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.ml.feature_engineering import FeatureEngineer
from src.ml.geometric_correction_model import GeometricCorrectionModel

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def train_model(db_path: str, output_path: str, min_stages: int = 10,
                validation_split: float = 0.2) -> dict:
    """
    Train the geometric correction model.

    Args:
        db_path: Path to database
        output_path: Path to save trained model
        min_stages: Minimum stages per driver
        validation_split: Validation set fraction

    Returns:
        Training metrics
    """
    print("\n" + "=" * 60)
    print("GEOMETRIC CORRECTION MODEL TRAINING")
    print("=" * 60)
    print(f"\nDatabase: {db_path}")
    print(f"Output: {output_path}")
    print(f"Min stages per driver: {min_stages}")
    print(f"Validation split: {validation_split}")

    # 1. Create feature engineer
    print("\n" + "-" * 40)
    print("Step 1: Feature Engineering")
    print("-" * 40)

    engineer = FeatureEngineer(db_path)

    # 2. Create training dataset
    print("\nCreating training dataset...")
    X, y = engineer.create_training_dataset(min_stages=min_stages)

    if len(X) == 0:
        print("\n❌ ERROR: No training data available!")
        print("   Possible reasons:")
        print("   - No stage_results in database")
        print("   - No stages_metadata (run process_kml_files.py first)")
        print("   - ratio_to_class_best not calculated")
        return None

    print(f"\n✓ Dataset created:")
    print(f"  - Samples: {len(X)}")
    print(f"  - Features: {len(X.columns)}")

    print("\nFeature summary:")
    print(f"  - Stage features: {len(engineer.STAGE_FEATURES)}")
    print(f"  - Driver profile features: {len(engineer.DRIVER_PROFILE_FEATURES)}")
    print(f"  - Baseline features: {len(engineer.BASELINE_FEATURES)}")
    print(f"  - Categorical features: {len(engineer.CATEGORICAL_FEATURES)}")
    print(f"  - Interaction features: 3")

    print(f"\nTarget (correction_factor) statistics:")
    print(f"  - Mean: {y.mean():.4f}")
    print(f"  - Std: {y.std():.4f}")
    print(f"  - Min: {y.min():.4f}")
    print(f"  - Max: {y.max():.4f}")
    print(f"  - Median: {y.median():.4f}")

    # 3. Train model
    print("\n" + "-" * 40)
    print("Step 2: Model Training")
    print("-" * 40)

    model = GeometricCorrectionModel()
    print("\nTraining LightGBM model...")
    print("(This may take a few minutes)")

    metrics = model.train(
        X, y,
        validation_split=validation_split,
        early_stopping_rounds=50
    )

    print(f"\n✓ Training complete!")
    print(f"\nMetrics:")
    print(f"  - Train samples: {metrics['train_samples']}")
    print(f"  - Validation samples: {metrics['val_samples']}")
    print(f"  - Train MAE: {metrics['train_mae']:.4f}")
    print(f"  - Val MAE: {metrics['val_mae']:.4f}")
    print(f"  - Train MAPE: {metrics['train_mape']:.2f}%")
    print(f"  - Val MAPE: {metrics['val_mape']:.2f}%")
    print(f"  - Best iteration: {metrics['best_iteration']}")

    # 4. Feature importance
    print("\n" + "-" * 40)
    print("Step 3: Feature Importance")
    print("-" * 40)

    importance = model.get_feature_importance()
    print("\nTop 15 most important features:")
    for i, (feat, imp) in enumerate(list(importance.items())[:15], 1):
        bar = "█" * int(imp / max(importance.values()) * 20)
        print(f"  {i:2d}. {feat:30s} {imp:8.1f} {bar}")

    # 5. Save model
    print("\n" + "-" * 40)
    print("Step 4: Save Model")
    print("-" * 40)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    model.save(str(output_path))

    print(f"\n✓ Model saved to:")
    print(f"  - {output_path.with_suffix('.pkl')}")
    print(f"  - {output_path.with_suffix('.json')}")

    # 6. Summary
    print("\n" + "=" * 60)
    print("TRAINING SUMMARY")
    print("=" * 60)

    # Assess model quality
    if metrics['val_mape'] < 1.0:
        quality = "EXCELLENT"
        emoji = "🟢"
    elif metrics['val_mape'] < 2.0:
        quality = "GOOD"
        emoji = "🟢"
    elif metrics['val_mape'] < 3.0:
        quality = "ACCEPTABLE"
        emoji = "🟡"
    else:
        quality = "NEEDS IMPROVEMENT"
        emoji = "🔴"

    print(f"\nModel Quality: {quality} {emoji}")
    print(f"Validation MAPE: {metrics['val_mape']:.2f}%")

    # Overfitting check
    overfit_ratio = metrics['train_mae'] / metrics['val_mae']
    if overfit_ratio < 0.7:
        print(f"⚠️  Possible underfitting (train/val ratio: {overfit_ratio:.2f})")
    elif overfit_ratio > 0.95:
        print(f"⚠️  Possible overfitting (train/val ratio: {overfit_ratio:.2f})")
    else:
        print(f"✓ Good generalization (train/val ratio: {overfit_ratio:.2f})")

    # Recommendations
    print("\nRecommendations:")

    if len(X) < 1000:
        print("  - Consider adding more training data (e-wrc.com scraping)")

    if metrics['val_mape'] > 2.0:
        print("  - Consider more KML data for better geometric features")
        print("  - Review data quality for outliers")

    print(f"\nNext steps:")
    print(f"  1. Use model for predictions in baseline_predictor.py")
    print(f"  2. Add SHAP explanations with shap_explainer.py")
    print(f"  3. Monitor performance on new rallies")

    return metrics


def main():
    parser = argparse.ArgumentParser(
        description="Train LightGBM Geometric Correction Model",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Train with default settings
  python scripts/train_model.py --db-path data/raw/rally_results.db

  # Train with custom output path
  python scripts/train_model.py --db-path data/raw/rally_results.db --output models/v2_model

  # Train with more data per driver
  python scripts/train_model.py --db-path data/raw/rally_results.db --min-stages 15
        """
    )

    parser.add_argument('--db-path', type=str,
                       default='data/raw/rally_results.db',
                       help='Path to database')
    parser.add_argument('--output', type=str,
                       default='models/geometric_correction',
                       help='Output path for model (without extension)')
    parser.add_argument('--min-stages', type=int, default=10,
                       help='Minimum stages per driver to include')
    parser.add_argument('--val-split', type=float, default=0.2,
                       help='Validation set fraction')

    args = parser.parse_args()

    # Check database exists
    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"❌ ERROR: Database not found: {db_path}")
        print("\nMake sure to:")
        print("  1. Run the scraper to populate stage_results")
        print("  2. Run process_kml_files.py to populate stages_metadata")
        return

    # Train
    metrics = train_model(
        db_path=str(db_path),
        output_path=args.output,
        min_stages=args.min_stages,
        validation_split=args.val_split
    )

    if metrics:
        print("\n✓ Training completed successfully!")
    else:
        print("\n❌ Training failed!")


if __name__ == '__main__':
    main()
