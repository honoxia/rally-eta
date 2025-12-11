"""Detect anomalous stage times - Version 1.1 with adaptive thresholds"""
import pandas as pd
import numpy as np
from scipy import stats
import logging
from config.config_loader import config

logger = logging.getLogger(__name__)


class AnomalyDetectorV1_1:
    """
    Detect outlier times that should be excluded from training

    Version 1.1 Changes:
    - Adaptive z-threshold for short stages (<7km)
    - Short stages use higher tolerance (3.5 vs 3.0) due to natural variance
    """

    def __init__(self):
        self.base_threshold = config.get('preprocessing.anomaly_detection.base_threshold_ratio')
        self.z_threshold = config.get('preprocessing.anomaly_detection.z_score_threshold')
        self.z_threshold_short = config.get('preprocessing.anomaly_detection.z_score_short_stage_threshold')
        self.short_stage_km = config.get('preprocessing.anomaly_detection.short_stage_threshold_km')
        self.min_speed_gravel = config.get('preprocessing.anomaly_detection.min_avg_speed_gravel')
        self.min_speed_asphalt = config.get('preprocessing.anomaly_detection.min_avg_speed_asphalt')
        self.max_speed = config.get('preprocessing.anomaly_detection.max_avg_speed')

    def detect(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Detect anomalies and add is_anomaly column

        CRITICAL: Must respect class boundaries
        """
        df = df.copy()
        df['is_anomaly'] = False
        df['anomaly_reason'] = None

        # Save columns that will be dropped by groupby
        index_cols = df.set_index('result_id')[['rally_id', 'stage_id', 'car_class']].copy()

        # Group by rally, stage, class
        def flag_group(group):
            if len(group) < 3:
                return group

            class_best = group['time_seconds'].min()
            stage_km = group['stage_length_km'].iloc[0]

            # Guard against zero division
            if class_best == 0 or pd.isna(class_best):
                return group

            # Method 1: Ratio to best
            group['ratio_to_best'] = group['time_seconds'] / class_best
            threshold = self.base_threshold * (1 + stage_km / 50)

            outlier_ratio = group['ratio_to_best'] > threshold

            # Method 2: Z-score (v1.1: adaptive threshold for short stages)
            is_short_stage = stage_km < self.short_stage_km
            z_thresh = self.z_threshold_short if is_short_stage else self.z_threshold
            z_scores = np.abs(stats.zscore(group['time_seconds'], nan_policy='omit'))
            outlier_z = z_scores > z_thresh

            # Flag if either triggers
            group['is_anomaly'] = outlier_ratio | outlier_z
            group.loc[outlier_ratio, 'anomaly_reason'] = 'ratio_outlier'
            group.loc[outlier_z & ~outlier_ratio, 'anomaly_reason'] = 'z_score_outlier'

            return group

        df = df.groupby(['rally_id', 'stage_id', 'car_class'], group_keys=False).apply(flag_group, include_groups=False)

        # Restore columns that were dropped by groupby
        for col in ['rally_id', 'stage_id', 'car_class']:
            if col not in df.columns and 'result_id' in df.columns:
                df = df.set_index('result_id')
                df[col] = index_cols[col]
                df = df.reset_index()

        # Physical speed checks
        # Guard against zero division
        df['avg_speed_kmh'] = df.apply(
            lambda row: (row['stage_length_km'] / row['time_seconds']) * 3600
            if row['time_seconds'] > 0 else 0,
            axis=1
        )

        speed_too_high = df['avg_speed_kmh'] > self.max_speed
        df.loc[speed_too_high, 'is_anomaly'] = True
        df.loc[speed_too_high, 'anomaly_reason'] = 'speed_too_high'

        # Speed too low (stuck/lost)
        df['min_speed'] = df['surface'].map({
            'gravel': self.min_speed_gravel,
            'asphalt': self.min_speed_asphalt
        }).fillna(self.min_speed_gravel)

        speed_too_low = df['avg_speed_kmh'] < df['min_speed']
        df.loc[speed_too_low, 'is_anomaly'] = True
        df.loc[speed_too_low, 'anomaly_reason'] = 'speed_too_low'

        logger.info(f"[v1.1] Detected {df['is_anomaly'].sum()} anomalies ({df['is_anomaly'].mean()*100:.1f}%)")

        # Drop temporary columns if they exist
        cols_to_drop = [col for col in ['ratio_to_best', 'min_speed', 'avg_speed_kmh'] if col in df.columns]
        if cols_to_drop:
            df = df.drop(columns=cols_to_drop)

        return df
