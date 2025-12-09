"""Test anomaly detection on portable data"""
import sys
sys.path.insert(0, 'RallyETA_Portable_v1.0')

from src.utils.database import Database
from src.preprocessing.anomaly_detector import AnomalyDetector
import pandas as pd

# Load data from portable
db = Database()
db.db_path = 'RallyETA_Portable_v1.0/data/rally_eta.db'

# Check what tables exist
try:
    tables = db.load_dataframe("SELECT name FROM sqlite_master WHERE type='table'")
    print(f"Tables in database: {tables['name'].tolist()}")
except:
    print("No tables yet or error loading")

# Try loading raw results
try:
    df = db.load_dataframe("SELECT * FROM raw_stage_results LIMIT 10")
    print(f"\nRaw results sample:\n{df[['rally_id', 'stage_id', 'car_class', 'status', 'time_seconds', 'stage_length_km']].head()}")
    print(f"\nTotal raw results: {len(df)}")

    # Check grouping
    groups = df.groupby(['rally_id', 'stage_id', 'car_class']).size().reset_index(name='count')
    print(f"\nGroup sizes:\n{groups.sort_values('count')}")
    print(f"\nGroups with <3 results: {len(groups[groups['count'] < 3])}")

except Exception as e:
    print(f"Error loading raw data: {e}")

# Try loading stage_results
try:
    df = db.load_dataframe("SELECT * FROM stage_results LIMIT 10")
    print(f"\nStage results sample:\n{df[['rally_id', 'stage_id', 'car_class', 'status', 'time_seconds', 'stage_length_km']].head()}")

    # Full data
    df_full = db.load_dataframe("SELECT * FROM stage_results")
    print(f"\nTotal stage results: {len(df_full)}")

    # Check grouping
    groups = df_full.groupby(['rally_id', 'stage_id', 'car_class']).size().reset_index(name='count')
    print(f"\nGroup sizes:\n{groups.sort_values('count')}")
    print(f"\nGroups with <3 results: {len(groups[groups['count'] < 3])}")

    # Test anomaly detection on a small sample
    print("\n--- Testing Anomaly Detection ---")
    detector = AnomalyDetector()

    # Take one group with 3+ results
    big_group = groups[groups['count'] >= 3].iloc[0]
    test_df = df_full[
        (df_full['rally_id'] == big_group['rally_id']) &
        (df_full['stage_id'] == big_group['stage_id']) &
        (df_full['car_class'] == big_group['car_class'])
    ].copy()

    print(f"\nTest group: rally={big_group['rally_id']}, stage={big_group['stage_id']}, class={big_group['car_class']}")
    print(f"Test group size: {len(test_df)}")
    print(f"Time range: {test_df['time_seconds'].min():.1f} - {test_df['time_seconds'].max():.1f}")

    result = detector.detect(test_df)
    print(f"\nAfter detection:")
    print(f"  - is_anomaly column exists: {'is_anomaly' in result.columns}")
    if 'is_anomaly' in result.columns:
        print(f"  - Anomalies: {result['is_anomaly'].sum()}/{len(result)}")
    print(f"  - Columns: {result.columns.tolist()}")

except Exception as e:
    print(f"Error with stage_results: {e}")
    import traceback
    traceback.print_exc()
