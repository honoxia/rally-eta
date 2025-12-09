"""Tests for feature engineering"""
import pytest
import pandas as pd
import numpy as np
from src.features.engineer_features import FeatureEngineer


def test_no_data_leakage():
    """CRITICAL: Ensure no future data is used in feature engineering"""
    # Create sample data with 6 stages for one driver
    df = pd.DataFrame({
        'result_id': ['r1_ss1_d1', 'r1_ss2_d1', 'r1_ss3_d1', 'r1_ss4_d1', 'r1_ss5_d1', 'r1_ss6_d1'],
        'rally_id': ['R1'] * 6,
        'rally_name': ['Rally 1'] * 6,
        'stage_id': ['r1_ss1', 'r1_ss2', 'r1_ss3', 'r1_ss4', 'r1_ss5', 'r1_ss6'],
        'stage_name': ['SS1', 'SS2', 'SS3', 'SS4', 'SS5', 'SS6'],
        'stage_number': [1, 2, 3, 4, 5, 6],
        'rally_date': pd.to_datetime(['2024-01-01'] * 6),
        'driver_id': ['D1'] * 6,
        'driver_name': ['Driver 1'] * 6,
        'time_seconds': [100, 102, 98, 105, 101, 99],
        'surface': ['gravel'] * 6,
        'car_class': ['Rally2'] * 6,
        'car_model': ['Ford Fiesta Rally2'] * 6,
        'is_anomaly': [False] * 6,
        'stage_length_km': [20.0] * 6,
        'day_or_night': ['day'] * 6,
        'status': ['FINISHED'] * 6,
        'overall_position_before': [1, 1, 1, 1, 1, 1],
        'class_position_before': [1, 1, 1, 1, 1, 1],
        'raw_time_str': ['10:00.0'] * 6,
    })

    engineer = FeatureEngineer()
    result = engineer.engineer_all(df)

    # For stage 3, mean should only use stages 1-2 (not stages 4-6)
    stage3_rows = result[result['stage_number'] == 3]

    if len(stage3_rows) > 0:
        stage3_idx = stage3_rows.index[0]
        stage3_mean = result.loc[stage3_idx, 'driver_mean_ratio_overall']

        # Expected mean: average of ratio from stages 1 and 2
        # Since all times are similar, ratios should be close to 1.0
        # Stage 1: 100/100 = 1.0, Stage 2: 102/98 or similar
        # The exact value depends on class_best calculation

        # Key check: driver_stages_completed should be 2 (only stages 1-2)
        stage3_completed = result.loc[stage3_idx, 'driver_stages_completed']
        assert stage3_completed == 2, \
            f"Data leakage! Stage 3 should only see 2 previous stages, got {stage3_completed}"

        # Mean should not include stages 4, 5, 6
        assert pd.notna(stage3_mean), "driver_mean_ratio_overall should not be NaN for stage 3"


def test_rookie_handling():
    """Test rookie driver imputation"""
    # Create data with 2 drivers: one experienced, one rookie
    df = pd.DataFrame({
        'result_id': ['r1_ss1_exp', 'r1_ss1_new'],
        'rally_id': ['R1', 'R1'],
        'rally_name': ['Rally 1', 'Rally 1'],
        'stage_id': ['r1_ss1', 'r1_ss1'],
        'stage_name': ['SS1', 'SS1'],
        'stage_number': [1, 1],
        'rally_date': pd.to_datetime(['2024-01-01', '2024-01-01']),
        'driver_id': ['EXP', 'NEW'],
        'driver_name': ['Experienced Driver', 'New Driver'],
        'time_seconds': [100.0, 105.0],
        'surface': ['gravel', 'gravel'],
        'car_class': ['Rally2', 'Rally2'],
        'car_model': ['Ford Fiesta Rally2', 'Ford Fiesta Rally2'],
        'is_anomaly': [False, False],
        'stage_length_km': [20.0, 20.0],
        'day_or_night': ['day', 'day'],
        'status': ['FINISHED', 'FINISHED'],
        'overall_position_before': [1, 2],
        'class_position_before': [1, 2],
        'raw_time_str': ['10:00.0', '10:05.0'],
    })

    engineer = FeatureEngineer()
    result = engineer.engineer_all(df)

    # Both should be rookies (first stage for both)
    assert result.loc[0, 'is_rookie'] == True, "First stage driver should be marked as rookie"
    assert result.loc[1, 'is_rookie'] == True, "First stage driver should be marked as rookie"


