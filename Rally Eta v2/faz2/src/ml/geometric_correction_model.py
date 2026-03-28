from __future__ import annotations

"""
LightGBM Geometric Correction Model.

Predicts correction factor based on:
- Stage geometry (hairpins, climb, curvature)
- Driver geometry profile
- Baseline prediction

correction_factor = actual_ratio / baseline_ratio
final_ratio = baseline_ratio * correction_factor
"""
import logging
import pickle
import json
from pathlib import Path
from typing import Dict, Optional, Tuple, List
from datetime import datetime

try:
    import numpy as np
except ImportError:
    np = None

try:
    import pandas as pd
except ImportError:
    pd = None

try:
    import lightgbm as lgb
    LIGHTGBM_AVAILABLE = True
except ImportError:
    LIGHTGBM_AVAILABLE = False
    lgb = None

logger = logging.getLogger(__name__)


def _require_ml_dependencies():
    """Raise a clear error when optional ML dependencies are missing."""
    missing = []
    if np is None:
        missing.append('numpy')
    if pd is None:
        missing.append('pandas')
    if not LIGHTGBM_AVAILABLE:
        missing.append('lightgbm')

    if missing:
        raise ImportError(
            "GeometricCorrectionModel requires optional dependencies: "
            + ", ".join(missing)
        )


