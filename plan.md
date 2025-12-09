# Rally Stage ETA Prediction - MVP Implementation Plan

## Project Overview

**Goal**: Build a machine learning system to predict notional times for rally drivers affected by red-flagged stages.

**Success Criteria**:
- MAPE < 2.5% on test set
- Class-fair predictions (within-class ranking preserved)
- Explainable predictions for race officials
- No predictions faster than class best time

---

## Phase 1: Project Setup (Day 1)

### 1.1 Directory Structure
```
rally-eta-prediction/
├── README.md
├── requirements.txt
├── setup.py
├── .gitignore
│
├── config/
│   ├── config.yaml
│   └── config_loader.py
│
├── data/
│   ├── raw/              # Scraped data
│   ├── processed/        # Cleaned and feature-engineered data
│   └── external/         # Manual data (if any)
│
├── src/
│   ├── __init__.py
│   │
│   ├── scraper/
│   │   ├── __init__.py
│   │   ├── base_scraper.py
│   │   ├── tosfed_scraper.py
│   │   ├── ewrc_scraper.py
│   │   └── orchestrator.py
│   │
│   ├── preprocessing/
│   │   ├── __init__.py
│   │   ├── time_parser.py
│   │   ├── clean_data.py
│   │   └── anomaly_detector.py
│   │
│   ├── features/
│   │   ├── __init__.py
│   │   └── engineer_features.py
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── train_model.py
│   │   └── model_validator.py
│   │
│   ├── inference/
│   │   ├── __init__.py
│   │   └── predict_notional_times.py
│   │
│   ├── evaluation/
│   │   ├── __init__.py
│   │   └── evaluate_model.py
│   │
│   └── utils/
│       ├── __init__.py
│       ├── database.py
│       └── logger.py
│
├── tests/
│   ├── __init__.py
│   ├── test_time_parser.py
│   ├── test_features.py
│   └── test_model.py
│
├── notebooks/
│   ├── 01_data_exploration.ipynb
│   ├── 02_feature_analysis.ipynb
│   └── 03_model_evaluation.ipynb
│
├── models/
│   └── rally_eta_v1/     # Saved models
│
├── reports/
│   └── figures/
│
└── logs/
```

### 1.2 Initial Setup Commands
```bash
# Create project directory
mkdir rally-eta-prediction
cd rally-eta-prediction

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Create all directories
mkdir -p data/{raw,processed,external}
mkdir -p src/{scraper,preprocessing,features,models,inference,evaluation,utils}
mkdir -p tests notebooks models/rally_eta_v1 reports/figures logs
mkdir -p config

# Create __init__.py files
touch src/__init__.py
touch src/{scraper,preprocessing,features,models,inference,evaluation,utils}/__init__.py
touch tests/__init__.py
```

### 1.3 Requirements File

Create `requirements.txt`:
```txt
# Data processing
pandas==2.2.0
numpy==1.26.0
scipy==1.12.0
pyarrow==15.0.0

# Machine learning
lightgbm==4.3.0
scikit-learn==1.4.0
optuna==3.5.0

# Scraping
requests==2.31.0
beautifulsoup4==4.12.0
lxml==5.1.0

# Database
sqlalchemy==2.0.25

# Visualization
matplotlib==3.8.0
seaborn==0.13.0
plotly==5.18.0

# Explainability
shap==0.44.0

# Configuration
pyyaml==6.0.1

# Utils
python-dateutil==2.8.2
tqdm==4.66.1

# Testing
pytest==7.4.0
pytest-cov==4.1.0

# Logging
colorlog==6.8.0

# Jupyter
jupyter==1.0.0
ipykernel==6.29.0
```

Install:
```bash
pip install -r requirements.txt
```

### 1.4 Configuration File

Create `config/config.yaml`:
```yaml
# Rally ETA Prediction Configuration

project:
  name: "rally-eta-prediction"
  version: "1.0-mvp"

data:
  raw_db_path: "data/raw/rally_results.db"
  processed_path: "data/processed/"
  
scraping:
  tosfed_base_url: "https://sonuc.tosfed.org.tr"
  ewrc_base_url: "https://www.ewrc-results.com"
  start_year: 2023
  end_year: 2025
  rate_limit_seconds: 2
  
preprocessing:
  anomaly_detection:
    base_threshold_ratio: 1.3
    z_score_threshold: 2.5
    min_avg_speed_gravel: 40
    min_avg_speed_asphalt: 50
    max_avg_speed: 200

features:
  lookback_stages: 15
  min_history_for_stats: 3

model:
  type: "lightgbm"
  target: "ratio_to_class_best"
  
  hyperparameters:
    objective: "regression"
    metric: "mae"
    n_estimators: 500
    learning_rate: 0.03
    max_depth: 8
    num_leaves: 31
    min_child_samples: 20
    subsample: 0.8
    colsample_bytree: 0.8
    reg_alpha: 0.1
    reg_lambda: 0.1
    random_state: 42
    
  split:
    train_ratio: 0.70
    val_ratio: 0.15
    test_ratio: 0.15

inference:
  constraints:
    min_ratio: 1.0
    max_ratio: 1.35
    
logging:
  level: "INFO"
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  file: "logs/rally_eta.log"
```

Create `config/config_loader.py`:
```python
"""Configuration loader"""
import yaml
from pathlib import Path
from typing import Any

class Config:
    def __init__(self, config_path: str = "config/config.yaml"):
        self.config_path = Path(config_path)
        self._config = self._load_config()
    
    def _load_config(self):
        with open(self.config_path, 'r') as f:
            return yaml.safe_load(f)
    
    def get(self, key_path: str, default: Any = None):
        """Get config value using dot notation"""
        keys = key_path.split('.')
        value = self._config
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value

config = Config()
```

### 1.5 Logging Setup

Create `src/utils/logger.py`:
```python
"""Logging configuration"""
import logging
import sys
from pathlib import Path
from config.config_loader import config

def setup_logger(name: str) -> logging.Logger:
    """Setup logger with file and console handlers"""
    
    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(config.get('logging.level', 'INFO'))
    
    # Avoid duplicate handlers
    if logger.handlers:
        return logger
    
    # Create formatters
    formatter = logging.Formatter(
        config.get('logging.format'),
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File handler
    log_file = Path(config.get('logging.file', 'logs/rally_eta.log'))
    log_file.parent.mkdir(exist_ok=True)
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    return logger
```

---

## Phase 2: Data Collection (Days 2-3)

### 2.1 Time Parser

