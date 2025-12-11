"""
Test script to verify scipy and sklearn imports work correctly
This directly tests the imports that were previously failing
"""
import sys

print("=" * 60)
print("IMPORT TEST - RallyETA Dependencies")
print("=" * 60)

errors = []

# Test 1: Scipy imports
print("\n[TEST 1] Testing scipy imports...")
try:
    from scipy import stats
    from scipy.sparse import lil_matrix
    print("  ✓ scipy.stats imported successfully")
    print("  ✓ scipy.sparse imported successfully")
except Exception as e:
    errors.append(f"scipy: {str(e)}")
    print(f"  ✗ scipy import FAILED: {e}")

# Test 2: Sklearn imports
print("\n[TEST 2] Testing sklearn imports...")
try:
    from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.tree import DecisionTreeRegressor
    print("  ✓ sklearn.metrics imported successfully")
    print("  ✓ sklearn.ensemble imported successfully")
    print("  ✓ sklearn.tree imported successfully")
except Exception as e:
    errors.append(f"sklearn: {str(e)}")
    print(f"  ✗ sklearn import FAILED: {e}")

# Test 3: Application-specific imports
print("\n[TEST 3] Testing application imports...")
try:
    from src.preprocessing.clean_data import DataCleaner
    print("  ✓ DataCleaner imported successfully")
except Exception as e:
    errors.append(f"DataCleaner: {str(e)}")
    print(f"  ✗ DataCleaner import FAILED: {e}")

try:
    from src.models.train_model import RallyETAModel
    print("  ✓ RallyETAModel imported successfully")
except Exception as e:
    errors.append(f"RallyETAModel: {str(e)}")
    print(f"  ✗ RallyETAModel import FAILED: {e}")

# Summary
print("\n" + "=" * 60)
if errors:
    print(f"RESULT: FAILED - {len(errors)} error(s) found")
    print("\nErrors:")
    for err in errors:
        print(f"  - {err}")
    sys.exit(1)
else:
    print("RESULT: ALL TESTS PASSED ✓")
    print("All critical imports are working correctly!")
    sys.exit(0)