class GeometricCorrectionModel:
    """
    LightGBM-based geometric correction model.

    Predicts how much to adjust baseline prediction based on
    stage geometry and driver characteristics.
    """

    # Default model parameters (tuned for small dataset, prevent overfitting)
    DEFAULT_PARAMS = {
        'objective': 'regression',
        'metric': 'mae',
        'boosting_type': 'gbdt',

        # Tree structure (conservative to prevent overfitting)
        'max_depth': 6,
        'num_leaves': 31,
        'min_child_samples': 50,

        # Learning
        'learning_rate': 0.03,
        'n_estimators': 500,

        # Regularization
        'lambda_l1': 0.1,
        'lambda_l2': 0.1,
        'min_gain_to_split': 0.01,

        # Subsampling
        'subsample': 0.8,
        'subsample_freq': 1,
        'colsample_bytree': 0.8,

        # Monotone constraints (optional, domain knowledge)
        # Higher hairpin/climb should not decrease correction factor

        # Misc
        'verbose': -1,
        'random_state': 42
    }

    # Categorical features
    CATEGORICAL_FEATURES = ['surface', 'normalized_class']

    def __init__(self, params: Dict = None):
        """
        Initialize model.

        Args:
            params: LightGBM parameters (uses defaults if not provided)
        """
        _require_ml_dependencies()

        self.params = {**self.DEFAULT_PARAMS, **(params or {})}
        self.model = None
        self.feature_names = None
        self.training_info = {}

    def train(self, X: pd.DataFrame, y: pd.Series,
              validation_split: float = 0.2,
              early_stopping_rounds: int = 50) -> Dict:
        """
        Train the model.

        Args:
            X: Feature DataFrame
            y: Target Series (correction_factor)
            validation_split: Fraction for validation
            early_stopping_rounds: Early stopping patience

        Returns:
            Training metrics dict
        """
        _require_ml_dependencies()
        logger.info(f"Training model with {len(X)} samples")

        # Store feature names
        self.feature_names = list(X.columns)

        # Encode categorical features
        X_encoded = self._encode_categoricals(X)

        # Split data
        n_val = int(len(X_encoded) * validation_split)
        indices = np.random.permutation(len(X_encoded))

        train_idx = indices[n_val:]
        val_idx = indices[:n_val]

        X_train = X_encoded.iloc[train_idx]
        y_train = y.iloc[train_idx]
        X_val = X_encoded.iloc[val_idx]
        y_val = y.iloc[val_idx]

        logger.info(f"Train: {len(X_train)}, Validation: {len(X_val)}")

        # Create datasets
        train_data = lgb.Dataset(
            X_train, y_train,
            categorical_feature=self._get_categorical_indices(X_encoded)
        )
        val_data = lgb.Dataset(
            X_val, y_val,
            categorical_feature=self._get_categorical_indices(X_encoded),
            reference=train_data
        )

        # Train with early stopping
        callbacks = [
            lgb.early_stopping(stopping_rounds=early_stopping_rounds),
            lgb.log_evaluation(period=100)
        ]

        self.model = lgb.train(
            self.params,
            train_data,
            valid_sets=[train_data, val_data],
            valid_names=['train', 'valid'],
            callbacks=callbacks
        )

        # Calculate metrics
        train_pred = self.model.predict(X_train)
        val_pred = self.model.predict(X_val)

        train_mae = np.mean(np.abs(train_pred - y_train))
        val_mae = np.mean(np.abs(val_pred - y_val))
        train_mape = np.mean(np.abs((train_pred - y_train) / y_train)) * 100
        val_mape = np.mean(np.abs((val_pred - y_val) / y_val)) * 100

        # Store training info
        self.training_info = {
            'train_samples': len(X_train),
            'val_samples': len(X_val),
            'train_mae': float(train_mae),
            'val_mae': float(val_mae),
            'train_mape': float(train_mape),
            'val_mape': float(val_mape),
            'best_iteration': self.model.best_iteration,
            'feature_importance': dict(zip(
                self.feature_names,
                self.model.feature_importance(importance_type='gain').tolist()
            )),
            'trained_at': datetime.now().isoformat(),
            'params': self.params
        }

        logger.info(f"Training complete. Val MAE: {val_mae:.4f}, Val MAPE: {val_mape:.2f}%")

        return self.training_info

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """
        Predict correction factors.

        Args:
            X: Feature DataFrame

        Returns:
            Array of correction factors
        """
        _require_ml_dependencies()
        if self.model is None:
            raise ValueError("Model not trained. Call train() first.")

        X_encoded = self._encode_categoricals(X)
        predictions = self.model.predict(X_encoded)

        # Clip to reasonable range
        predictions = np.clip(predictions, 0.85, 1.15)

        return predictions

    def predict_single(self, features: Dict) -> float:
        """
        Predict for a single sample.

        Args:
            features: Feature dictionary

        Returns:
            Correction factor
        """
        _require_ml_dependencies()
        # Convert to DataFrame
        X = pd.DataFrame([features])

        # Ensure all columns are present
        for col in self.feature_names:
            if col not in X.columns:
                X[col] = 0

        X = X[self.feature_names]

        return float(self.predict(X)[0])

    def get_feature_importance(self) -> Dict[str, float]:
        """Get feature importance from trained model."""
        if self.model is None:
            return {}

        importance = self.model.feature_importance(importance_type='gain')
        return dict(sorted(
            zip(self.feature_names, importance),
            key=lambda x: x[1],
            reverse=True
        ))

    def save(self, path: str):
        """
        Save model to disk.

        Args:
            path: Path to save model (will create .pkl and .json files)
        """
        if self.model is None:
            raise ValueError("No model to save")

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Save model
        model_path = path.with_suffix('.pkl')
        with open(model_path, 'wb') as f:
            pickle.dump({
                'model': self.model,
                'feature_names': self.feature_names,
                'params': self.params
            }, f)

        # Save training info as JSON
        info_path = path.with_suffix('.json')
        with open(info_path, 'w') as f:
            json.dump(self.training_info, f, indent=2)

        logger.info(f"Model saved to {model_path}")

    def load(self, path: str):
        """
        Load model from disk.

        Args:
            path: Path to model file (.pkl)
        """
        path = Path(path)

        if not path.suffix:
            path = path.with_suffix('.pkl')

        with open(path, 'rb') as f:
            data = pickle.load(f)

        self.model = data['model']
        # Support both key names: 'feature_names' (new) and 'feature_columns' (old)
        self.feature_names = data.get('feature_names') or data.get('feature_columns')
        self.params = data.get('params', {})

        # Load training info if available
        info_path = path.with_suffix('.json')
        if info_path.exists():
            with open(info_path, 'r') as f:
                self.training_info = json.load(f)

        logger.info(f"Model loaded from {path}")

    def _encode_categoricals(self, X: pd.DataFrame) -> pd.DataFrame:
        """Encode categorical features as category dtype."""
        _require_ml_dependencies()
        X = X.copy()

        for col in self.CATEGORICAL_FEATURES:
            if col in X.columns:
                X[col] = X[col].astype('category')

        return X

    def _get_categorical_indices(self, X: pd.DataFrame) -> List[int]:
        """Get indices of categorical columns."""
        indices = []
        for i, col in enumerate(X.columns):
            if col in self.CATEGORICAL_FEATURES:
                indices.append(i)
        return indices


