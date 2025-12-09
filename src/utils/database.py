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

        if if_exists == 'append' and table_name == 'stage_results':
            # Tekrar eden kayıtları ignore et (UNIQUE constraint için)
            # INSERT OR IGNORE kullan
            cursor = conn.cursor()

            for _, row in df.iterrows():
                try:
                    placeholders = ','.join(['?' for _ in row])
                    columns = ','.join(row.index)
                    sql = f"INSERT OR IGNORE INTO {table_name} ({columns}) VALUES ({placeholders})"
                    cursor.execute(sql, tuple(row.values))
                except Exception as e:
                    # Hata logla ama devam et
                    pass

            conn.commit()
        else:
            df.to_sql(table_name, conn, if_exists=if_exists, index=False)

        conn.close()

    def load_dataframe(self, query: str) -> pd.DataFrame:
        """Load DataFrame from database"""
        conn = self.get_connection()
        df = pd.read_sql(query, conn)
        conn.close()
        return df