Create `src/preprocessing/time_parser.py`:
```python
"""Parse rally time strings to seconds"""
import re
from typing import Optional
import logging
logger = logging.getLogger(name)
class TimeParser:
"""Parse rally time strings to seconds"""
FORMATS = [
    r'^(\d{1,2}):(\d{2})\.(\d{1,3})$',           # MM:SS.mmm
    r'^(\d{1,2}):(\d{2}):(\d{2})\.(\d{1,3})$',  # HH:MM:SS.mmm
    r'^(\d{1,2}):(\d{2})$',                      # MM:SS
    r'^(\d{1,2}):(\d{2}):(\d{2})$',             # HH:MM:SS
]

INVALID_MARKERS = ['DNF', 'DNS', 'DSQ', '—', '', 'N/A', 'RET']

def parse(self, time_str: str) -> Optional[float]:
    """Parse time string to seconds"""
    if not time_str or not isinstance(time_str, str):
        return None
    
    time_str = time_str.strip().upper()
    
    if any(marker in time_str for marker in self.INVALID_MARKERS):
        return None
    
    for pattern in self.FORMATS:
        match = re.match(pattern, time_str)
        if match:
            return self._convert_to_seconds(match)
    
    logger.warning(f"Could not parse: '{time_str}'")
    return None

def _convert_to_seconds(self, match: re.Match) -> float:
    """Convert regex match to seconds"""
    groups = match.groups()
    
    if len(groups) == 3:  # MM:SS.mmm
        minutes, seconds, ms = groups
        return int(minutes) * 60 + int(seconds) + int(ms) / 1000
    
    elif len(groups) == 4:  # HH:MM:SS.mmm
        hours, minutes, seconds, ms = groups
        return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(ms) / 1000
    
    elif len(groups) == 2:  # MM:SS
        minutes, seconds = groups
        return int(minutes) * 60 + int(seconds)
    
    else:  # HH:MM:SS
        hours, minutes, seconds = groups
        return int(hours) * 3600 + int(minutes) * 60 + int(seconds)

def format_seconds(self, seconds: float) -> str:
    """Convert seconds back to MM:SS.SS format"""
    if seconds is None or seconds < 0:
        return "—"
    
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:05.2f}"
    return f"{minutes}:{secs:05.2f}"

### 2.2 Database Setup

Create `src/utils/database.py`:
```python
"""Database utilities"""
import sqlite3
import pandas as pd
from pathlib import Path
from typing import Optional
from config.config_loader import config

class Database:
    """SQLite database handler"""
    
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or config.get('data.raw_db_path')
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._create_tables()
    
    def get_connection(self):
        """Get database connection"""
        return sqlite3.connect(self.db_path)
    
    def _create_tables(self):
        """Create database schema"""
        conn = self.get_connection()
        
        conn.execute("""
        CREATE TABLE IF NOT EXISTS stage_results (
            result_id TEXT PRIMARY KEY,
            rally_id TEXT NOT NULL,
            rally_name TEXT,
            rally_year INTEGER,
            rally_date DATE,
            stage_id TEXT NOT NULL,
            stage_name TEXT,
            stage_number INTEGER,
            stage_number_in_day INTEGER,
            stage_length_km REAL,
            surface TEXT,
            day_or_night TEXT,
            driver_id TEXT NOT NULL,
            driver_name TEXT,
            car_model TEXT,
            car_class TEXT,
            drive_type TEXT,
            raw_time_str TEXT,
            time_seconds REAL,
            status TEXT,
            overall_position_before INTEGER,
            class_position_before INTEGER,
            gap_to_leader_seconds REAL,
            gap_to_class_leader_seconds REAL,
            cumulative_stage_km REAL,
            is_anomaly BOOLEAN,
            anomaly_reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(rally_id, stage_id, driver_id)
        )
        """)
        
        conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_driver_surface 
        ON stage_results(driver_id, surface, rally_date)
        """)
        
        conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_rally_stage 
        ON stage_results(rally_id, stage_number)
        """)
        
        conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_class_stage 
        ON stage_results(car_class, stage_id)
        """)
        
        conn.commit()
        conn.close()
    
    def save_dataframe(self, df: pd.DataFrame, table_name: str, 
                       if_exists: str = 'append'):
        """Save DataFrame to database"""
        conn = self.get_connection()
        df.to_sql(table_name, conn, if_exists=if_exists, index=False)
        conn.close()
    
    def load_dataframe(self, query: str) -> pd.DataFrame:
        """Load DataFrame from database"""
        conn = self.get_connection()
        df = pd.read_sql(query, conn)
        conn.close()
        return df
```

### 2.3 Web Scraper (Simplified for MVP)

**NOTE**: Since actual scraping requires site-specific HTML parsing which may change, we'll create a **manual data entry template** for MVP.

Create `src/scraper/manual_entry.py`:
```python
"""Manual data entry helper for MVP"""
import pandas as pd
from pathlib import Path

def create_data_template():
    """Create Excel template for manual data entry"""
    
    template = pd.DataFrame({
        'rally_name': ['Example Rally 2024'],
        'rally_date': ['2024-03-15'],
        'stage_name': ['SS1'],
        'stage_number': [1],
        'stage_length_km': [18.5],
        'surface': ['gravel'],  # or 'asphalt'
        'day_or_night': ['day'],  # or 'night'
        'driver_name': ['Pilot Name'],
        'car_model': ['Ford Fiesta Rally2'],
        'car_class': ['Rally2'],  # R2, Rally2, R5, N4, etc.
        'time_str': ['10:23.4'],  # MM:SS.S format
        'status': ['FINISHED'],  # or DNF, DNS, DSQ
        'overall_position': [5],
        'class_position': [2],
    })
    
    output_path = Path('data/external/data_entry_template.xlsx')
    output_path.parent.mkdir(parents=True, exist_ok=True)
    template.to_excel(output_path, index=False)
    
    print(f"Template created: {output_path}")
    print("\nFill this template with rally data and save as 'rally_data.xlsx'")

def import_manual_data(file_path: str):
    """Import manually entered data"""
    from src.utils.database import Database
    from src.preprocessing.time_parser import TimeParser
    
    df = pd.read_excel(file_path)
    
    # Parse times
    parser = TimeParser()
    df['time_seconds'] = df['time_str'].apply(parser.parse)
    
    # Generate IDs
    df['rally_id'] = df['rally_name'].str.lower().str.replace(' ', '_')
    df['stage_id'] = df['rally_id'] + '_' + df['stage_name'].str.lower()
    df['driver_id'] = df['driver_name'].str.lower().str.replace(' ', '_')
    df['result_id'] = df['stage_id'] + '_' + df['driver_id']
    
    # Save to database
    db = Database()
    db.save_dataframe(df, 'stage_results', if_exists='append')
    
    print(f"Imported {len(df)} results")

if __name__ == '__main__':
    # Create template
    create_data_template()
```

**For MVP, use this workflow:**
```bash
# 1. Create template
python -m src.scraper.manual_entry

# 2. Fill template with data from TOSFED/EWRC manually
# 3. Import data
python -c "from src.scraper.manual_entry import import_manual_data; import_manual_data('data/external/rally_data.xlsx')"
```

---

## Phase 3: Data Cleaning (Day 4)

### 3.1 Anomaly Detection

Create `src/preprocessing/anomaly_detector.py`:
```python
"""Detect anomalous stage times"""
import pandas as pd
import numpy as np
from scipy import stats
import logging
from config.config_loader import config

logger = logging.getLogger(__name__)

class AnomalyDetector:
    """Detect outlier times that should be excluded from training"""
    
    def __init__(self):
        self.base_threshold = config.get('preprocessing.anomaly_detection.base_threshold_ratio')
        self.z_threshold = config.get('preprocessing.anomaly_detection.z_score_threshold')
        self.min_speed_gravel = config.get('preprocessing.anomaly_detection.min_avg_speed_gravel')
        self.min_speed_asphalt = config.get('preprocessing.anomaly_detection.min_avg_speed_asphalt')
        self.max_speed = config.get('preprocessing.anomaly_detection.max_avg_speed')
    
    def detect(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Detect anomalies and add is_anomaly column
        
        CRITICAL: Must respect class boundaries
        """
        df = df.copy()
        df['is_anomaly'] = False
        df['anomaly_reason'] = None
        
        # Group by rally, stage, class
        def flag_group(group):
            if len(group) < 3:
                return group
            
            class_best = group['time_seconds'].min()
            stage_km = group['stage_length_km'].iloc[0]
            
            # Method 1: Ratio to best
            group['ratio_to_best'] = group['time_seconds'] / class_best
            threshold = self.base_threshold * (1 + stage_km / 50)
            
            outlier_ratio = group['ratio_to_best'] > threshold
            
            # Method 2: Z-score
            z_scores = np.abs(stats.zscore(group['time_seconds'], nan_policy='omit'))
            outlier_z = z_scores > self.z_threshold
            
            # Flag if either triggers
            group['is_anomaly'] = outlier_ratio | outlier_z
            group.loc[outlier_ratio, 'anomaly_reason'] = 'ratio_outlier'
            group.loc[outlier_z & ~outlier_ratio, 'anomaly_reason'] = 'z_score_outlier'
            
            return group
        
        df = df.groupby(['rally_id', 'stage_id', 'car_class'], group_keys=False).apply(flag_group)
        
        # Physical speed checks
        df['avg_speed_kmh'] = (df['stage_length_km'] / df['time_seconds']) * 3600
        
        speed_too_high = df['avg_speed_kmh'] > self.max_speed
        df.loc[speed_too_high, 'is_anomaly'] = True
        df.loc[speed_too_high, 'anomaly_reason'] = 'speed_too_high'
        
        # Speed too low (stuck/lost)
        df['min_speed'] = df['surface'].map({
            'gravel': self.min_speed_gravel,
            'asphalt': self.min_speed_asphalt
        }).fillna(self.min_speed_gravel)
        
        speed_too_low = df['avg_speed_kmh'] < df['min_speed']
        df.loc[speed_too_low, 'is_anomaly'] = True
        df.loc[speed_too_low, 'anomaly_reason'] = 'speed_too_low'
        
        logger.info(f"Detected {df['is_anomaly'].sum()} anomalies ({df['is_anomaly'].mean()*100:.1f}%)")
        
        return df.drop(columns=['ratio_to_best', 'min_speed'])
