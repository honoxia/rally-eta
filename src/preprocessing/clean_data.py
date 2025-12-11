"""Clean and prepare raw data"""
import pandas as pd
import logging
from src.utils.database import Database
from src.preprocessing.time_parser import TimeParser
from src.preprocessing.anomaly_detector_v1_1 import AnomalyDetectorV1_1 as AnomalyDetector  # v1.1
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class DataCleaner:
    """Clean raw stage results"""

    def __init__(self):
        self.db = Database()
        self.time_parser = TimeParser()
        self.anomaly_detector = AnomalyDetector()

    def clean(self):
        """Full cleaning pipeline"""
        logger.info("Starting data cleaning...")

        # Load raw data
        df = self.db.load_dataframe("SELECT * FROM stage_results")
        logger.info(f"Loaded {len(df)} raw results")

        # Parse times if not already done
        if df['time_seconds'].isna().any():
            df['time_seconds'] = df['raw_time_str'].apply(self.time_parser.parse)

        # Normalize driver names (convert to title case for consistency)
        if 'driver_name' in df.columns:
            df['driver_name'] = df['driver_name'].str.strip().str.title()
            logger.info("Normalized driver names to title case")

        # Remove invalid results
        df = self._remove_invalid(df)

        # Detect anomalies
        df = self.anomaly_detector.detect(df)

        # For now, keep all rows; just tag anomalies
        clean_df = df.copy()

        # Save tagged data
        self.db.save_dataframe(clean_df, 'clean_stage_results', if_exists='replace')
        logger.info(f"Saved {len(clean_df)} tagged results (including anomalies)")

        # Save anomalies separately for analysis
        anomaly_df = df[df['is_anomaly']].copy()
        self.db.save_dataframe(anomaly_df, 'anomaly_stage_results', if_exists='replace')
        logger.info(f"Saved {len(anomaly_df)} anomalies")

        return clean_df

    def _remove_invalid(self, df: pd.DataFrame) -> pd.DataFrame:
        """Remove clearly invalid results"""
        initial_count = len(df)

        # Log diagnostic info about each filter condition
        status_count = (df['status'].isin(['FINISHED', 'OK'])).sum()
        time_valid = (df['time_seconds'].notna() & (df['time_seconds'] > 0)).sum()
        length_valid = (df['stage_length_km'].notna() & (df['stage_length_km'] > 0)).sum()
        
        logger.info(f"Filter diagnostics - Total: {initial_count}")
        logger.info(f"  - Status FINISHED/OK: {status_count}")
        logger.info(f"  - Time valid: {time_valid}")
        logger.info(f"  - Stage length valid: {length_valid}")
        logger.info(f"  - Unique statuses: {df['status'].unique().tolist()[:10]}")

        valid_mask = (
            (df['status'].isin(['FINISHED', 'OK'])) &
            (df['time_seconds'].notna()) &
            (df['time_seconds'] > 0) &
            (df['stage_length_km'].notna()) &
            (df['stage_length_km'] > 0)
        )

        df = df[valid_mask].copy()

        logger.info(f"Removed {initial_count - len(df)} invalid results, remaining: {len(df)}")
        
        if len(df) == 0:
            logger.warning("WARNING: All data was filtered out! Check raw data for issues.")
        
        return df


if __name__ == '__main__':
    cleaner = DataCleaner()
    clean_df = cleaner.clean()
