"""Model training with proper validation"""
import pandas as pd
import numpy as np
import lightgbm as lgb
from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error
from scipy.stats import spearmanr
import joblib
import json
from pathlib import Path
import logging
from config.config_loader import config
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class RallyETAModel:
    """Rally ETA prediction model"""

    def __init__(self):
        self.model = None
        self.feature_names = None
        self.feature_importance = None
        self.config = config.get('model')

    def prepare_data_split(self, df: pd.DataFrame):
        """
        CRITICAL: Split by rally, not by rows (avoid leakage)
        For MVP with limited data, use simple row split
        """
        logger.info("Preparing data split...")

        # Get unique rallies sorted by date
        rally_dates = df.groupby('rally_id')['rally_date'].first().sort_values()
        rallies = rally_dates.index.tolist()

        n_rallies = len(rallies)

        # If only 1 rally (MVP), do simple row-based split
        if n_rallies == 1:
            logger.warning("Only 1 rally found - using row-based split for MVP")
            n_samples = len(df)
            train_size = int(n_samples * self.config['split']['train_ratio'])
            val_size = int(n_samples * self.config['split']['val_ratio'])

            train_df = df.iloc[:train_size]
            val_df = df.iloc[train_size:train_size + val_size]
            test_df = df.iloc[train_size + val_size:]
        else:
            # Normal rally-based split
            train_size = int(n_rallies * self.config['split']['train_ratio'])
            val_size = int(n_rallies * self.config['split']['val_ratio'])

            train_rallies = rallies[:train_size]
            val_rallies = rallies[train_size:train_size + val_size]
            test_rallies = rallies[train_size + val_size:]

            train_df = df[df['rally_id'].isin(train_rallies)]
            val_df = df[df['rally_id'].isin(val_rallies)]
            test_df = df[df['rally_id'].isin(test_rallies)]

        logger.info(f"Train: {len(train_df)} rows")
        logger.info(f"Val: {len(val_df)} rows")
        logger.info(f"Test: {len(test_df)} rows")

        return train_df, val_df, test_df

    def select_features(self, df: pd.DataFrame):
        """Select training features"""
        exclude_cols = [
            'result_id', 'rally_id', 'stage_id', 'driver_id',
            'rally_name', 'rally_date', 'stage_name', 'driver_name',
            'car_model', 'surface', 'day_or_night',
            'raw_time_str', 'time_seconds', 'status',
            'class_best_time', 'ratio_to_class_best',  # target
            'is_anomaly', 'anomaly_reason', 'created_at',
            'car_class'  # already one-hot encoded
        ]

        feature_cols = [col for col in df.columns if col not in exclude_cols]

        # Only keep numeric columns (exclude object dtype)
        numeric_cols = df[feature_cols].select_dtypes(include=[np.number]).columns.tolist()
        self.feature_names = numeric_cols

        logger.info(f"Selected {len(numeric_cols)} numeric features")
        return numeric_cols

    def train(self, train_df: pd.DataFrame, val_df: pd.DataFrame):
        """Train LightGBM model"""
        logger.info("Training model...")

        feature_cols = self.select_features(train_df)

        X_train = train_df[feature_cols]
        y_train = train_df['ratio_to_class_best']

        # If validation set is empty, use training set for validation
        if len(val_df) == 0:
            logger.warning("Validation set is empty - using train set for validation")
            X_val = X_train
            y_val = y_train
        else:
            X_val = val_df[feature_cols]
            y_val = val_df['ratio_to_class_best']

        # LightGBM datasets
        train_data = lgb.Dataset(X_train, label=y_train)
        val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)

        # Training parameters
        params = {
            'objective': self.config['hyperparameters']['objective'],
            'metric': self.config['hyperparameters']['metric'],
            'learning_rate': self.config['hyperparameters']['learning_rate'],
            'max_depth': self.config['hyperparameters']['max_depth'],
            'num_leaves': self.config['hyperparameters']['num_leaves'],
            'min_child_samples': self.config['hyperparameters']['min_child_samples'],
            'subsample': self.config['hyperparameters']['subsample'],
            'colsample_bytree': self.config['hyperparameters']['colsample_bytree'],
            'reg_alpha': self.config['hyperparameters']['reg_alpha'],
            'reg_lambda': self.config['hyperparameters']['reg_lambda'],
            'random_state': self.config['hyperparameters']['random_state'],
            'verbose': -1
        }

        # Train
        self.model = lgb.train(
            params,
            train_data,
            num_boost_round=self.config['hyperparameters']['n_estimators'],
            valid_sets=[train_data, val_data],
            valid_names=['train', 'val']
        )

        # Feature importance
        self.feature_importance = dict(zip(
            self.feature_names,
            self.model.feature_importance(importance_type='gain')
        ))

        logger.info("Training complete")

    def evaluate(self, df: pd.DataFrame, split_name: str):
        """Evaluate model"""
        X = df[self.feature_names]
        y_true = df['ratio_to_class_best']

        y_pred = self.model.predict(X)

        # Apply constraints
        min_ratio = config.get('inference.constraints.min_ratio')
        max_ratio = config.get('inference.constraints.max_ratio')
        y_pred = np.clip(y_pred, min_ratio, max_ratio)

        # Metrics
        mae = mean_absolute_error(y_true, y_pred)
        mape = mean_absolute_percentage_error(y_true, y_pred)
        corr, _ = spearmanr(y_true, y_pred)

        logger.info(f"{split_name} - MAE: {mae:.4f}, MAPE: {mape:.4f}, Correlation: {corr:.4f}")

        return {
            'mae': mae,
            'mape': mape,
            'correlation': corr,
            'predictions': y_pred,
            'actuals': y_true
        }

    def save(self, model_dir: str = 'models/rally_eta_v1'):
        """Save model and metadata"""
        model_path = Path(model_dir)
        model_path.mkdir(parents=True, exist_ok=True)

        # Save model
        joblib.dump(self.model, model_path / 'model.pkl')

        # Save metadata
        metadata = {
            'feature_names': self.feature_names,
            'feature_importance': self.feature_importance,
            'config': self.config
        }

        with open(model_path / 'metadata.json', 'w') as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"Model saved to {model_path}")

    def load(self, model_dir: str = 'models/rally_eta_v1'):
        """Load trained model"""
        model_path = Path(model_dir)

        self.model = joblib.load(model_path / 'model.pkl')

        with open(model_path / 'metadata.json', 'r') as f:
            metadata = json.load(f)

        self.feature_names = metadata['feature_names']
        self.feature_importance = metadata['feature_importance']

        logger.info(f"Model loaded from {model_path}")


if __name__ == '__main__':
    # Load features
    df = pd.read_parquet('data/processed/features.parquet')
    logger.info(f"Loaded {len(df)} samples with {len(df.columns)} columns")

    # Train model
    model = RallyETAModel()

    # Split data
    train_df, val_df, test_df = model.prepare_data_split(df)

    # Train
    model.train(train_df, val_df)

    # Evaluate
    train_metrics = model.evaluate(train_df, 'Train')
    val_metrics = model.evaluate(val_df, 'Validation')
    test_metrics = model.evaluate(test_df, 'Test')

    # Save
    model.save()

    logger.info("Training pipeline complete!")
