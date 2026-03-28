from __future__ import annotations

"""
Model Trainer - LightGBM model egitimi ve kaydetme.

stages_metadata ve stage_results tablolarindan feature olusturup
LightGBM modeli egitir.
"""
import sqlite3
import pickle
import logging
from importlib import import_module
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass

try:
    import numpy as np
except ImportError:
    np = None

try:
    import pandas as pd
except ImportError:
    pd = None

logger = logging.getLogger(__name__)


def _load_training_dependencies() -> Dict[str, object]:
    """Load sklearn pieces lazily with compatibility for older/frozen builds."""
    try:
        model_selection = import_module('sklearn.model_selection')
        metrics = import_module('sklearn.metrics')
        inspection = import_module('sklearn.inspection')
    except ImportError:
        raise

    try:
        ensemble = import_module('sklearn.ensemble')
        hist_gradient_boosting = getattr(ensemble, 'HistGradientBoostingRegressor')
    except (ImportError, AttributeError) as primary_error:
        try:
            import_module('sklearn.experimental.enable_hist_gradient_boosting')
            ensemble = import_module('sklearn.ensemble')
            hist_gradient_boosting = getattr(ensemble, 'HistGradientBoostingRegressor')
        except (ImportError, AttributeError) as secondary_error:
            cause = secondary_error or primary_error
            raise ImportError(
                "cannot import name 'HistGradientBoostingRegressor' from 'sklearn.ensemble'"
            ) from cause

    return {
        'train_test_split': model_selection.train_test_split,
        'mean_absolute_error': metrics.mean_absolute_error,
        'mean_squared_error': metrics.mean_squared_error,
        'r2_score': metrics.r2_score,
        'permutation_importance': inspection.permutation_importance,
        'HistGradientBoostingRegressor': hist_gradient_boosting,
    }


@dataclass
class TrainingResult:
    """Model egitim sonucu."""
    success: bool
    model_path: Optional[str]
    metrics: Dict
    feature_importance: Dict
    training_samples: int
    validation_samples: int
    error_message: Optional[str] = None