```

### 3.2 Data Cleaning Pipeline

Create `src/preprocessing/clean_data.py`:
```python
"""Clean and prepare raw data"""
import pandas as pd
import logging
from src.utils.database import Database
from src.preprocessing.time_parser import TimeParser
from src.preprocessing.anomaly_detector import AnomalyDetector
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

class DataCleaner:
    """Clean raw stage results"""
    
    def __init__(self):
        self.db = Database()
        self.time_parser = TimeParser()
        self.anomaly_detector = AnomalyDetector()
    
    def clean(self):
        """Full cleaning pipeline"""
        logger.info("Starting data cleaning...")
        
        # Load raw data
        df = self.db.load_dataframe("SELECT * FROM stage_results")
        logger.info(f"Loaded {len(df)} raw results")
        
        # Parse times if not already done
        if df['time_seconds'].isna().any():
            df['time_seconds'] = df['raw_time_str'].apply(self.time_parser.parse)
        
        # Remove invalid results
        df = self._remove_invalid(df)
        
        # Detect anomalies
        df = self.anomaly_detector.detect(df)
        
        # Save clean data
        clean_df = df[~df['is_anomaly']].copy()
        self.db.save_dataframe(clean_df, 'clean_stage_results', if_exists='replace')
        logger.info(f"Saved {len(clean_df)} clean results")
        
        # Save anomalies separately for analysis
        anomaly_df = df[df['is_anomaly']].copy()
        self.db.save_dataframe(anomaly_df, 'anomaly_stage_results', if_exists='replace')
        logger.info(f"Saved {len(anomaly_df)} anomalies")
        
        return clean_df
    
    def _remove_invalid(self, df: pd.DataFrame) -> pd.DataFrame:
        """Remove clearly invalid results"""
        initial_count = len(df)
        
        valid_mask = (
            (df['status'] == 'FINISHED') &
            (df['time_seconds'].notna()) &
            (df['time_seconds'] > 0) &
            (df['stage_length_km'].notna()) &
            (df['stage_length_km'] > 0)
        )
        
        df = df[valid_mask].copy()
        
        logger.info(f"Removed {initial_count - len(df)} invalid results")
        return df

if __name__ == '__main__':
    cleaner = DataCleaner()
    clean_df = cleaner.clean()
```

---

## Phase 4: Feature Engineering (Days 5-6)

### 4.1 Target Variable Calculation

Create `src/features/engineer_features.py`:
```python
"""Feature engineering with temporal safety"""
import pandas as pd
import numpy as np
import logging
from typing import Dict
from config.config_loader import config
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