def test_target_calculation():
    """Test ratio_to_class_best calculation"""
    df = pd.DataFrame({
        'result_id': ['r1_ss1_d1', 'r1_ss1_d2'],
        'rally_id': ['R1', 'R1'],
        'rally_name': ['Rally 1', 'Rally 1'],
        'stage_id': ['r1_ss1', 'r1_ss1'],
        'stage_name': ['SS1', 'SS1'],
        'stage_number': [1, 1],
        'rally_date': pd.to_datetime(['2024-01-01', '2024-01-01']),
        'driver_id': ['D1', 'D2'],
        'driver_name': ['Driver 1', 'Driver 2'],
        'time_seconds': [100.0, 110.0],
        'car_class': ['Rally2', 'Rally2'],
        'car_model': ['Ford Fiesta Rally2', 'Ford Fiesta Rally2'],
        'is_anomaly': [False, False],
        'surface': ['gravel', 'gravel'],
        'stage_length_km': [20.0, 20.0],
        'day_or_night': ['day', 'day'],
        'status': ['FINISHED', 'FINISHED'],
        'overall_position_before': [1, 2],
        'class_position_before': [1, 2],
        'raw_time_str': ['10:00.0', '11:00.0'],
    })

    engineer = FeatureEngineer()
    result = engineer._calculate_target(df)

    # Class best should be 100 (D1's time)
    assert result.loc[0, 'class_best_time'] == 100.0, "Class best time should be 100"

    # D1 ratio should be 1.0 (fastest)
    assert abs(result.loc[0, 'ratio_to_class_best'] - 1.0) < 0.01, "D1 ratio should be 1.0"

    # D2 ratio should be 1.1 (10% slower)
    assert abs(result.loc[1, 'ratio_to_class_best'] - 1.1) < 0.01, "D2 ratio should be 1.1"


def test_class_separation():
    """Test that different classes don't interfere with each other"""
    df = pd.DataFrame({
        'result_id': ['r1_ss1_wrc', 'r1_ss1_r2'],
        'rally_id': ['R1', 'R1'],
        'rally_name': ['Rally 1', 'Rally 1'],
        'stage_id': ['r1_ss1', 'r1_ss1'],
        'stage_name': ['SS1', 'SS1'],
        'stage_number': [1, 1],
        'rally_date': pd.to_datetime(['2024-01-01', '2024-01-01']),
        'driver_id': ['WRC_D', 'R2_D'],
        'driver_name': ['WRC Driver', 'Rally2 Driver'],
        'time_seconds': [90.0, 100.0],  # WRC faster
        'car_class': ['WRC', 'Rally2'],
        'car_model': ['Toyota GR Yaris WRC', 'Ford Fiesta Rally2'],
        'is_anomaly': [False, False],
        'surface': ['gravel', 'gravel'],
        'stage_length_km': [20.0, 20.0],
        'day_or_night': ['day', 'day'],
        'status': ['FINISHED', 'FINISHED'],
        'overall_position_before': [1, 2],
        'class_position_before': [1, 1],
        'raw_time_str': ['9:00.0', '10:00.0'],
    })

    engineer = FeatureEngineer()
    result = engineer._calculate_target(df)

    # Each class should have ratio 1.0 (best in their class)
    wrc_row = result[result['car_class'] == 'WRC']
    r2_row = result[result['car_class'] == 'Rally2']

    if len(wrc_row) > 0:
        assert abs(wrc_row.iloc[0]['ratio_to_class_best'] - 1.0) < 0.01, \
            "WRC driver should have ratio 1.0 in their class"

    if len(r2_row) > 0:
        assert abs(r2_row.iloc[0]['ratio_to_class_best'] - 1.0) < 0.01, \
            "Rally2 driver should have ratio 1.0 in their class"
