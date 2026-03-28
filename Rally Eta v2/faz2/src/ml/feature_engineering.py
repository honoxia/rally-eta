from __future__ import annotations

"""
Feature Engineering for LightGBM Geometric Correction Model.

Combines:
- Stage geometric features (from KML analysis)
- Driver geometry profile (lifetime characteristics)
- Baseline prediction components
"""
import sqlite3
import logging
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import sys

try:
    import pandas as pd
except ImportError:
    pd = None

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.data.stage_metadata_manager import StageMetadataManager
from src.baseline.driver_geometry_profiler import DriverGeometryProfiler

logger = logging.getLogger(__name__)


class FeatureEngineer:
    """
    Engineer features for LightGBM model.

    Creates feature vectors combining:
    1. Stage geometric features (hairpin, climb, curvature)
    2. Driver geometry profile (lifetime performance patterns)
    3. Baseline prediction (historical + momentum + surface)
    """

    # Features that will be used in the model
    STAGE_FEATURES = [
        'distance_km',
        'hairpin_count',
        'hairpin_density',
        'turn_count',
        'turn_density',
        'total_ascent',
        'total_descent',
        'elevation_gain',
        'max_grade',
        'avg_abs_grade',
        'avg_curvature',
        'max_curvature',
        'p95_curvature',
        'curvature_density',
        'straight_percentage',
        'curvy_percentage'
    ]

    DRIVER_PROFILE_FEATURES = [
        'driver_hairpin_perf',
        'driver_climb_perf',
        'driver_curvature_sens',
        'driver_grade_perf',
        'driver_profile_confidence'
    ]

    BASELINE_FEATURES = [
        'baseline_ratio',
        'momentum_factor',
        'surface_adjustment'
    ]

    CATEGORICAL_FEATURES = [
        'surface',
        'normalized_class'
    ]

    def __init__(self, db_path: str):
        """
        Initialize feature engineer.

        Args:
            db_path: Path to database
        """
        self.db_path = db_path
        self.metadata_manager = StageMetadataManager(db_path)
        self.geometry_profiler = DriverGeometryProfiler(db_path)

        # Cache for driver profiles
        self._driver_profile_cache = {}

    def create_features_for_prediction(self, driver_id: str, stage_id: str,
                                        baseline_ratio: float,
                                        momentum_factor: float = 1.0,
                                        surface_adjustment: float = 1.0,
                                        surface: str = 'gravel',
                                        normalized_class: str = 'Rally2') -> Optional[Dict]:
        """
        Create feature vector for a single prediction.

        Args:
            driver_id: Driver identifier
            stage_id: Stage identifier
            baseline_ratio: From baseline calculator
            momentum_factor: From momentum analyzer
            surface_adjustment: From surface calculator
            surface: Stage surface type
            normalized_class: Normalized car class

        Returns:
            Feature dictionary ready for model prediction
        """
        # 1. Get stage geometry
        stage_meta = self.metadata_manager.get_stage(stage_id)

        if not stage_meta:
            logger.warning(f"No geometry data for stage {stage_id}")
            return None

        # 2. Get driver profile
        driver_profile = self._get_driver_profile(driver_id)

        # 3. Build feature dict
        features = {}

        # Stage features
        for feat in self.STAGE_FEATURES:
            value = stage_meta.get(feat)
            features[feat] = value if value is not None else 0.0

        # Driver profile features
        if driver_profile:
            features['driver_hairpin_perf'] = driver_profile.hairpin_performance or 1.0
            features['driver_climb_perf'] = driver_profile.climb_performance or 1.0
            features['driver_curvature_sens'] = driver_profile.curvature_sensitivity or 1.0
            features['driver_grade_perf'] = driver_profile.grade_performance or 1.0
            features['driver_profile_confidence'] = self._confidence_to_numeric(
                driver_profile.confidence
            )
        else:
            # Default values when no profile available
            features['driver_hairpin_perf'] = 1.0
            features['driver_climb_perf'] = 1.0
            features['driver_curvature_sens'] = 1.0
            features['driver_grade_perf'] = 1.0
            features['driver_profile_confidence'] = 0.0

        # Baseline features
        features['baseline_ratio'] = baseline_ratio
        features['momentum_factor'] = momentum_factor
        features['surface_adjustment'] = surface_adjustment

        # Categorical features (will be encoded)
        features['surface'] = surface.lower()
        features['normalized_class'] = normalized_class

        # Interaction features
        features['hairpin_x_driver'] = features['hairpin_density'] * features['driver_hairpin_perf']
        features['climb_x_driver'] = features['total_ascent'] * features['driver_climb_perf']
        features['curvature_x_driver'] = features['p95_curvature'] * features['driver_curvature_sens']

        return features

    def create_training_dataset(self, min_stages: int = 10) -> Tuple[pd.DataFrame, pd.Series]:
        """
        Create training dataset from historical data.

        Joins stage_results with stages_metadata and driver profiles.

        Args:
            min_stages: Minimum stages per driver to include

        Returns:
            (X, y) where:
            - X: Feature DataFrame
            - y: Target Series (correction_factor = actual_ratio / baseline_ratio)
        """
        if pd is None:
            raise ImportError("pandas is required to create the training dataset")

        conn = sqlite3.connect(self.db_path)

        # Query to join stage results with geometry
        query = """
            SELECT
                COALESCE(sr.driver_id, sr.driver_name) as driver_id,
                COALESCE(sr.raw_driver_name, sr.driver_name) as driver_name,
                sr.rally_id,
                COALESCE(sr.stage_id, sr.rally_id || '_ss' || sr.stage_number) as stage_id,
                sr.car_class as normalized_class,
                sr.time_seconds,
                sr.status,
                sm.surface,
                sm.distance_km,
                sm.hairpin_count,
                sm.hairpin_density,
                sm.turn_count,
                sm.turn_density,
                sm.total_ascent,
                sm.total_descent,
                sm.max_grade,
                sm.avg_abs_grade,
                sm.avg_curvature,
                sm.max_curvature,
                sm.p95_curvature,
                sm.curvature_density,
                sm.straight_percentage,
                sm.curvy_percentage
            FROM stage_results sr
            INNER JOIN stages_metadata sm
                ON COALESCE(sr.stage_id, sr.rally_id || '_ss' || sr.stage_number) = sm.stage_id
            WHERE sr.status IN ('FINISHED', 'OK')
            AND sr.time_seconds > 0
            AND sm.hairpin_density IS NOT NULL
        """

        df = pd.read_sql_query(query, conn)
        conn.close()

        logger.info(f"Loaded {len(df)} records with geometry data")

        if len(df) == 0:
            logger.error("No training data available")
            return pd.DataFrame(), pd.Series()

        # Filter drivers with enough stages
        driver_counts = df['driver_id'].value_counts()
        valid_drivers = driver_counts[driver_counts >= min_stages].index
        df = df[df['driver_id'].isin(valid_drivers)]

        logger.info(f"After filtering: {len(df)} records from {len(valid_drivers)} drivers")

        # Add driver profile features
        df = self._add_driver_profiles(df)

        # Calculate baseline ratio for each record (simplified: use rolling average)
        df = self._calculate_historical_baselines(df)

        # Calculate target: correction_factor = actual_ratio / baseline_ratio
        df['correction_factor'] = df['actual_ratio'] / df['baseline_ratio']

        # Filter extreme values
        df = df[(df['correction_factor'] > 0.8) & (df['correction_factor'] < 1.2)]

        # Add interaction features
        df['hairpin_x_driver'] = df['hairpin_density'] * df['driver_hairpin_perf']
        df['climb_x_driver'] = df['total_ascent'] * df['driver_climb_perf']
        df['curvature_x_driver'] = df['p95_curvature'] * df['driver_curvature_sens']

        # Prepare feature matrix
        feature_cols = (
            self.STAGE_FEATURES +
            self.DRIVER_PROFILE_FEATURES +
            self.BASELINE_FEATURES +
            ['hairpin_x_driver', 'climb_x_driver', 'curvature_x_driver']
        )

        X = df[feature_cols].copy()
        y = df['correction_factor'].copy()

        # Handle categorical features separately
        X['surface'] = df['surface'].fillna('unknown').str.lower()
        X['normalized_class'] = df['normalized_class'].fillna('Unknown')

        # Fill NaN with 0 for numeric features
        X = X.fillna(0)

        logger.info(f"Training dataset: {len(X)} samples, {len(X.columns)} features")

        return X, y

    def _get_driver_profile(self, driver_id: str):
        """Get driver profile with caching."""
        if driver_id not in self._driver_profile_cache:
            profile = self.geometry_profiler.create_profile(driver_id)
            self._driver_profile_cache[driver_id] = profile

        return self._driver_profile_cache[driver_id]

    def _confidence_to_numeric(self, confidence: str) -> float:
        """Convert confidence level to numeric value."""
        mapping = {
            'HIGH': 1.0,
            'MEDIUM': 0.7,
            'LOW': 0.4,
            'INSUFFICIENT': 0.1
        }
        return mapping.get(confidence, 0.5)

    def _add_driver_profiles(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add driver profile features to DataFrame."""
        if pd is None:
            raise ImportError("pandas is required to add driver profiles")

        # Get unique drivers
        drivers = df['driver_id'].unique()

        # Create profile dict
        profile_data = {
            'driver_id': [],
            'driver_hairpin_perf': [],
            'driver_climb_perf': [],
            'driver_curvature_sens': [],
            'driver_grade_perf': [],
            'driver_profile_confidence': []
        }

        for driver_id in drivers:
            profile = self._get_driver_profile(driver_id)

            profile_data['driver_id'].append(driver_id)

            if profile:
                profile_data['driver_hairpin_perf'].append(profile.hairpin_performance or 1.0)
                profile_data['driver_climb_perf'].append(profile.climb_performance or 1.0)
                profile_data['driver_curvature_sens'].append(profile.curvature_sensitivity or 1.0)
                profile_data['driver_grade_perf'].append(profile.grade_performance or 1.0)
                profile_data['driver_profile_confidence'].append(
                    self._confidence_to_numeric(profile.confidence)
                )
            else:
                profile_data['driver_hairpin_perf'].append(1.0)
                profile_data['driver_climb_perf'].append(1.0)
                profile_data['driver_curvature_sens'].append(1.0)
                profile_data['driver_grade_perf'].append(1.0)
                profile_data['driver_profile_confidence'].append(0.0)

        profile_df = pd.DataFrame(profile_data)

        # Merge with main DataFrame
        df = df.merge(profile_df, on='driver_id', how='left')

        return df

    def _calculate_historical_baselines(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate baseline ratio for each record.

        Uses rolling average of previous stages (simplified approach).
        """
        if pd is None:
            raise ImportError("pandas is required to calculate historical baselines")

        # Sort by driver and date
        df = df.sort_values(['driver_id', 'rally_id', 'stage_id'])

        # Calculate rolling baseline per driver
        baselines = []

        for driver_id in df['driver_id'].unique():
            driver_df = df[df['driver_id'] == driver_id].copy()

            # Use expanding mean of previous ratios
            driver_df['baseline_ratio'] = (
                driver_df['actual_ratio']
                .expanding(min_periods=1)
                .mean()
                .shift(1)  # Don't include current stage
            )

            # Fill first stage with driver's overall mean
            overall_mean = driver_df['actual_ratio'].mean()
            driver_df['baseline_ratio'] = driver_df['baseline_ratio'].fillna(overall_mean)

            baselines.append(driver_df)

        df = pd.concat(baselines, ignore_index=True)

        # Add default momentum and surface adjustment
        df['momentum_factor'] = 1.0
        df['surface_adjustment'] = 1.0

        return df

    def get_feature_names(self) -> List[str]:
        """Get list of all feature names."""
        return (
            self.STAGE_FEATURES +
            self.DRIVER_PROFILE_FEATURES +
            self.BASELINE_FEATURES +
            ['hairpin_x_driver', 'climb_x_driver', 'curvature_x_driver'] +
            self.CATEGORICAL_FEATURES
        )


def main():
    """Test feature engineering."""
    import argparse

    parser = argparse.ArgumentParser(description="Feature Engineering")
    parser.add_argument('--db-path', default='data/raw/rally_results.db',
                       help='Database path')
    parser.add_argument('--create-dataset', action='store_true',
                       help='Create training dataset')
    parser.add_argument('--driver-id', type=str, help='Test for specific driver')
    parser.add_argument('--stage-id', type=str, help='Test for specific stage')

    args = parser.parse_args()

    engineer = FeatureEngineer(args.db_path)

    if args.create_dataset:
        print("Creating training dataset...")
        X, y = engineer.create_training_dataset()

        print(f"\nDataset shape: {X.shape}")
        print(f"\nFeature columns:")
        for col in X.columns:
            print(f"  - {col}")

        print(f"\nTarget statistics:")
        print(f"  Mean: {y.mean():.4f}")
        print(f"  Std: {y.std():.4f}")
        print(f"  Min: {y.min():.4f}")
        print(f"  Max: {y.max():.4f}")

    elif args.driver_id and args.stage_id:
        print(f"Creating features for {args.driver_id} / {args.stage_id}...")

        features = engineer.create_features_for_prediction(
            driver_id=args.driver_id,
            stage_id=args.stage_id,
            baseline_ratio=1.05,
            momentum_factor=1.01,
            surface_adjustment=0.98
        )

        if features:
            print("\nFeatures:")
            for key, value in sorted(features.items()):
                if isinstance(value, float):
                    print(f"  {key}: {value:.4f}")
                else:
                    print(f"  {key}: {value}")
        else:
            print("Could not create features")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