class FeatureEngineer:
    """Engineer features with strict temporal constraints"""
    
    def __init__(self):
        self.lookback_stages = config.get('features.lookback_stages')
        self.min_history = config.get('features.min_history_for_stats')
    
    def engineer_all(self, df: pd.DataFrame) -> pd.DataFrame:
        """Full feature engineering pipeline"""
        logger.info("Starting feature engineering...")
        
        # Sort by date and stage
        df = df.sort_values(['rally_date', 'rally_id', 'stage_number'])
        
        # Calculate target
        df = self._calculate_target(df)
        
        # Add features
        df = self._add_stage_features(df)
        df = self._add_vehicle_features(df)
        df = self._add_driver_features_temporal(df)
        df = self._add_rally_context(df)
        df = self._add_competition_features(df)
        
        # Impute missing
        df = self._impute_missing(df)
        
        logger.info(f"Feature engineering complete: {len(df.columns)} columns")
        return df
    
    def _calculate_target(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate ratio_to_class_best"""
        logger.info("Calculating target variable...")
        
        def compute_class_best(group):
            valid = group[~group.get('is_anomaly', False)]
            if len(valid) == 0:
                group['class_best_time'] = np.nan
                group['ratio_to_class_best'] = np.nan
            else:
                class_best = valid['time_seconds'].min()
                group['class_best_time'] = class_best
                group['ratio_to_class_best'] = group['time_seconds'] / class_best
            return group
        
        df = df.groupby(['rally_id', 'stage_id', 'car_class'], group_keys=False).apply(compute_class_best)
        
        # Remove rows where target can't be calculated
        df = df[df['ratio_to_class_best'].notna()].copy()
        
        logger.info(f"Target calculated for {len(df)} results")
        return df
    
    def _add_stage_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add stage characteristics"""
        df['surface_asphalt'] = (df['surface'] == 'asphalt').astype(int)
        df['surface_gravel'] = (df['surface'] == 'gravel').astype(int)
        df['is_night'] = (df['day_or_night'] == 'night').astype(int)
        
        # Stage length bins
        df['stage_length_bin'] = pd.cut(
            df['stage_length_km'],
            bins=[0, 10, 20, 30, 100],
            labels=['short', 'medium', 'long', 'very_long']
        )
        df = pd.get_dummies(df, columns=['stage_length_bin'], prefix='length', dtype=int)
        
        return df
    
    def _add_vehicle_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add vehicle/class features"""
        # Class encoding
        class_order = {
            'R2': 1, 'Rally3': 2, 'Rally2': 3, 'R5': 4,
            'N4': 5, 'Rally1': 6, 'WRC': 7
        }
        df['class_ordinal'] = df['car_class'].map(class_order).fillna(0)
        
        # One-hot encode class
        df = pd.get_dummies(df, columns=['car_class'], prefix='class', dtype=int)
        
        return df
    
    def _add_driver_features_temporal(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        CRITICAL: Add driver features with strict temporal ordering
        """
        logger.info("Adding driver features (temporal-safe)...")
        
        # Initialize columns
        driver_cols = [
            'driver_mean_ratio_surface',
            'driver_std_ratio_surface',
            'driver_mean_ratio_overall',
            'driver_best_ratio_season',
            'driver_stages_completed',
            'driver_last3_ratio_same_rally',
            'driver_avg_ratio_this_rally',
            'is_rookie'
        ]
        
        for col in driver_cols:
            df[col] = np.nan
        
        df['is_rookie'] = False
        df['driver_stages_completed'] = 0
        
        # Process each driver
        for driver_id in df['driver_id'].unique():
            driver_mask = df['driver_id'] == driver_id
            driver_df = df[driver_mask].sort_values(['rally_date', 'stage_number'])
            
            for idx in driver_df.index:
                current_row = df.loc[idx]
                current_date = current_row['rally_date']
                current_rally = current_row['rally_id']
                current_stage = current_row['stage_number']
                current_surface = current_row['surface']
                
                # Get historical data (before this stage)
                historical = driver_df[
                    ((driver_df['rally_date'] < current_date) |
                     ((driver_df['rally_id'] == current_rally) &
                      (driver_df['stage_number'] < current_stage)))
                ].copy()
                
                if len(historical) == 0:
                    df.loc[idx, 'is_rookie'] = True
                    continue
                
                # Overall stats
                recent = historical.tail(self.lookback_stages)
                df.loc[idx, 'driver_mean_ratio_overall'] = recent['ratio_to_class_best'].mean()
                df.loc[idx, 'driver_std_ratio_surface'] = recent['ratio_to_class_best'].std()
                df.loc[idx, 'driver_stages_completed'] = len(historical)
                df.loc[idx, 'driver_best_ratio_season'] = historical['ratio_to_class_best'].min()
                
                # Surface-specific
                surface_history = historical[historical['surface'] == current_surface].tail(self.lookback_stages)
                if len(surface_history) > 0:
                    df.loc[idx, 'driver_mean_ratio_surface'] = surface_history['ratio_to_class_best'].mean()
                else:
                    df.loc[idx, 'driver_mean_ratio_surface'] = df.loc[idx, 'driver_mean_ratio_overall']
                
                # Same rally stats
                same_rally = historical[historical['rally_id'] == current_rally]
                if len(same_rally) > 0:
                    df.loc[idx, 'driver_avg_ratio_this_rally'] = same_rally['ratio_to_class_best'].mean()
                    df.loc[idx, 'driver_last3_ratio_same_rally'] = same_rally.tail(3)['ratio_to_class_best'].mean()
        
        logger.info("Driver features complete")
        return df
    
    def _add_rally_context(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add rally context features"""
        df['cumulative_stage_km_normalized'] = df.get('cumulative_stage_km', 0) / 100
        
        df['stage_progress'] = df.groupby('rally_id')['stage_number'].transform(
            lambda x: (x - x.min()) / (x.max() - x.min() + 1e-6)
        )
        
        df['is_first_stage_of_day'] = (df.get('stage_number_in_day', 1) == 1).astype(int)
        
        return df
    
    def _add_competition_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add competition pressure features"""
        df['gap_to_leader_per_km'] = df.get('gap_to_leader_seconds', 0) / df['stage_length_km']
        df['gap_to_class_leader_per_km'] = df.get('gap_to_class_leader_seconds', 0) / df['stage_length_km']
        
        df['is_leading_overall'] = (df.get('overall_position_before', 999) == 1).astype(int)
        df['is_leading_class'] = (df.get('class_position_before', 999) == 1).astype(int)
        df['is_top3_class'] = (df.get('class_position_before', 999) <= 3).astype(int)
        
        return df
    
    def _impute_missing(self, df: pd.DataFrame) -> pd.DataFrame:
        """Impute missing values"""
        logger.info("Imputing missing values...")
        
        # For rookies, use class median
        rookie_mask = df['is_rookie']
        
        for col in ['driver_mean_ratio_surface', 'driver_mean_ratio_overall']:
            if col in df.columns:
                class_medians = df.groupby(['car_class', 'surface'])[col].transform('median')
                df.loc[rookie_mask, col] = df.loc[rookie_mask, col].fillna(class_medians)
        
        # Fill remaining NaNs
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        for col in numeric_cols:
            if df[col].isna().any():
                df[col].fillna(df[col].median(), inplace=True)
        
        return df

if __name__ == '__main__':
    from src.utils.database import Database
    
    db = Database()
    df = db.load_dataframe("SELECT * FROM clean_stage_results")
    
    engineer = FeatureEngineer()
    features_df = engineer.engineer_all(df)
    
    # Save
    features_df.to_parquet('data/processed/features.parquet')
    logger.info(f"Saved {len(features_df)} rows with {len(features_df.columns)} features")
```

---

## Phase 5: Model Training (Days 7-8)

---

## Phase 5: Model Training (Days 7-8)

### 5.1 Model Training Pipeline

Create `src/models/train_model.py`:
```python
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
        """
        logger.info("Preparing train/val/test split...")
        
        df = df.sort_values('rally_date')
        rallies = df['rally_id'].unique()
        
        train_ratio = self.config['split']['train_ratio']
        val_ratio = self.config['split']['val_ratio']
        
        n_rallies = len(rallies)
        train_end = int(n_rallies * train_ratio)
        val_end = int(n_rallies * (train_ratio + val_ratio))
        
        train_rallies = rallies[:train_end]
        val_rallies = rallies[train_end:val_end]
        test_rallies = rallies[val_end:]
        
        train_df = df[df['rally_id'].isin(train_rallies)]
        val_df = df[df['rally_id'].isin(val_rallies)]
        test_df = df[df['rally_id'].isin(test_rallies)]
        
        logger.info(f"Train: {len(train_rallies)} rallies, {len(train_df)} stages")
        logger.info(f"Val: {len(val_rallies)} rallies, {len(val_df)} stages")
        logger.info(f"Test: {len(test_rallies)} rallies, {len(test_df)} stages")
        
        return train_df, val_df, test_df
    
    def get_feature_columns(self, df: pd.DataFrame):
        """Select feature columns (exclude IDs, target, etc.)"""
        exclude = [
            'result_id', 'rally_id', 'rally_name', 'stage_id', 'stage_name',
            'driver_id', 'driver_name', 'car_model', 'raw_time_str',
            'time_seconds', 'status', 'ratio_to_class_best', 'class_best_time',
            'is_anomaly', 'anomaly_reason', 'created_at', 'rally_date',
            'rally_year', 'avg_speed_kmh'
        ]
        
        feature_cols = [col for col in df.columns if col not in exclude]
        numeric_features = df[feature_cols].select_dtypes(include=[np.number]).columns.tolist()
        
        return numeric_features
    
    def train(self, train_df: pd.DataFrame, val_df: pd.DataFrame):
        """Train LightGBM model"""
        logger.info("Starting model training...")
        
        feature_cols = self.get_feature_columns(train_df)
        self.feature_names = feature_cols
        
        X_train = train_df[feature_cols].fillna(0)
        y_train = train_df['ratio_to_class_best']
        
        X_val = val_df[feature_cols].fillna(0)
        y_val = val_df['ratio_to_class_best']
        
        logger.info(f"Training with {len(feature_cols)} features on {len(X_train)} samples")
        
        # LightGBM parameters
        params = self.config['hyperparameters'].copy()
        
        self.model = lgb.LGBMRegressor(**params)
        
        # Train with early stopping
        self.model.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)],
            eval_metric='mae',
            callbacks=[
                lgb.early_stopping(stopping_rounds=50, verbose=True),
                lgb.log_evaluation(period=50)
            ]
        )
        
        # Feature importance
        self.feature_importance = pd.DataFrame({
            'feature': feature_cols,
            'importance': self.model.feature_importances_
        }).sort_values('importance', ascending=False)
        
        logger.info("\nTop 10 Features:")
        print(self.feature_importance.head(10).to_string(index=False))
    
    def predict(self, df: pd.DataFrame) -> np.ndarray:
        """Predict ratio_to_class_best"""
        X = df[self.feature_names].fillna(0)
        predictions = self.model.predict(X)
        
        # Post-processing: ratio >= 1.0
        predictions = np.maximum(predictions, 1.0)
        
        return predictions
    
    def evaluate(self, df: pd.DataFrame, split_name: str = "Test"):
        """Comprehensive evaluation"""
        logger.info(f"\n{'='*60}")
        logger.info(f"{split_name} Set Evaluation")
        logger.info(f"{'='*60}")
        
        y_true = df['ratio_to_class_best'].values
        y_pred = self.predict(df)
        
        # Convert to times
        actual_times = df['time_seconds'].values
        predicted_times = y_pred * df['class_best_time'].values
        
        # Overall metrics
        mae_ratio = mean_absolute_error(y_true, y_pred)
        mae_seconds = mean_absolute_error(actual_times, predicted_times)
        mape = mean_absolute_percentage_error(actual_times, predicted_times) * 100
        
        logger.info(f"MAE (ratio): {mae_ratio:.4f}")
        logger.info(f"MAE (seconds): {mae_seconds:.1f}s")
        logger.info(f"MAPE: {mape:.2f}%")
        
        # Per-class metrics
        logger.info("\nPer-Class MAPE:")
        class_metrics = []
        for car_class_col in [col for col in df.columns if col.startswith('class_')]:
            if df[car_class_col].sum() < 5:
                continue
            
            mask = df[car_class_col] == 1
            class_name = car_class_col.replace('class_', '')
            class_mape = mean_absolute_percentage_error(
                actual_times[mask],
                predicted_times[mask]
            ) * 100
            
            class_metrics.append({
                'class': class_name,
                'n_samples': mask.sum(),
                'mape': class_mape
            })
        
        class_df = pd.DataFrame(class_metrics).sort_values('mape')
        print(class_df.to_string(index=False))
        
        # Ranking correlation
        self._evaluate_ranking(df, y_pred)
        
        return {
            'mae_ratio': mae_ratio,
            'mae_seconds': mae_seconds,
            'mape': mape,
            'class_metrics': class_metrics
        }
    
    def _evaluate_ranking(self, df: pd.DataFrame, y_pred: np.ndarray):
        """Evaluate ranking preservation"""
        correlations = []
        
        # Group by rally, stage, class
        for (rally, stage), group in df.groupby(['rally_id', 'stage_id']):
            if len(group) < 3:
                continue
            
            true_ranks = group['ratio_to_class_best'].rank()
            pred_ranks = pd.Series(y_pred[group.index], index=group.index).rank()
            
            corr, _ = spearmanr(true_ranks, pred_ranks)
            correlations.append(corr)
        
        avg_corr = np.mean(correlations)
        perfect_pct = (np.array(correlations) > 0.9).mean() * 100
        
        logger.info(f"\nRanking Metrics:")
        logger.info(f"Average Spearman Correlation: {avg_corr:.3f}")
        logger.info(f"Perfect Rankings (r > 0.9): {perfect_pct:.1f}%")
    
    def save(self, output_dir: str = "models/rally_eta_v1"):
        """Save model and metadata"""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Save model
        joblib.dump(self.model, output_path / "model.pkl")
        
        # Save metadata
        metadata = {
            'feature_names': self.feature_names,
            'feature_importance': self.feature_importance.to_dict('records'),
            'config': self.config
        }
        
        with open(output_path / "metadata.json", 'w') as f:
            json.dump(metadata, f, indent=2)
        
        # Save feature importance plot
        import matplotlib.pyplot as plt
        
        plt.figure(figsize=(10, 8))
        top_features = self.feature_importance.head(20)
        plt.barh(top_features['feature'], top_features['importance'])
        plt.xlabel('Importance')
        plt.title('Top 20 Feature Importance')
        plt.gca().invert_yaxis()
        plt.tight_layout()
        plt.savefig(output_path / "feature_importance.png", dpi=300)
        plt.close()
        
        logger.info(f"Model saved to {output_path}")
    
    @classmethod
    def load(cls, model_dir: str = "models/rally_eta_v1"):
        """Load trained model"""
        model_path = Path(model_dir)
        
        with open(model_path / "metadata.json", 'r') as f:
            metadata = json.load(f)
        
        instance = cls()
        instance.model = joblib.load(model_path / "model.pkl")
        instance.feature_names = metadata['feature_names']
        instance.feature_importance = pd.DataFrame(metadata['feature_importance'])
        
        return instance

def main():
    """Main training pipeline"""
    # Load features
    logger.info("Loading feature data...")
    df = pd.read_parquet('data/processed/features.parquet')
    
    # Initialize model
    model = RallyETAModel()
    
    # Split data
    train_df, val_df, test_df = model.prepare_data_split(df)
    
    # Train
    model.train(train_df, val_df)
    
    # Evaluate
    val_metrics = model.evaluate(val_df, "Validation")
    test_metrics = model.evaluate(test_df, "Test")
    
    # Save
    model.save()
    
    # Save metrics
    metrics_output = {
        'validation': val_metrics,
        'test': test_metrics
    }
    
    with open('models/rally_eta_v1/evaluation_metrics.json', 'w') as f:
        json.dump(metrics_output, f, indent=2)
    
    logger.info("\nTraining complete!")
    
    # Check success criteria
    if test_metrics['mape'] < 2.5:
        logger.info("✅ SUCCESS: MAPE < 2.5% target achieved!")
    else:
        logger.warning(f"⚠️  MAPE {test_metrics['mape']:.2f}% exceeds 2.5% target")

if __name__ == '__main__':
    main()
```

---

## Phase 6: Inference Pipeline (Days 9-10)

### 6.1 Notional Time Prediction

Create `src/inference/predict_notional_times.py`:
```python
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
        self.model = RallyETAModel.load(model_path)
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
        for col in stage_results.columns:
            if col.startswith('class_') and stage_results[col].sum() > 0:
                class_name = col.replace('class_', '')
                class_mask = stage_results[col] == 1
                class_times = stage_results[class_mask]['time_seconds']
                
                if len(class_times) > 0:
                    ref_times[class_name] = {
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
        driver_class = None
        for col in driver_data.columns:
            if col.startswith('class_') and driver_data[col].iloc[-1] == 1:
                driver_class = col.replace('class_', '')
                break
        
        if not driver_class:
            raise ValueError(f"Could not determine class for driver {driver_id}")
        
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
        
        # Predict ratio
        predicted_ratio = self.model.predict(feature_df)[0]
        
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
            'rally_date': stage_info['rally_date'],
            'stage_id': stage_info['stage_id'],
            'stage_name': stage_info['stage_name'],
            'stage_number': stage_info['stage_number'],
            'stage_length_km': stage_info['stage_length_km'],
            'surface': stage_info['surface'],
            'day_or_night': stage_info['day_or_night'],
        }
        
        # Add car info from last stage
        last_result = driver_data.iloc[-1]
        for col in last_result.index:
            if col.startswith('class_') or col in ['car_model']:
                row[col] = last_result[col]
        
        # Add competition context
        row['overall_position_before'] = last_result.get('overall_position_before', 999)
        row['class_position_before'] = last_result.get('class_position_before', 999)
        row['gap_to_leader_seconds'] = last_result.get('gap_to_leader_seconds', 0)
        row['cumulative_stage_km'] = last_result.get('cumulative_stage_km', 0)
        
        # Add dummy target (will be ignored in prediction)
        row['ratio_to_class_best'] = 1.0
        row['time_seconds'] = 600.0  # Dummy
        row['class_best_time'] = 600.0  # Dummy
        row['is_anomaly'] = False
        
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
        
        # Query historical average for this class on similar stages
        query = f"""
        SELECT AVG(class_best_time) as avg_time
        FROM clean_stage_results
        WHERE car_class = '{car_class}'
        AND surface = '{stage_info['surface']}'
        AND stage_length_km BETWEEN {stage_info['stage_length_km'] * 0.8} 
                                AND {stage_info['stage_length_km'] * 1.2}
        """
        
        result = self.db.load_dataframe(query)
        
        if len(result) > 0 and not pd.isna(result['avg_time'].iloc[0]):
            return result['avg_time'].iloc[0]
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
    
    # Example: SS8 was red-flagged in Rally X
    rally_id = "example_rally_2024"
    stage_id = "example_rally_2024_ss8"
    affected_drivers = ["driver_1", "driver_2", "driver_3"]
    
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
```

---

## Phase 7: Testing (Day 11)

### 7.1 Unit Tests

Create `tests/test_time_parser.py`:
```python
"""Tests for time parser"""
import pytest
from src.preprocessing.time_parser import TimeParser

def test_parse_mm_ss_mmm():
    parser = TimeParser()
    assert parser.parse("5:23.4") == 323.4
    assert parser.parse("12:34.567") == 754.567

def test_parse_hh_mm_ss_mmm():
    parser = TimeParser()
    assert parser.parse("1:05:23.456") == 3923.456

def test_parse_mm_ss():
    parser = TimeParser()
    assert parser.parse("5:23") == 323.0

def test_parse_invalid():
    parser = TimeParser()
    assert parser.parse("DNF") is None
    assert parser.parse("") is None
    assert parser.parse(None) is None

def test_format_seconds():
    parser = TimeParser()
    assert parser.format_seconds(323.4) == "5:23.40"
    assert parser.format_seconds(3923.456) == "1:05:23.46"
```

Create `tests/test_features.py`:
```python
"""Tests for feature engineering"""
import pytest
import pandas as pd
import numpy as np
from src.features.engineer_features import FeatureEngineer

def test_no_data_leakage():
    """CRITICAL: Ensure no future data is used"""
    df = pd.DataFrame({
        'rally_id': ['R1'] * 6,
        'stage_number': [1, 2, 3, 4, 5, 6],
        'rally_date': pd.to_datetime(['2024-01-01'] * 6),
        'driver_id': ['D1'] * 6,
        'time_seconds': [100, 102, 98, 105, 101, 99],
        'ratio_to_class_best': [1.0, 1.02, 0.98, 1.05, 1.01, 0.99],
        'surface': ['gravel'] * 6,
        'car_class': ['R5'] * 6,
        'is_anomaly': [False] * 6,
        'stage_length_km': [20] * 6,
        'day_or_night': ['day'] * 6,
    })
    
    engineer = FeatureEngineer()
    result = engineer.engineer_all(df)
    
    # For stage 3, mean should only use stages 1-2
    stage3_idx = result[result['stage_number'] == 3].index[0]
    stage3_mean = result.loc[stage3_idx, 'driver_mean_ratio_overall']
    expected_mean = (1.0 + 1.02) / 2
    
    assert abs(stage3_mean - expected_mean) < 0.01, \
        f"Data leakage! Expected {expected_mean}, got {stage3_mean}"

def test_rookie_handling():
    """Test rookie driver imputation"""
    df = pd.DataFrame({
        'rally_id': ['R1'],
        'stage_number': [1],
        'rally_date': pd.to_datetime(['2024-01-01']),
        'driver_id': ['NEW'],
        'time_seconds': [100],
        'ratio_to_class_best': [1.05],
        'surface': ['gravel'],
        'car_class': ['R5'],
        'is_anomaly': [False],
        'stage_length_km': [20],
        'day_or_night': ['day'],
    })
    
    engineer = FeatureEngineer()
    result = engineer.engineer_all(df)
    
    assert result.loc[0, 'is_rookie'] == True
    assert pd.notna(result.loc[0, 'driver_mean_ratio_surface'])

def test_target_calculation():
    """Test ratio_to_class_best calculation"""
    df = pd.DataFrame({
    'rally_id': ['R1', 'R1'],
    'stage_id': ['SS1', 'SS1'],
    'stage_number': [1, 1],
    'rally_date': pd.to_datetime(['2024-01-01', '2024-01-01']),
    'driver_id': ['D1', 'D2'],
    'time_seconds': [100, 110],
    'car_class': ['R5', 'R5'],
    'is_anomaly': [False, False],
    'surface': ['gravel', 'gravel'],
    'stage_length_km': [20, 20],
    'day_or_night': ['day', 'day'],
})

engineer = FeatureEngineer()
result = engineer._calculate_target(df)

assert result.loc[0, 'class_best_time'] == 100
assert result.loc[0, 'ratio_to_class_best'] == 1.0
assert result.loc[1, 'ratio_to_class_best'] == 1.1
Run tests:
````bash
pytest tests/ -v --cov=src
````

---

## Phase 8: Documentation & Deployment (Day 12)

### 8.1 README.md

Create comprehensive `README.md`:
````markdown
# Rally Stage ETA Prediction System

Machine learning system to predict notional times for rally drivers affected by red-flagged stages.

## Quick Start

### Installation
```bash
# Clone repository
git clone <repository-url>
cd rally-eta-prediction

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Data Preparation

1. Create data entry template:
```bash
python -m src.scraper.manual_entry
```

2. Fill `data/external/data_entry_template.xlsx` with rally data

3. Import data:
```bash
python -c "from src.scraper.manual_entry import import_manual_data; import_manual_data('data/external/rally_data.xlsx')"
```

### Training Pipeline
```bash
# 1. Clean data
python -m src.preprocessing.clean_data

# 2. Engineer features
python -c "
from src.utils.database import Database
from src.features.engineer_features import FeatureEngineer
db = Database()
df = db.load_dataframe('SELECT * FROM clean_stage_results')
engineer = FeatureEngineer()
features = engineer.engineer_all(df)
features.to_parquet('data/processed/features.parquet')
"

# 3. Train model
python -m src.models.train_model
```

### Making Predictions
```python
from src.inference.predict_notional_times import NotionalTimePredictor

predictor = NotionalTimePredictor()

predictions = predictor.predict_for_red_flag(
    rally_id="example_rally_2024",
    stage_id="example_rally_2024_ss8",
    affected_driver_ids=["driver_1", "driver_2"]
)

print(predictions[['driver_name', 'notional_time_str', 'confidence']])
```

## Project Structure
````
rally-eta-prediction/
├── src/                      # Source code
│   ├── scraper/             # Data collection
│   ├── preprocessing/       # Data cleaning
│   ├── features/            # Feature engineering
│   ├── models/              # Model training
│   ├── inference/           # Prediction pipeline
│   └── utils/               # Utilities
├── tests/                    # Unit tests
├── data/                     # Data storage
├── models/                   # Saved models
├── config/                   # Configuration
└── reports/                  # Output reports
Model Performance
Target: MAPE < 2.5%
See models/rally_eta_v1/evaluation_metrics.json for detailed metrics.
Configuration
Edit config/config.yaml to customize:

Data paths
Model hyperparameters
Inference constraints
Logging settings

Testing
bashpytest tests/ -v --cov=src
````

## License

[Your License]
````

### 8.2 Usage Guide for Race Officials

Create `docs/OFFICIAL_GUIDE.md`:
````markdown
# Rally ETA System - Official Guide

## Purpose

This system predicts what time a driver **would have achieved** if a red-flagged stage had run normally.

## How It Works

### 1. Historical Data
- System learns from 2023-2025 Turkish rally results
- Understands each driver's typical performance
- Accounts for stage characteristics (length, surface, etc.)

### 2. Prediction Process

When a stage is red-flagged:

1. **Reference Time**: Find best time in each class from unaffected drivers
2. **Driver Analysis**: Calculate affected driver's typical gap to class leader
3. **Prediction**: Apply driver's typical performance to reference time
4. **Constraints**: Ensure prediction is fair and physically realistic

### 3. Confidence Levels

- **High**: 3+ drivers finished normally in class
- **Medium**: 1-2 drivers finished normally
- **Low**: No class reference, using historical estimate

## Reading Predictions

### Example Output
````
Driver: Mehmet Yılmaz
Class: Rally2
Reference Time: 10:30.00
Predicted Ratio: 1.075
Notional Time: 11:17.75
Confidence: High

Explanation:
Driver's average on gravel surfaces is 7.2% slower than class leader.
In this rally, their average gap is 6.8%.
Predicted ratio: 1.075, reference time: 10:30.00.
````

### Interpretation

- **Predicted Ratio**: How much slower than class best (1.075 = 7.5% slower)
- **Notional Time**: Final predicted time
- **Confidence**: Reliability of prediction

## When to Review Manually

System flags for review when:
- Confidence is LOW
- Driver is rookie (no history)
- Prediction seems unusual compared to rally performance

## Limitations

- Cannot predict crashes that would have happened anyway
- Less accurate for rookies
- Requires at least one class finisher for reference

## Questions?

Contact: [Technical Support]
````

---

## Claude Code Usage Guide

### Step-by-Step Instructions for Implementation

#### 1. Initial Setup (Use Claude Code Terminal)
````bash
# In Claude Code terminal:
mkdir rally-eta-prediction
cd rally-eta-prediction

# Create virtual environment
python -m venv venv

# Activate (on macOS/Linux)
source venv/bin/activate

# Or on Windows
# venv\Scripts\activate
````

#### 2. Create File Structure

Tell Claude Code:
````
"Create the complete directory structure as specified in the plan:
- src/ with all subdirectories (scraper, preprocessing, features, models, inference, evaluation, utils)
- tests/
- data/ with subdirectories (raw, processed, external)
- config/
- models/rally_eta_v1/
- reports/figures/
- logs/
- notebooks/

Also create all __init__.py files in the appropriate directories."
````

#### 3. Create Configuration Files

Tell Claude Code:
````
"Create config/config.yaml with all the configuration parameters from the plan.
Then create config/config_loader.py with the Config class."
````

#### 4. Implement Core Modules (One at a Time)

**Order of implementation:**

1. **Utils first:**
````
"Create src/utils/logger.py with the setup_logger function.
Then create src/utils/database.py with the Database class."
````

2. **Time parser:**
````
"Create src/preprocessing/time_parser.py with the TimeParser class including all parsing formats."
````

3. **Data entry (for MVP):**
````
"Create src/scraper/manual_entry.py with functions to create template and import data."
````

4. **Anomaly detection:**
````
"Create src/preprocessing/anomaly_detector.py with the AnomalyDetector class."
````

5. **Data cleaning:**
````
"Create src/preprocessing/clean_data.py with the DataCleaner class."
````

6. **Feature engineering:**
````
"Create src/features/engineer_features.py with the FeatureEngineer class.
Make sure temporal constraints are properly implemented."
````

7. **Model training:**
````
"Create src/models/train_model.py with the RallyETAModel class."
````

8. **Inference pipeline:**
````
"Create src/inference/predict_notional_times.py with the NotionalTimePredictor class."
````

#### 5. Create Tests
````
"Create tests/test_time_parser.py with all test functions.
Then create tests/test_features.py with temporal leakage tests."
````

#### 6. Install Dependencies
````bash
pip install -r requirements.txt
````

#### 7. Running the System

**Step 1: Prepare Data**
````bash
# Create template
python -m src.scraper.manual_entry

# Fill the Excel file manually with rally data
# Then import:
python -c "from src.scraper.manual_entry import import_manual_data; import_manual_data('data/external/rally_data.xlsx')"
````

**Step 2: Clean Data**
````bash
python -m src.preprocessing.clean_data
````

**Step 3: Engineer Features**
````bash
python -c "
from src.utils.database import Database
from src.features.engineer_features import FeatureEngineer
db = Database()
df = db.load_dataframe('SELECT * FROM clean_stage_results')
engineer = FeatureEngineer()
features = engineer.engineer_all(df)
features.to_parquet('data/processed/features.parquet')
print('Features saved!')
"
````

**Step 4: Train Model**
````bash
python -m src.models.train_model
````

**Step 5: Make Predictions**
````bash
python -m src.inference.predict_notional_times
````

#### 8. Testing
````bash
# Run all tests
pytest tests/ -v

# With coverage
pytest tests/ -v --cov=src --cov-report=html
````

### Tips for Claude Code

1. **One module at a time**: Don't ask Claude to create everything at once
2. **Test as you go**: After each module, test it before moving on
3. **Use specific requests**: "Create X file with Y functionality" works better than "create the whole system"
4. **Review generated code**: Check that temporal constraints and data handling are correct
5. **Ask for fixes**: If something doesn't work, show Claude the error and ask for a fix

### Common Claude Code Commands
````
# Create a file
"Create src/utils/database.py with a Database class that handles SQLite connections"

# Modify a file
"In src/models/train_model.py, add error handling to the train() method"

# Debug
"I'm getting this error: [paste error]. Can you fix it?"

# Explain
"Explain how the temporal ordering works in engineer_features.py"

# Test
"Create unit tests for the TimeParser class"
````

---

## Success Checklist

MVP is complete when:

- [ ] Data can be imported from Excel template
- [ ] Anomaly detection removes outliers correctly
- [ ] Features are engineered with no temporal leakage
- [ ] Model trains successfully
- [ ] Test set MAPE < 2.5%
- [ ] Predictions can be generated for red flag scenarios
- [ ] All tests pass
- [ ] Documentation is complete
- [ ] Example predictions run successfully

---

## Next Steps After MVP

1. **Automated scraping** from TOSFED/EWRC
2. **KMZ analysis** for stage characteristics
3. **Weather data** integration
4. **Web interface** (Streamlit/Flask)
5. **Real-time integration** with timing systems

---

## Support

For issues or questions:
1. Check logs in `logs/rally_eta.log`
2. Run tests to identify problems
3. Review configuration in `config/config.yaml`
4. Check model evaluation metrics

---

**End of Implementation Plan**

Bu plan Claude Code ile adım adım uygulanabilir. Her adımı sırayla tamamla ve test et!