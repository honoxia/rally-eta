"""Test inference module"""
from src.inference.predict_notional_times import NotionalTimePredictor
from src.utils.database import Database

# Get sample IDs from database
db = Database()
df = db.load_dataframe("SELECT DISTINCT rally_id, stage_id, driver_id FROM clean_stage_results LIMIT 5")

print("Sample data from database:")
print(df)

# Get the rally and stage for testing
rally_id = df.iloc[0]['rally_id']

# Get stage 2 (SS2) to ensure we have historical data
df_ss2 = db.load_dataframe(f"SELECT DISTINCT stage_id FROM clean_stage_results WHERE rally_id = '{rally_id}' AND stage_name = 'SS2'")
if len(df_ss2) > 0:
    stage_id = df_ss2.iloc[0]['stage_id']
else:
    print("Error: No SS2 found in database. Using SS1 (will fail due to no history)")
    stage_id = df.iloc[0]['stage_id']

affected_drivers = [df.iloc[0]['driver_id']]  # Test with first driver

print(f"\nTest prediction for:")
print(f"Rally: {rally_id}")
print(f"Stage: {stage_id}")
print(f"Driver: {affected_drivers[0]}")

# Create predictor
try:
    predictor = NotionalTimePredictor()

    # Make prediction
    predictions = predictor.predict_for_red_flag(
        rally_id=rally_id,
        stage_id=stage_id,
        affected_driver_ids=affected_drivers
    )

    print("\n" + "="*80)
    print("PREDICTION RESULTS")
    print("="*80)
    print(predictions.to_string(index=False))

except Exception as e:
    print(f"\nError during prediction: {e}")
    import traceback
    traceback.print_exc()
