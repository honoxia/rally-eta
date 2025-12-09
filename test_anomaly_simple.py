"""Test anomaly detector with synthetic data"""
import pandas as pd
import numpy as np
from src.preprocessing.anomaly_detector import AnomalyDetector

# Create synthetic data - one rally, one stage, one class, 10 drivers
np.random.seed(42)
base_time = 1000  # ~16.7 minutes for 25.5 km = 91.8 km/h average (realistic)
times = base_time + np.random.normal(0, 50, 10)  # Normal distribution

df = pd.DataFrame({
    'result_id': range(1, 11),
    'rally_id': [1] * 10,
    'stage_id': [1] * 10,
    'car_class': ['RC2'] * 10,
    'driver_name': [f'Driver {i}' for i in range(1, 11)],
    'time_seconds': times,
    'stage_length_km': [25.5] * 10,
    'surface': ['gravel'] * 10,
    'status': ['OK'] * 10
})

print("Input data:")
print(df[['result_id', 'rally_id', 'stage_id', 'car_class', 'time_seconds', 'stage_length_km']])
print(f"\nTime range: {df['time_seconds'].min():.1f} - {df['time_seconds'].max():.1f}")
print(f"Mean time: {df['time_seconds'].mean():.1f}")

# Test anomaly detection
detector = AnomalyDetector()
result = detector.detect(df)

print("\n\nAfter detection:")
print(f"Columns: {result.columns.tolist()}")
print(f"'is_anomaly' exists: {'is_anomaly' in result.columns}")

if 'is_anomaly' in result.columns:
    print(f"\nAnomalies: {result['is_anomaly'].sum()}/{len(result)}")
    print(f"Clean results: {(~result['is_anomaly']).sum()}/{len(result)}")

    if result['is_anomaly'].any():
        print("\nAnomalous results:")
        print(result[result['is_anomaly']][['result_id', 'time_seconds', 'anomaly_reason']])

    if (~result['is_anomaly']).any():
        print("\nClean results:")
        print(result[~result['is_anomaly']][['result_id', 'time_seconds']])
else:
    print("ERROR: is_anomaly column not created!")
    print("\nResult DataFrame:")
    print(result)
