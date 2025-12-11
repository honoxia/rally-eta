"""Feature engineering with temporal safety - Version 1.1 with short stage fixes"""
import pandas as pd
import numpy as np
import logging
from typing import Dict
from config.config_loader import config
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class FeatureEngineerV1_1:
    """
    Engineer features with strict temporal constraints

    Version 1.1 Changes:
    1. Nonlinear stage length correction (stage_km^0.85)
    2. Short stage flag and penalty factor
    3. Driver short-stage specific performance metric
    4. Driver momentum feature (recent 5 vs prev 5)
    """

    def __init__(self):
        self.lookback_stages = config.get('features.lookback_stages')
        self.min_history = config.get('features.min_history_for_stats')
        # v1.1: New parameters
        self.stage_length_power = config.get('features.stage_length_power')
        self.short_stage_km = config.get('features.short_stage_threshold_km')
        self.short_stage_penalty = config.get('features.short_stage_penalty_factor')
        self.momentum_lookback = config.get('features.momentum_lookback')

    def engineer_all(self, df: pd.DataFrame) -> pd.DataFrame:
        """Full feature engineering pipeline"""
        logger.info("[v1.1] Starting feature engineering...")

        # Generate IDs if missing
        if 'rally_id' not in df.columns:
            df['rally_id'] = df['rally_name'].str.lower().str.replace(' ', '_')
        if 'stage_id' not in df.columns:
            df['stage_id'] = df['rally_id'] + '_' + df['stage_name'].str.lower()
        if 'car_class' not in df.columns and 'car_model' in df.columns:
            # Extract class from model if needed
            logger.warning("car_class column missing, using default Rally2")
            df['car_class'] = 'Rally2'

        # Sort by date and stage
        df = df.sort_values(['rally_date', 'rally_id', 'stage_number'])

        # Calculate target
        df = self._calculate_target(df)

        # Add features
        df = self._add_stage_features(df)
        df = self._add_vehicle_features(df)
        df = self._add_driver_features_temporal(df)
        df = self._add_rally_context(df)
        df = self._add_competition_features(df)

        # Impute missing
        df = self._impute_missing(df)

        logger.info(f"[v1.1] Feature engineering complete: {len(df.columns)} columns")
        return df

    def _calculate_target(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate ratio_to_class_best"""
        logger.info("Calculating target variable...")

        # Save important columns before groupby (groupby with include_groups=False drops them)
        index_cols = df.set_index('result_id')[['car_class', 'rally_id', 'stage_id']].copy()

        def compute_class_best(group):
            # All data in clean_stage_results is already valid (anomalies removed)
            valid = group
            if len(valid) == 0:
                group['class_best_time'] = np.nan
                group['ratio_to_class_best'] = np.nan
            else:
                class_best = valid['time_seconds'].min()
                group['class_best_time'] = class_best
                group['ratio_to_class_best'] = group['time_seconds'] / class_best
            return group

        df = df.groupby(['rally_id', 'stage_id', 'car_class'], group_keys=False).apply(compute_class_best, include_groups=False)

        # Restore columns that were dropped by groupby
        for col in ['car_class', 'rally_id', 'stage_id']:
            if col not in df.columns and 'result_id' in df.columns:
                df = df.set_index('result_id')
                df[col] = index_cols[col]
                df = df.reset_index()

        # Remove rows where target can't be calculated
        df = df[df['ratio_to_class_best'].notna()].copy()

        logger.info(f"Target calculated for {len(df)} results")
        return df

    def _add_stage_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add stage characteristics (v1.1: with short stage corrections)"""
        df['surface_asphalt'] = (df['surface'] == 'asphalt').astype(int)
        df['surface_gravel'] = (df['surface'] == 'gravel').astype(int)
        df['is_night'] = (df['day_or_night'] == 'night').astype(int)

        # v1.1: Nonlinear stage length correction (short stages are disproportionately harder)
        df['stage_length_corrected'] = df['stage_length_km'] ** self.stage_length_power

        # v1.1: Short stage flag and penalty factor
        df['is_short_stage'] = (df['stage_length_km'] < self.short_stage_km).astype(int)
        df['short_stage_penalty'] = np.where(
            df['stage_length_km'] < self.short_stage_km,
            self.short_stage_penalty,
            1.0
        )

        # Stage length bins
        df['stage_length_bin'] = pd.cut(
            df['stage_length_km'],
            bins=[0, 10, 20, 30, 100],
            labels=['short', 'medium', 'long', 'very_long']
        )
        df = pd.get_dummies(df, columns=['stage_length_bin'], prefix='length', dtype=int)

        return df

    def _add_vehicle_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add vehicle/class features"""
        # Store car_class before one-hot encoding
        car_class_backup = df['car_class'].copy()

        # Class encoding
        class_order = {
            'R2': 1, 'Rally3': 2, 'Rally2': 3, 'R5': 4,
            'N4': 5, 'Rally1': 6, 'WRC': 7
        }
        df['class_ordinal'] = car_class_backup.map(class_order).fillna(0)

        # One-hot encode class
        df = pd.get_dummies(df, columns=['car_class'], prefix='class', dtype=int)

        # Restore original car_class column for later use
        df['car_class'] = car_class_backup

        return df

    def _add_driver_features_temporal(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        CRITICAL: Add driver features with strict temporal ordering
        v1.1: Adds short-stage performance + momentum
        """
        logger.info("[v1.1] Adding driver features (temporal-safe)...")

        # Initialize columns (v1.1: added 2 new features)
        driver_cols = [
            'driver_mean_ratio_surface',
            'driver_std_ratio_surface',
            'driver_mean_ratio_overall',
            'driver_best_ratio_season',
            'driver_stages_completed',
            'driver_last3_ratio_same_rally',
            'driver_avg_ratio_this_rally',
            'driver_short_stage_ratio',  # v1.1: NEW - Short stage specific performance
            'driver_momentum',  # v1.1: NEW - Performance trend
            'is_rookie'
        ]

        for col in driver_cols:
            df[col] = np.nan

        df['is_rookie'] = False
        df['driver_stages_completed'] = 0

        # Process each driver
        for driver_id in df['driver_id'].unique():
            driver_mask = df['driver_id'] == driver_id
            driver_df = df[driver_mask].sort_values(['rally_date', 'stage_number'])

            for idx in driver_df.index:
                current_row = df.loc[idx]
                current_date = current_row['rally_date']
                current_rally = current_row['rally_id']
                current_stage = current_row['stage_number']
                current_surface = current_row['surface']

                # Get historical data (before this stage)
                historical = driver_df[
                    ((driver_df['rally_date'] < current_date) |
                     ((driver_df['rally_id'] == current_rally) &
                      (driver_df['stage_number'] < current_stage)))
                ].copy()

                if len(historical) == 0:
                    df.loc[idx, 'is_rookie'] = True
                    continue

                # Overall stats
                recent = historical.tail(self.lookback_stages)
                df.loc[idx, 'driver_mean_ratio_overall'] = recent['ratio_to_class_best'].mean()
                df.loc[idx, 'driver_std_ratio_surface'] = recent['ratio_to_class_best'].std()
                df.loc[idx, 'driver_stages_completed'] = len(historical)
                df.loc[idx, 'driver_best_ratio_season'] = historical['ratio_to_class_best'].min()

                # Surface-specific
                surface_history = historical[historical['surface'] == current_surface].tail(self.lookback_stages)
                if len(surface_history) > 0:
                    df.loc[idx, 'driver_mean_ratio_surface'] = surface_history['ratio_to_class_best'].mean()
                else:
                    df.loc[idx, 'driver_mean_ratio_surface'] = df.loc[idx, 'driver_mean_ratio_overall']

                # Same rally stats
                same_rally = historical[historical['rally_id'] == current_rally]
                if len(same_rally) > 0:
                    df.loc[idx, 'driver_avg_ratio_this_rally'] = same_rally['ratio_to_class_best'].mean()
                    df.loc[idx, 'driver_last3_ratio_same_rally'] = same_rally.tail(3)['ratio_to_class_best'].mean()

                # v1.1: Short stage specific performance (only stages <7km)
                short_stages = historical[historical['stage_length_km'] < self.short_stage_km]
                if len(short_stages) >= 3:  # Need minimum data
                    df.loc[idx, 'driver_short_stage_ratio'] = short_stages.tail(10)['ratio_to_class_best'].mean()
                else:
                    # Fallback to overall
                    df.loc[idx, 'driver_short_stage_ratio'] = df.loc[idx, 'driver_mean_ratio_overall']

                # v1.1: Momentum - Recent 5 vs Previous 5
                if len(recent) >= self.momentum_lookback:
                    recent_n = recent.tail(self.momentum_lookback)['ratio_to_class_best'].mean()

                    if len(historical) >= self.momentum_lookback * 2:
                        # Get stages before the recent N
                        prev_n = historical.iloc[-(self.momentum_lookback*2):-self.momentum_lookback]['ratio_to_class_best'].mean()
                        # Positive momentum = getting faster (lower ratio)
                        df.loc[idx, 'driver_momentum'] = prev_n - recent_n
                    else:
                        df.loc[idx, 'driver_momentum'] = 0.0
                else:
                    df.loc[idx, 'driver_momentum'] = 0.0

        logger.info("[v1.1] Driver features complete")
        return df

    def _add_rally_context(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add rally context features"""
        # Handle cumulative_stage_km
        if 'cumulative_stage_km' in df.columns:
            df['cumulative_stage_km_normalized'] = df['cumulative_stage_km'] / 100
        else:
            df['cumulative_stage_km_normalized'] = 0

        df['stage_progress'] = df.groupby('rally_id')['stage_number'].transform(
            lambda x: (x - x.min()) / (x.max() - x.min() + 1e-6)
        )

        # Handle stage_number_in_day
        if 'stage_number_in_day' in df.columns:
            df['is_first_stage_of_day'] = (df['stage_number_in_day'] == 1).astype(int)
        else:
            df['is_first_stage_of_day'] = 1  # Default to first stage

        return df

    def _add_competition_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add competition pressure features"""
        # Handle gap columns
        if 'gap_to_leader_seconds' in df.columns:
            df['gap_to_leader_per_km'] = df['gap_to_leader_seconds'] / df['stage_length_km']
        else:
            df['gap_to_leader_per_km'] = 0

        if 'gap_to_class_leader_seconds' in df.columns:
            df['gap_to_class_leader_per_km'] = df['gap_to_class_leader_seconds'] / df['stage_length_km']
        else:
            df['gap_to_class_leader_per_km'] = 0

        # Handle position columns
        if 'overall_position_before' in df.columns:
            df['is_leading_overall'] = (df['overall_position_before'] == 1).astype(int)
        else:
            df['is_leading_overall'] = 0

        if 'class_position_before' in df.columns:
            df['is_leading_class'] = (df['class_position_before'] == 1).astype(int)
            df['is_top3_class'] = (df['class_position_before'] <= 3).astype(int)
        else:
            df['is_leading_class'] = 0
            df['is_top3_class'] = 0

        return df

    def _impute_missing(self, df: pd.DataFrame) -> pd.DataFrame:
        """Impute missing values"""
        logger.info("Imputing missing values...")

        # For rookies, use surface median (car_class was one-hot encoded so we can't group by it)
        rookie_mask = df['is_rookie']

        for col in ['driver_mean_ratio_surface', 'driver_mean_ratio_overall']:
            if col in df.columns:
                surface_medians = df.groupby('surface')[col].transform('median')
                df.loc[rookie_mask, col] = df.loc[rookie_mask, col].fillna(surface_medians)

        # Fill remaining NaNs
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        for col in numeric_cols:
            if df[col].isna().any():
                df[col].fillna(df[col].median(), inplace=True)

        return df


if __name__ == '__main__':
    from src.utils.database import Database

    db = Database()
    df = db.load_dataframe("SELECT * FROM clean_stage_results")

    engineer = FeatureEngineerV1_1()
    features_df = engineer.engineer_all(df)

    # Save
    output_path = 'data/processed/features_v1_1.parquet'
    features_df.to_parquet(output_path)
    logger.info(f"[v1.1] Saved {len(features_df)} rows with {len(features_df.columns)} features")
