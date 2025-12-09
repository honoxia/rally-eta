from pathlib import Path

import pandas as pd

from src.preprocessing.clean_data import DataCleaner
from src.preprocessing.time_parser import TimeParser
from src.preprocessing.anomaly_detector import AnomalyDetector


def main():
    raw_path = Path("data") / "scraper_debug_97.xlsx"
    raw_df = pd.read_excel(raw_path)

    print("RAW ROWS:", len(raw_df))
    print(raw_df.head())

    parser = TimeParser()
    cleaner = DataCleaner()
    anomaly_detector = AnomalyDetector()

    df = raw_df.copy()

    if 'raw_time_str' not in df.columns:
        if 'time_str' in df.columns:
            df['raw_time_str'] = df['time_str']
        else:
            print("Available columns:", list(df.columns))
            raise KeyError("Neither 'raw_time_str' nor 'time_str' column found in input data.")

    if 'time_seconds' not in df.columns or df['time_seconds'].isna().any():
        df['time_seconds'] = df['raw_time_str'].apply(parser.parse)

    # Ensure result_id exists
    if 'result_id' not in df.columns:
        df = df.reset_index(drop=True)
        df['result_id'] = df.index + 1

    # Ensure stage_id exists
    if 'stage_id' not in df.columns:
        if 'rally_id' in df.columns and 'stage_number' in df.columns:
            df['stage_id'] = (
                df['rally_id'].astype(str) + "_" +
                df['stage_number'].astype(str)
            )
        else:
            print("Available columns:", list(df.columns))
            raise KeyError("Cannot construct 'stage_id' because 'rally_id' or 'stage_number' is missing.")

    # Ensure surface exists (for this debug rally, assume asphalt)
    if 'surface' not in df.columns:
        df['surface'] = 'asphalt'

    df = cleaner._remove_invalid(df)
    df = anomaly_detector.detect(df)
    print("Anomaly value counts:")
    print(df['is_anomaly'].value_counts())
    print("Anomaly reasons:")
    print(df['anomaly_reason'].value_counts())

    clean_df = df.copy()

    print("CLEAN ROWS:", len(clean_df))
    print(clean_df.head())

    clean_path = Path("data") / "preprocess_clean_97.xlsx"
    clean_path.parent.mkdir(parents=True, exist_ok=True)
    clean_df.to_excel(clean_path, index=False)

    print(f"Saved cleaned data to: {clean_path}")


if __name__ == "__main__":
    main()
