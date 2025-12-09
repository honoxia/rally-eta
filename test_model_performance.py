"""Test model performance"""
import pandas as pd
import numpy as np
from src.models.train_model import RallyETAModel

# Load model
model = RallyETAModel()
model.load()

# Load data
df = pd.read_parquet('data/processed/features.parquet')

print('Model Test:')
print('='*60)

# Split data
train_df, val_df, test_df = model.prepare_data_split(df)
print(f'\nData Split:')
print(f'  Train: {len(train_df)} samples')
print(f'  Val: {len(val_df)} samples')
print(f'  Test: {len(test_df)} samples')
print(f'\nFeatures: {len(model.feature_names)} numeric features')

# Evaluate on test set
test_metrics = model.evaluate(test_df, 'Test')

print(f'\nTest Performance:')
print(f'  MAE: {test_metrics["mae"]:.4f} ({test_metrics["mae"]*100:.2f}%)')
print(f'  MAPE: {test_metrics["mape"]:.4f} ({test_metrics["mape"]*100:.2f}%)')

# Check success criterion
success = test_metrics["mape"]*100 < 2.5
print(f'\nSuccess Criterion: Test MAPE < 2.5%: {"PASSED" if success else "FAILED"}')

# Show sample predictions
print(f'\nSample Predictions (Test Set):')
for i in range(min(5, len(test_df))):
    idx = test_df.index[i]
    actual = test_metrics['actuals'].iloc[i]
    pred = test_metrics['predictions'][i]
    error = abs(actual - pred)
    print(f'  Sample {i+1}: Actual={actual:.4f}, Predicted={pred:.4f}, Error={error:.4f} ({error/actual*100:.1f}%)')
