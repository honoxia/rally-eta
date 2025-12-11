"""Predict notional times for red-flagged stages"""
import pandas as pd
import numpy as np
from typing import List, Dict, Optional
from pathlib import Path
import logging
from src.models.train_model import RallyETAModel
from src.features.engineer_features import FeatureEngineer
from src.utils.database import Database
from src.utils.logger import setup_logger
from config.config_loader import config

logger = setup_logger(__name__)

class NotionalTimePredictor:
    """Predict notional times for affected drivers"""

    def __init__(self, model_path: str = "models/rally_eta_v1"):
        self.model = RallyETAModel()
        self.model.load(model_path)
        self.feature_engineer = FeatureEngineer()
        self.db = Database()
        self.min_ratio = config.get('inference.constraints.min_ratio')
        self.max_ratio = config.get('inference.constraints.max_ratio')

    def predict_for_red_flag(self,
                            rally_id: str,
                            stage_id: str,
                            affected_driver_ids: List[str]) -> pd.DataFrame:
        """
        Main prediction function for red flag scenario

        Args:
            rally_id: Current rally ID
            stage_id: Stage that was red-flagged
            affected_driver_ids: List of driver IDs affected

        Returns:
            DataFrame with predictions for each driver
        """
        logger.info(f"Predicting notional times for {len(affected_driver_ids)} drivers")
        logger.info(f"Rally: {rally_id}, Stage: {stage_id}")

        # Load rally data
        rally_data = self._load_rally_data(rally_id, stage_id)
        stage_info = self._get_stage_info(rally_data, stage_id)

        # Calculate class reference times
        class_ref_times = self._calculate_class_reference_times(rally_data, stage_id)

        # Prepare prediction data
        predictions = []

        for driver_id in affected_driver_ids:
            try:
                prediction = self._predict_single_driver(
                    driver_id=driver_id,
                    rally_data=rally_data,
                    stage_info=stage_info,
                    class_ref_times=class_ref_times
                )
                predictions.append(prediction)
            except Exception as e:
                logger.error(f"Failed to predict for {driver_id}: {e}")

        results_df = pd.DataFrame(predictions)

        # Log summary
        logger.info(f"\nPrediction Summary:")
        logger.info(f"Total predictions: {len(results_df)}")

        if len(results_df) > 0:
            logger.info(f"High confidence: {(results_df['confidence'] == 'high').sum()}")
            logger.info(f"Medium confidence: {(results_df['confidence'] == 'medium').sum()}")
            logger.info(f"Low confidence: {(results_df['confidence'] == 'low').sum()}")

        return results_df

    def _load_rally_data(self, rally_id: str, current_stage_id: str) -> pd.DataFrame:
        """Load all data from current rally up to (and including) current stage"""
        query = f"""
        SELECT * FROM clean_stage_results
        WHERE rally_id = '{rally_id}'
        ORDER BY stage_number
        """

        df = self.db.load_dataframe(query)

        if len(df) == 0:
            raise ValueError(f"No data found for rally {rally_id}")

        logger.info(f"Loaded {len(df)} results from {rally_id}")
        return df

    def _get_stage_info(self, rally_data: pd.DataFrame, stage_id: str) -> Dict:
        """Extract stage information"""
        stage_data = rally_data[rally_data['stage_id'] == stage_id].iloc[0]

        return {
            'stage_id': stage_id,
            'stage_name': stage_data['stage_name'],
            'stage_number': stage_data['stage_number'],
            'stage_length_km': stage_data['stage_length_km'],
            'surface': stage_data['surface'],
            'day_or_night': stage_data.get('day_or_night', 'day'),
            'rally_date': stage_data['rally_date']
        }

    def _calculate_class_reference_times(self,
                                         rally_data: pd.DataFrame,
                                         stage_id: str) -> Dict:
        """Calculate best time per class from unaffected drivers"""
        stage_results = rally_data[rally_data['stage_id'] == stage_id]

        ref_times = {}

        # Get unique classes from data
        for car_class in stage_results['car_class'].unique():
            class_mask = stage_results['car_class'] == car_class
            class_times = stage_results[class_mask]['time_seconds']

            if len(class_times) > 0:
                ref_times[car_class] = {
                    'best_time': class_times.min(),
                    'n_finishers': len(class_times),
                    'median_time': class_times.median()
                }

        logger.info(f"Calculated reference times for {len(ref_times)} classes")
        return ref_times

    def _predict_single_driver(self,
                               driver_id: str,
                               rally_data: pd.DataFrame,
                               stage_info: Dict,
                               class_ref_times: Dict) -> Dict:
        """Predict notional time for a single driver"""

        # Get driver's data from this rally (before current stage)
        driver_data = rally_data[
            (rally_data['driver_id'] == driver_id) &
            (rally_data['stage_number'] < stage_info['stage_number'])
        ]

        if len(driver_data) == 0:
            raise ValueError(f"No historical data for driver {driver_id} in this rally")

        # Get driver's car class
        driver_class = driver_data.iloc[-1]['car_class']

        # Build feature row for prediction
        feature_row = self._build_feature_row(
            driver_id=driver_id,
            driver_data=driver_data,
            stage_info=stage_info,
            rally_data=rally_data
        )

        # Engineer features
        feature_df = pd.DataFrame([feature_row])
        feature_df = self.feature_engineer.engineer_all(feature_df)

        # Add avg_speed_kmh if not present (anomaly detector adds this)
        if 'avg_speed_kmh' not in feature_df.columns:
            feature_df['avg_speed_kmh'] = (feature_df['stage_length_km'] / feature_df['time_seconds']) * 3600

        # Select only numeric features (same as training)
        X = feature_df[self.model.feature_names]

        # Predict ratio
        predicted_ratio = self.model.model.predict(X)[0]

        # Apply constraints to ratio
        predicted_ratio = np.clip(predicted_ratio, self.min_ratio, self.max_ratio)

        # Get class reference time
        if driver_class in class_ref_times:
            class_ref = class_ref_times[driver_class]
            ref_time = class_ref['best_time']
            n_finishers = class_ref['n_finishers']
            confidence = 'high' if n_finishers >= 3 else 'medium'
        else:
            # Fallback: estimate from historical data
            ref_time = self._estimate_reference_time(driver_class, stage_info)
            n_finishers = 0
            confidence = 'low'

        # Calculate notional time
        notional_time = predicted_ratio * ref_time

        # Apply constraints
        notional_time = self._apply_constraints(
            notional_time,
            ref_time,
            stage_info
        )

        # Generate explanation
        explanation = self._generate_explanation(
            feature_df.iloc[0],
            predicted_ratio,
            ref_time
        )

        return {
            'driver_id': driver_id,
            'driver_name': driver_data.iloc[-1]['driver_name'],
            'car_class': driver_class,
            'stage_name': stage_info['stage_name'],
            'predicted_ratio': round(predicted_ratio, 4),
            'class_reference_time_seconds': round(ref_time, 2),
            'class_reference_time_str': self._format_time(ref_time),
            'notional_time_seconds': round(notional_time, 2),
            'notional_time_str': self._format_time(notional_time),
            'confidence': confidence,
            'n_class_finishers': n_finishers,
            'explanation': explanation
        }

    def _build_feature_row(self,
                          driver_id: str,
                          driver_data: pd.DataFrame,
                          stage_info: Dict,
                          rally_data: pd.DataFrame) -> Dict:
        """Build feature dictionary for prediction"""

        # Start with stage info
        row = {
            'driver_id': driver_id,
            'driver_name': driver_data.iloc[-1]['driver_name'],
            'rally_id': driver_data.iloc[-1]['rally_id'],
            'rally_name': driver_data.iloc[-1]['rally_name'],
            'rally_date': stage_info['rally_date'],
            'rally_year': pd.to_datetime(stage_info['rally_date']).year,
            'stage_id': stage_info['stage_id'],
            'stage_name': stage_info['stage_name'],
            'stage_number': stage_info['stage_number'],
            'stage_number_in_day': stage_info['stage_number'],
            'stage_length_km': stage_info['stage_length_km'],
            'surface': stage_info['surface'],
            'day_or_night': stage_info['day_or_night'],
        }

        # Add car info from last stage
        last_result = driver_data.iloc[-1]
        row['car_model'] = last_result['car_model']
        row['car_class'] = last_result['car_class']

        # Add competition context
        row['overall_position_before'] = last_result.get('overall_position_before', 999)
        row['class_position_before'] = last_result.get('class_position_before', 999)
        row['gap_to_leader_seconds'] = last_result.get('gap_to_leader_seconds', 0)
        row['gap_to_class_leader_seconds'] = last_result.get('gap_to_class_leader_seconds', 0)
        row['cumulative_stage_km'] = last_result.get('cumulative_stage_km', 0)

        # Add dummy target (will be ignored in prediction)
        row['ratio_to_class_best'] = 1.0
        row['time_seconds'] = 600.0  # Dummy
        row['class_best_time'] = 600.0  # Dummy
        row['is_anomaly'] = False
        row['anomaly_reason'] = None
        row['status'] = 'FINISHED'
        row['raw_time_str'] = '10:00.0'

        # Generate result_id
        row['result_id'] = f"{stage_info['stage_id']}_{driver_id}"

        return row

    def _apply_constraints(self,
                          predicted_time: float,
                          class_best: float,
                          stage_info: Dict) -> float:
        """Apply business rules and physical constraints"""

        # Cannot be faster than class best
        predicted_time = max(predicted_time, class_best)

        # Maximum ratio constraint
        max_time = class_best * self.max_ratio
        predicted_time = min(predicted_time, max_time)

        # Physical speed constraint
        min_speed = 40 if stage_info['surface'] == 'gravel' else 50
        max_time_physical = (stage_info['stage_length_km'] / min_speed) * 3600
        predicted_time = min(predicted_time, max_time_physical)

        return predicted_time

    def _estimate_reference_time(self, car_class: str, stage_info: Dict) -> float:
        """Estimate reference time from historical data (fallback)"""
        logger.warning(f"No reference time available for {car_class}, using historical estimate")

        # Query historical best times for similar stages
        # Use AVG of class leaders from similar-length stages (narrow range ±15%)
        query = f"""
        WITH stage_class_best AS (
            SELECT stage_id, car_class, MIN(time_seconds) as class_best_time
            FROM clean_stage_results
            WHERE time_seconds > 0
            GROUP BY stage_id, car_class
        )
        SELECT
            AVG(s.class_best_time / c.stage_length_km) as avg_speed_time_per_km,
            COUNT(DISTINCT c.stage_id) as stage_count
        FROM clean_stage_results c
        INNER JOIN stage_class_best s
            ON c.stage_id = s.stage_id AND c.car_class = s.car_class
        WHERE c.car_class = '{car_class}'
        AND c.surface = '{stage_info['surface']}'
        AND c.stage_length_km BETWEEN {stage_info['stage_length_km'] * 0.85}
                                AND {stage_info['stage_length_km'] * 1.15}
        AND c.stage_length_km > 0
        """

        result = self.db.load_dataframe(query)

        if len(result) > 0 and not pd.isna(result['avg_speed_time_per_km'].iloc[0]):
            avg_time_per_km = result['avg_speed_time_per_km'].iloc[0]
            ref_time = avg_time_per_km * stage_info['stage_length_km']
            stage_count = result['stage_count'].iloc[0]
            logger.info(f"Using historical reference: {ref_time:.1f}s ({avg_time_per_km:.1f}s/km, {stage_count} stages)")
            return ref_time
        else:
            # Ultimate fallback: estimate from length
            avg_speed = 80 if stage_info['surface'] == 'asphalt' else 70
            return (stage_info['stage_length_km'] / avg_speed) * 3600

    def _generate_explanation(self,
                             feature_row: pd.Series,
                             predicted_ratio: float,
                             ref_time: float) -> str:
        """Generate human-readable explanation"""

        surface = feature_row.get('surface', 'unknown')
        driver_mean = feature_row.get('driver_mean_ratio_surface', predicted_ratio)
        rally_mean = feature_row.get('driver_avg_ratio_this_rally', predicted_ratio)

        explanation = (
            f"Model prediction based on: "
            f"Driver's average on {surface} surfaces is {(driver_mean-1)*100:.1f}% slower than class leader. "
            f"In this rally, their average gap is {(rally_mean-1)*100:.1f}%. "
            f"Predicted ratio: {predicted_ratio:.3f}, "
            f"reference time: {self._format_time(ref_time)}."
        )

        return explanation

    def _format_time(self, seconds: float) -> str:
        """Format seconds to MM:SS.SS"""
        if seconds is None or seconds < 0:
            return "—"

        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}:{secs:05.2f}"

    def predict_for_manual_input(self,
                                 driver_id: str,
                                 driver_name: str,  # NEW: Accept driver_name from UI
                                 stage_length_km: float,
                                 surface: str,
                                 day_or_night: str = 'day',
                                 stage_number: int = 1,
                                 rally_name: str = "Manual Prediction") -> Dict:
        """
        Predict time for manual input parameters

        Args:
            driver_id: Driver ID from database
            driver_name: Driver name from UI selection (to avoid database mismatch)
            stage_length_km: Stage length in km
            surface: 'gravel' or 'asphalt'
            day_or_night: 'day' or 'night'
            stage_number: Stage number in rally
            rally_name: Optional rally name

        Returns:
            Dictionary with prediction results
        """
        logger.info(f"Manual prediction for {driver_id}: {stage_length_km}km, {surface}")

        # Get driver historical data with ratio_to_class_best calculation
        driver_history = self.db.load_dataframe(f"""
            WITH stage_class_best AS (
                SELECT stage_id, car_class, MIN(time_seconds) as class_best_time
                FROM clean_stage_results
                WHERE time_seconds > 0
                GROUP BY stage_id, car_class
            )
            SELECT c.*,
                   CAST(c.time_seconds AS REAL) / CAST(s.class_best_time AS REAL) as ratio_to_class_best
            FROM clean_stage_results c
            INNER JOIN stage_class_best s
                ON c.stage_id = s.stage_id AND c.car_class = s.car_class
            WHERE c.driver_id = '{driver_id}'
            AND s.class_best_time > 0
            ORDER BY c.rally_date DESC, c.stage_number DESC
            LIMIT 30
        """)

        if len(driver_history) == 0:
            raise ValueError(f"No historical data found for driver {driver_id}")

        # Get driver info (car_class from history, but use PROVIDED driver_name)
        last_result = driver_history.iloc[0]
        # IMPORTANT: Use driver_name from parameter, NOT from database
        # driver_name = last_result['driver_name']  # OLD - can be wrong!
        car_class = last_result['car_class']

        # Calculate momentum
        momentum_data = self._calculate_momentum(driver_history)

        # Build feature row
        feature_row = self._build_manual_feature_row(
            driver_id=driver_id,
            driver_name=driver_name,
            car_class=car_class,
            stage_length_km=stage_length_km,
            surface=surface,
            day_or_night=day_or_night,
            stage_number=stage_number,
            rally_name=rally_name,
            driver_history=driver_history
        )

        # Engineer features
        feature_df = pd.DataFrame([feature_row])
        feature_df = self.feature_engineer.engineer_all(feature_df)

        # Add avg_speed_kmh if not present
        if 'avg_speed_kmh' not in feature_df.columns:
            feature_df['avg_speed_kmh'] = (feature_df['stage_length_km'] / feature_df['time_seconds']) * 3600

        # Ensure all required features exist (add missing ones with 0)
        for feature in self.model.feature_names:
            if feature not in feature_df.columns:
                feature_df[feature] = 0

        # Select features in the same order as training
        X = feature_df[self.model.feature_names]

        # Predict ratio
        predicted_ratio = self.model.model.predict(X)[0]
        predicted_ratio = np.clip(predicted_ratio, self.min_ratio, self.max_ratio)

        # Estimate reference time based on historical data
        ref_time = self._estimate_reference_time_manual(
            car_class=car_class,
            stage_length_km=stage_length_km,
            surface=surface
        )

        # Calculate predicted time
        predicted_time = predicted_ratio * ref_time

        # Apply physical constraints
        min_speed = 40 if surface == 'gravel' else 50
        max_time_physical = (stage_length_km / min_speed) * 3600
        predicted_time = min(predicted_time, max_time_physical)

        # Calculate average speed
        predicted_speed = (stage_length_km / predicted_time) * 3600

        return {
            'driver_id': driver_id,
            'driver_name': driver_name,
            'car_class': car_class,
            'stage_length_km': stage_length_km,
            'surface': surface,
            'day_or_night': day_or_night,
            'predicted_ratio': round(predicted_ratio, 4),
            'reference_time_seconds': round(ref_time, 2),
            'reference_time_str': self._format_time(ref_time),
            'predicted_time_seconds': round(predicted_time, 2),
            'predicted_time_str': self._format_time(predicted_time),
            'predicted_speed_kmh': round(predicted_speed, 1),
            'momentum': momentum_data['momentum_str'],
            'momentum_delta': momentum_data['momentum_delta'],
            'recent_avg_ratio': momentum_data['recent_avg'],
            'historical_avg_ratio': momentum_data['historical_avg'],
            'confidence': 'medium',
            'explanation': self._generate_manual_explanation(
                driver_name=driver_name,  # Use the driver_name from database query, not feature_row
                surface=surface,
                predicted_ratio=predicted_ratio,
                ref_time=ref_time,
                momentum_data=momentum_data
            )
        }

    def _calculate_momentum(self, driver_history: pd.DataFrame) -> Dict:
        """Calculate driver momentum from recent vs previous races"""
        if len(driver_history) < 5:
            return {
                'momentum_str': '➡️ Insufficient data',
                'momentum_delta': 0.0,
                'recent_avg': 1.0,
                'historical_avg': 1.0
            }

        # Last 5 races vs previous 5
        recent_5 = driver_history.iloc[:5]['ratio_to_class_best'].mean()

        if len(driver_history) >= 10:
            prev_5 = driver_history.iloc[5:10]['ratio_to_class_best'].mean()
        else:
            prev_5 = driver_history.iloc[5:]['ratio_to_class_best'].mean()

        momentum = prev_5 - recent_5  # Positive = getting faster

        if momentum > 0.02:
            momentum_str = "📈 Hızlanıyor"
        elif momentum < -0.02:
            momentum_str = "📉 Yavaşlıyor"
        else:
            momentum_str = "➡️ Stabil"

        return {
            'momentum_str': momentum_str,
            'momentum_delta': round(momentum * 100, 1),
            'recent_avg': round(recent_5, 3),
            'historical_avg': round(prev_5, 3)
        }

    def _build_manual_feature_row(self,
                                  driver_id: str,
                                  driver_name: str,
                                  car_class: str,
                                  stage_length_km: float,
                                  surface: str,
                                  day_or_night: str,
                                  stage_number: int,
                                  rally_name: str,
                                  driver_history: pd.DataFrame) -> Dict:
        """Build feature dictionary for manual prediction"""
        import datetime

        # Start with manual input
        row = {
            'driver_id': driver_id,
            'driver_name': driver_name,
            'rally_id': f"manual_prediction_{datetime.datetime.now().strftime('%Y%m%d')}",
            'rally_name': rally_name,
            'rally_date': datetime.datetime.now().strftime('%Y-%m-%d'),
            'rally_year': datetime.datetime.now().year,
            'stage_id': f"manual_stage_{stage_number}",
            'stage_name': f"Manual Stage {stage_number}",
            'stage_number': stage_number,
            'stage_number_in_day': stage_number,
            'stage_length_km': stage_length_km,
            'surface': surface,
            'day_or_night': day_or_night,
            'car_class': car_class,
            'car_model': driver_history.iloc[0].get('car_model', 'Unknown'),
        }

        # Add dummy values
        row['overall_position_before'] = 999
        row['class_position_before'] = 999
        row['gap_to_leader_seconds'] = 0
        row['gap_to_class_leader_seconds'] = 0
        row['cumulative_stage_km'] = stage_length_km * (stage_number - 1)
        row['ratio_to_class_best'] = 1.0
        row['time_seconds'] = 600.0
        row['class_best_time'] = 600.0
        row['is_anomaly'] = False
        row['anomaly_reason'] = None
        row['status'] = 'FINISHED'
        row['raw_time_str'] = '10:00.0'
        row['result_id'] = f"manual_{driver_id}_{datetime.datetime.now().timestamp()}"

        return row

    def _estimate_reference_time_manual(self,
                                        car_class: str,
                                        stage_length_km: float,
                                        surface: str) -> float:
        """Estimate reference time for manual prediction"""
        # Query historical best times for similar stages
        # Use AVG of class leaders from similar-length stages (narrow range ±15%)
        query = f"""
        WITH stage_class_best AS (
            SELECT stage_id, car_class, MIN(time_seconds) as class_best_time
            FROM clean_stage_results
            WHERE time_seconds > 0
            GROUP BY stage_id, car_class
        )
        SELECT
            AVG(s.class_best_time / c.stage_length_km) as avg_speed_time_per_km,
            COUNT(DISTINCT c.stage_id) as stage_count
        FROM clean_stage_results c
        INNER JOIN stage_class_best s
            ON c.stage_id = s.stage_id AND c.car_class = s.car_class
        WHERE c.car_class = '{car_class}'
        AND c.surface = '{surface}'
        AND c.stage_length_km BETWEEN {stage_length_km * 0.85} AND {stage_length_km * 1.15}
        AND c.stage_length_km > 0
        """

        result = self.db.load_dataframe(query)

        if len(result) > 0 and not pd.isna(result['avg_speed_time_per_km'].iloc[0]):
            # Calculate reference time based on average speed from similar stages
            avg_time_per_km = result['avg_speed_time_per_km'].iloc[0]
            ref_time = avg_time_per_km * stage_length_km
            stage_count = result['stage_count'].iloc[0]
            logger.info(f"Using historical reference: {ref_time:.1f}s ({avg_time_per_km:.1f}s/km, {stage_count} stages) for {car_class} on {surface}")
            return ref_time
        else:
            # Fallback: estimate from typical speeds
            if surface == 'asphalt':
                typical_speed = 100  # km/h for top class on asphalt
            else:
                typical_speed = 85   # km/h for top class on gravel

            # Adjust for class
            class_factors = {
                'WRC': 1.0, 'Rally1': 1.0,
                'Rally2': 1.08, 'R5': 1.08,
                'Rally3': 1.15, 'R2': 1.15,
                'N4': 1.12
            }

            speed_factor = class_factors.get(car_class, 1.10)
            adjusted_speed = typical_speed / speed_factor

            ref_time = (stage_length_km / adjusted_speed) * 3600
            logger.warning(f"Using estimated reference: {ref_time:.1f}s (no historical data)")
            return ref_time

    def _generate_manual_explanation(self,
                                     driver_name: str,
                                     surface: str,
                                     predicted_ratio: float,
                                     ref_time: float,
                                     momentum_data: Dict) -> str:
        """Generate explanation for manual prediction"""
        explanation = (
            f"{driver_name} için tahmin: "
            f"{surface} yüzeyde sınıf liderinden {(predicted_ratio-1)*100:.1f}% daha yavaş. "
            f"Son performans trendi: {momentum_data['momentum_str']} "
            f"({momentum_data['momentum_delta']:+.1f}%). "
            f"Referans zaman: {self._format_time(ref_time)}."
        )
        return explanation

    def save_predictions(self, predictions_df: pd.DataFrame, output_path: str):
        """Save predictions to file"""
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        # Save as Excel for easy viewing
        predictions_df.to_excel(output_file, index=False)
        logger.info(f"Predictions saved to {output_path}")

        # Also save as CSV
        csv_path = output_file.with_suffix('.csv')
        predictions_df.to_csv(csv_path, index=False)

def main():
    """Example usage"""
    predictor = NotionalTimePredictor()

    # Example: SS2 was red-flagged
    rally_id = "example_rally_2024"
    stage_id = "example_rally_2024_ss2"
    affected_drivers = ["pilot_name"]  # Use actual driver_id from database

    predictions = predictor.predict_for_red_flag(
        rally_id=rally_id,
        stage_id=stage_id,
        affected_driver_ids=affected_drivers
    )

    # Display results
    print("\n" + "="*80)
    print("NOTIONAL TIME PREDICTIONS")
    print("="*80)
    print(predictions[['driver_name', 'car_class', 'notional_time_str',
                       'confidence', 'explanation']].to_string(index=False))

    # Save
    predictor.save_predictions(predictions, 'reports/notional_times_prediction.xlsx')

if __name__ == '__main__':
    main()