class ModelWithFallback:
    """
    Model wrapper with fallback to baseline-only prediction.

    Used when:
    - No geometric data available for stage
    - Model prediction fails
    - Confidence is too low
    """

    def __init__(self, model: GeometricCorrectionModel = None):
        """
        Initialize wrapper.

        Args:
            model: Trained GeometricCorrectionModel (optional)
        """
        self.model = model
        self.has_model = model is not None and model.model is not None

    def predict(self, features: Dict, require_geometry: bool = False) -> Tuple[float, str]:
        """
        Predict with fallback.

        Args:
            features: Feature dictionary
            require_geometry: If True, fail when geometry missing

        Returns:
            (correction_factor, mode)
            mode is 'geometric' or 'fallback'
        """
        # Check if we have geometry data
        has_geometry = (
            features.get('hairpin_density') is not None and
            features.get('hairpin_density') > 0
        )

        if not has_geometry:
            if require_geometry:
                raise ValueError("Geometry data required but not available")
            logger.info("No geometry data - using fallback (correction=1.0)")
            return 1.0, 'fallback'

        if not self.has_model:
            logger.info("No trained model - using fallback (correction=1.0)")
            return 1.0, 'fallback'

        try:
            correction = self.model.predict_single(features)
            return correction, 'geometric'
        except Exception as e:
            logger.warning(f"Model prediction failed: {e} - using fallback")
            return 1.0, 'fallback'


def main():
    """Test geometric correction model."""
    import argparse

    parser = argparse.ArgumentParser(description="Geometric Correction Model")
    parser.add_argument('--test', action='store_true', help='Run synthetic test')

    args = parser.parse_args()

    if args.test:
        _require_ml_dependencies()
        print("Running synthetic model test...")

        # Create synthetic data
        np.random.seed(42)
        n_samples = 500

        X = pd.DataFrame({
            'distance_km': np.random.uniform(5, 25, n_samples),
            'hairpin_count': np.random.randint(0, 20, n_samples),
            'hairpin_density': np.random.uniform(0, 2, n_samples),
            'turn_count': np.random.randint(5, 50, n_samples),
            'turn_density': np.random.uniform(1, 5, n_samples),
            'total_ascent': np.random.uniform(0, 800, n_samples),
            'total_descent': np.random.uniform(0, 800, n_samples),
            'elevation_gain': np.random.uniform(0, 500, n_samples),
            'max_grade': np.random.uniform(0, 15, n_samples),
            'avg_abs_grade': np.random.uniform(0, 8, n_samples),
            'avg_curvature': np.random.uniform(0, 0.01, n_samples),
            'max_curvature': np.random.uniform(0, 0.05, n_samples),
            'p95_curvature': np.random.uniform(0, 0.02, n_samples),
            'curvature_density': np.random.uniform(0, 5, n_samples),
            'straight_percentage': np.random.uniform(20, 80, n_samples),
            'curvy_percentage': np.random.uniform(5, 40, n_samples),
            'driver_hairpin_perf': np.random.uniform(0.95, 1.05, n_samples),
            'driver_climb_perf': np.random.uniform(0.95, 1.05, n_samples),
            'driver_curvature_sens': np.random.uniform(0.95, 1.05, n_samples),
            'driver_grade_perf': np.random.uniform(0.95, 1.05, n_samples),
            'driver_profile_confidence': np.random.uniform(0.3, 1.0, n_samples),
            'baseline_ratio': np.random.uniform(1.0, 1.1, n_samples),
            'momentum_factor': np.random.uniform(0.98, 1.02, n_samples),
            'surface_adjustment': np.random.uniform(0.97, 1.03, n_samples),
            'hairpin_x_driver': np.random.uniform(0, 2, n_samples),
            'climb_x_driver': np.random.uniform(0, 800, n_samples),
            'curvature_x_driver': np.random.uniform(0, 0.02, n_samples),
            'surface': np.random.choice(['gravel', 'asphalt'], n_samples),
            'normalized_class': np.random.choice(['Rally2', 'Rally3', 'Rally4'], n_samples)
        })

        # Synthetic target with some patterns
        y = (
            1.0 +
            0.002 * X['hairpin_density'] +
            0.00001 * X['total_ascent'] +
            0.001 * X['max_grade'] +
            0.5 * (X['driver_hairpin_perf'] - 1) +
            np.random.normal(0, 0.01, n_samples)
        )

        # Train model
        model = GeometricCorrectionModel()
        metrics = model.train(X, y)

        print("\nTraining Results:")
        print(f"  Train MAE: {metrics['train_mae']:.4f}")
        print(f"  Val MAE: {metrics['val_mae']:.4f}")
        print(f"  Train MAPE: {metrics['train_mape']:.2f}%")
        print(f"  Val MAPE: {metrics['val_mape']:.2f}%")
        print(f"  Best iteration: {metrics['best_iteration']}")

        print("\nTop 10 Feature Importance:")
        importance = model.get_feature_importance()
        for i, (feat, imp) in enumerate(list(importance.items())[:10]):
            print(f"  {i+1}. {feat}: {imp:.2f}")

        # Test prediction
        print("\nTest prediction:")
        test_features = dict(X.iloc[0])
        pred = model.predict_single(test_features)
        print(f"  Correction factor: {pred:.4f}")
        print(f"  Actual: {y.iloc[0]:.4f}")

        print("\n✓ Model test completed successfully!")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