class ModelTrainer:
    """
    LightGBM model egitici.

    3-Stage Pipeline icin Geometric Correction modeli egitir:
    - Input: baseline_ratio + geometric features + driver profile
    - Output: correction_factor (actual_ratio / baseline_ratio)
    """

    # Feature kolonlari
    NUMERIC_FEATURES = [
        'baseline_ratio',
        'stage_length_km',
        'hairpin_count',
        'hairpin_density',
        'turn_count',
        'turn_density',
        'total_ascent',
        'total_descent',
        'avg_curvature',
        'max_curvature',
        'p95_curvature',
        'curvature_density',
        'avg_grade',
        'max_grade',
        'avg_abs_grade',
        'straight_percentage',
        'curvy_percentage',
        'driver_stage_count',
        'driver_avg_ratio',
        'driver_surface_ratio',
        'momentum_factor',
    ]

    CATEGORICAL_FEATURES = [
        'surface',
        'normalized_class',
    ]

    def __init__(self, db_path: str, model_dir: str = 'models'):
        """
        Initialize trainer.

        Args:
            db_path: Veritabani yolu
            model_dir: Model kayit klasoru
        """
        self.db_path = db_path
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(exist_ok=True)

    def prepare_training_data(self) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Egitim verisi hazirla.

        Returns:
            (X, y) feature matrix ve target
        """
        conn = sqlite3.connect(self.db_path)

        # Ana query: stage_results + stages_metadata
        # stage_id olustur: rally_id || '_ss' || stage_number
        query = """
            SELECT
                sr.result_id,
                COALESCE(sr.driver_id, sr.driver_name) as driver_id,
                COALESCE(sr.raw_driver_name, sr.driver_name) as driver_name,
                COALESCE(sr.stage_id, sr.rally_id || '_ss' || sr.stage_number) as stage_id,
                sr.rally_id,
                sr.time_seconds,
                sm.distance_km as stage_length_km,
                COALESCE(sm.surface, sr.surface, 'gravel') as surface,
                sr.car_class,
                COALESCE(sr.normalized_class, sr.car_class) as normalized_class,
                -- stages_metadata
                sm.distance_km as geo_distance_km,
                sm.hairpin_count,
                sm.hairpin_density,
                COALESCE(sm.turn_count, 0) as turn_count,
                COALESCE(sm.turn_density, 0) as turn_density,
                sm.total_ascent,
                sm.total_descent,
                sm.avg_curvature,
                sm.max_curvature,
                sm.p95_curvature,
                sm.curvature_density,
                sm.max_grade,
                sm.avg_abs_grade,
                sm.straight_percentage,
                sm.curvy_percentage
            FROM stage_results sr
            INNER JOIN stages_metadata sm
                ON COALESCE(sr.stage_id, sr.rally_id || '_ss' || sr.stage_number) = sm.stage_id
            WHERE sr.time_seconds > 0
            AND sm.hairpin_count IS NOT NULL
        """

        df = pd.read_sql_query(query, conn)
        conn.close()

        if len(df) == 0:
            logger.warning("Egitim verisi bulunamadi! stages_metadata bos olabilir.")
            return pd.DataFrame(), pd.DataFrame()

        logger.info(f"Ham veri: {len(df)} satir")

        # Class best time hesapla
        df = self._calculate_class_best(df)

        # Ratio hesapla
        df['ratio'] = df['time_seconds'] / df['class_best_time']
        df = df[df['ratio'] > 0.5]  # Outlier filtrele
        df = df[df['ratio'] < 2.0]

        # Driver features hesapla
        df = self._calculate_driver_features(df)

        # Baseline ratio (son 15 etap ortalamasi - simulasyon)
        df['baseline_ratio'] = df.groupby('driver_id')['ratio'].transform(
            lambda x: x.rolling(15, min_periods=1).mean().shift(1)
        )
        df['baseline_ratio'] = df['baseline_ratio'].fillna(df['ratio'].mean())

        # Target: correction factor
        df['correction_factor'] = df['ratio'] / df['baseline_ratio']

        # Outlier filtrele
        df = df[df['correction_factor'] > 0.8]
        df = df[df['correction_factor'] < 1.2]

        logger.info(f"Temiz veri: {len(df)} satir")

        # Features
        feature_cols = []
        for col in self.NUMERIC_FEATURES:
            if col in df.columns:
                feature_cols.append(col)

        # Fill NaN
        for col in feature_cols:
            df[col] = df[col].fillna(0)

        # Categorical encoding
        for col in self.CATEGORICAL_FEATURES:
            if col in df.columns:
                df[col] = df[col].fillna('unknown')
                df[col] = df[col].astype('category')
                feature_cols.append(col)

        X = df[feature_cols]
        y = df['correction_factor']

        return X, y

    def _calculate_class_best(self, df: pd.DataFrame) -> pd.DataFrame:
        """Her etap icin class best time hesapla."""
        # Normalize class
        if 'normalized_class' not in df.columns:
            df['normalized_class'] = df['car_class'].fillna('Unknown')

        # Class best = her (stage_id, normalized_class) icin min time
        class_best = df.groupby(['stage_id', 'normalized_class'])['time_seconds'].transform('min')
        df['class_best_time'] = class_best

        # 0 olan class_best'leri duzelt
        df.loc[df['class_best_time'] == 0, 'class_best_time'] = df['time_seconds']

        return df

    def _calculate_driver_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Driver bazli featurelar hesapla."""
        # Driver stage count
        df['driver_stage_count'] = df.groupby('driver_id').cumcount() + 1

        # Driver average ratio
        df['driver_avg_ratio'] = df.groupby('driver_id')['ratio'].transform('mean')

        # Surface-specific ratio
        df['driver_surface_ratio'] = df.groupby(['driver_id', 'surface'])['ratio'].transform('mean')
        df['driver_surface_ratio'] = df['driver_surface_ratio'].fillna(df['driver_avg_ratio'])

        # Momentum (son 3 etap vs onceki 3 etap)
        df['recent_ratio'] = df.groupby('driver_id')['ratio'].transform(
            lambda x: x.rolling(3, min_periods=1).mean()
        )
        df['older_ratio'] = df.groupby('driver_id')['ratio'].transform(
            lambda x: x.rolling(6, min_periods=1).mean().shift(3)
        )
        df['momentum_factor'] = df['recent_ratio'] / df['older_ratio'].replace(0, 1)
        df['momentum_factor'] = df['momentum_factor'].fillna(1.0)

        return df

    def train(self, test_size: float = 0.2, random_state: int = 42) -> TrainingResult:
        """
        Model egit.

        Args:
            test_size: Test seti orani
            random_state: Random seed

        Returns:
            TrainingResult
        """
        missing_base_dependencies = []
        if np is None:
            missing_base_dependencies.append('numpy')
        if pd is None:
            missing_base_dependencies.append('pandas')

        if missing_base_dependencies:
            return TrainingResult(
                success=False,
                model_path=None,
                metrics={},
                feature_importance={},
                training_samples=0,
                validation_samples=0,
                error_message=(
                    "Import hatasi: eksik bagimliliklar: "
                    + ", ".join(missing_base_dependencies)
                ),
            )

        try:
            dependencies = _load_training_dependencies()
        except ImportError as e:
            return TrainingResult(
                success=False,
                model_path=None,
                metrics={},
                feature_importance={},
                training_samples=0,
                validation_samples=0,
                error_message=f"Import hatasi: {e}"
            )

        train_test_split = dependencies['train_test_split']
        mean_absolute_error = dependencies['mean_absolute_error']
        mean_squared_error = dependencies['mean_squared_error']
        r2_score = dependencies['r2_score']
        permutation_importance = dependencies['permutation_importance']
        HistGradientBoostingRegressor = dependencies['HistGradientBoostingRegressor']

        # Veri hazirla
        X, y = self.prepare_training_data()

        if len(X) == 0:
            return TrainingResult(
                success=False,
                model_path=None,
                metrics={},
                feature_importance={},
                training_samples=0,
                validation_samples=0,
                error_message="Egitim verisi bulunamadi"
            )

        # Train/test split
        X_train, X_val, y_train, y_val = train_test_split(
            X, y, test_size=test_size, random_state=random_state
        )

        logger.info(f"Training: {len(X_train)}, Validation: {len(X_val)}")

        # HistGradientBoostingRegressor (LightGBM benzeri, sklearn icinde)
        model = HistGradientBoostingRegressor(
            max_iter=300,
            max_depth=6,
            learning_rate=0.05,
            min_samples_leaf=20,
            l2_regularization=0.1,
            early_stopping=True,
            validation_fraction=0.1,
            n_iter_no_change=50,
            random_state=random_state,
            verbose=0
        )

        # Train
        model.fit(X_train, y_train)

        # Evaluate
        y_pred = model.predict(X_val)

        mae = mean_absolute_error(y_val, y_pred)
        rmse = np.sqrt(mean_squared_error(y_val, y_pred))
        mape = np.mean(np.abs((y_val - y_pred) / y_val)) * 100

        # R² hesapla
        r2 = r2_score(y_val, y_pred)

        metrics = {
            'mae': float(mae),
            'rmse': float(rmse),
            'mape': float(mape),
            'r2': float(r2),
            'mean_correction': float(y_val.mean()),
            'std_correction': float(y_val.std()),
        }

        logger.info(f"MAE: {mae:.4f}, RMSE: {rmse:.4f}, MAPE: {mape:.2f}%, R2: {r2:.4f}")

        # Feature importance - permutation importance kullan
        perm_importance = permutation_importance(model, X_val, y_val, n_repeats=10, random_state=random_state)
        importance = {col: float(imp) for col, imp in zip(X.columns, perm_importance.importances_mean)}

        # Save model
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        model_path = self.model_dir / f'geometric_model_{timestamp}.pkl'

        model_data = {
            'model': model,
            'feature_columns': X.columns.tolist(),
            'categorical_features': self.CATEGORICAL_FEATURES,
            'metrics': metrics,
            'feature_importance': importance,
            'training_date': timestamp,
            'training_samples': len(X_train),
            'validation_samples': len(X_val),
        }

        with open(model_path, 'wb') as f:
            pickle.dump(model_data, f)

        # Also save as latest
        latest_path = self.model_dir / 'geometric_model_latest.pkl'
        with open(latest_path, 'wb') as f:
            pickle.dump(model_data, f)

        logger.info(f"Model kaydedildi: {model_path}")

        return TrainingResult(
            success=True,
            model_path=str(model_path),
            metrics=metrics,
            feature_importance=importance,
            training_samples=len(X_train),
            validation_samples=len(X_val)
        )

    def load_model(self, model_path: Optional[str] = None) -> Optional[Dict]:
        """
        Model yukle.

        Args:
            model_path: Model dosya yolu (None ise latest)

        Returns:
            Model data dict
        """
        if model_path is None:
            model_path = self.model_dir / 'geometric_model_latest.pkl'
        else:
            model_path = Path(model_path)

        if not model_path.exists():
            logger.warning(f"Model bulunamadi: {model_path}")
            return None

        with open(model_path, 'rb') as f:
            model_data = pickle.load(f)

        logger.info(f"Model yuklendi: {model_path}")
        return model_data

    def get_training_status(self) -> Dict:
        """Egitim durumu bilgilerini getir."""
        status = {
            'model_exists': False,
            'model_path': None,
            'training_date': None,
            'metrics': None,
            'can_train': False,
            'reason': None,
        }

        # Model var mi?
        latest_path = self.model_dir / 'geometric_model_latest.pkl'
        if latest_path.exists():
            model_data = self.load_model()
            if model_data:
                status['model_exists'] = True
                status['model_path'] = str(latest_path)
                status['training_date'] = model_data.get('training_date')
                status['metrics'] = model_data.get('metrics')

        # Egitim verisi var mi?
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT COUNT(*)
            FROM stage_results sr
            INNER JOIN stages_metadata sm
                ON (sr.rally_id || '_ss' || sr.stage_number) = sm.stage_id
            WHERE sr.time_seconds > 0
        """)
        training_data_count = cursor.fetchone()[0]
        conn.close()

        status['training_data_count'] = training_data_count

        if training_data_count > 100:
            status['can_train'] = True
        else:
            status['reason'] = f"Yetersiz veri ({training_data_count} < 100)"

        return status


def main():
    """Test model trainer."""
    import argparse

    parser = argparse.ArgumentParser(description="Model Trainer")
    parser.add_argument('--db-path', default='data/raw/rally_results.db')
    parser.add_argument('--model-dir', default='models')
    parser.add_argument('--train', action='store_true', help='Model egit')
    parser.add_argument('--status', action='store_true', help='Egitim durumu')

    args = parser.parse_args()

    trainer = ModelTrainer(args.db_path, args.model_dir)

    if args.status:
        status = trainer.get_training_status()
        print("Egitim Durumu:")
        for key, value in status.items():
            print(f"  {key}: {value}")

    if args.train:
        print("Model egitiliyor...")
        result = trainer.train()

        if result.success:
            print(f"\nBasarili!")
            print(f"Model: {result.model_path}")
            print(f"Training samples: {result.training_samples}")
            print(f"Validation samples: {result.validation_samples}")
            print(f"\nMetrics:")
            for key, value in result.metrics.items():
                print(f"  {key}: {value:.4f}")
            print(f"\nTop 10 Features:")
            for i, (feat, imp) in enumerate(list(result.feature_importance.items())[:10]):
                print(f"  {i+1}. {feat}: {imp}")
        else:
            print(f"Hata: {result.error_message}")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
