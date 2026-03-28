"""
Rally ETA v2.0 - Veri Yükleme Fonksiyonları
Pilot, ralli, KML ve metadata yükleme işlemleri.
"""

import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
import sqlite3

from .config import get_db_path, get_kml_folder, FINISHED_STATUSES


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        [table_name],
    ).fetchone()
    return row is not None


def get_driver_list(db_path: Optional[str] = None) -> List[Dict]:
    """Veritabanından pilot listesini yükle."""
    path = db_path or get_db_path()

    if not Path(path).exists():
        return []

    try:
        conn = sqlite3.connect(path)
        if _table_exists(conn, 'drivers'):
            query = """
                SELECT
                    d.display_name as driver_name,
                    d.driver_id,
                    MAX(sr.car_class) as car_class,
                    COALESCE(MAX(sr.normalized_class), MAX(sr.car_class)) as normalized_class
                FROM drivers d
                LEFT JOIN stage_results sr
                    ON sr.driver_id = d.driver_id
                    AND sr.time_seconds > 0
                GROUP BY d.driver_id, d.display_name
                HAVING COUNT(sr.result_id) > 0
                ORDER BY d.display_name
            """
        else:
            query = """
                SELECT DISTINCT
                    driver_name,
                    driver_name as driver_id,
                    car_class,
                    COALESCE(normalized_class, car_class) as normalized_class
                FROM stage_results
                WHERE time_seconds > 0
                ORDER BY driver_name
            """

        df = pd.read_sql_query(query, conn)
        conn.close()

        # Duplicate driver_name'leri kaldır
        df = df.drop_duplicates(subset=['driver_name'], keep='first')

        return df.to_dict('records')
    except Exception as e:
        return []


def get_rally_list(db_path: Optional[str] = None, limit: Optional[int] = None) -> List[Dict]:
    """Veritabanından ralli listesini yükle."""
    path = db_path or get_db_path()

    if not Path(path).exists():
        return []

    try:
        conn = sqlite3.connect(path)
        if _table_exists(conn, 'rallies') and _table_exists(conn, 'stages'):
            query = """
                SELECT
                    r.rally_id,
                    COALESCE(r.rally_name, r.rally_id) as rally_name,
                    COUNT(DISTINCT s.stage_id) as stage_count
                FROM rallies r
                LEFT JOIN stages s ON s.rally_id = r.rally_id
                GROUP BY r.rally_id, r.rally_name
                ORDER BY CAST(r.rally_id AS INTEGER) DESC
            """
        else:
            query = """
                SELECT DISTINCT
                    rally_id,
                    rally_name,
                    COUNT(DISTINCT stage_number) as stage_count
                FROM stage_results
                GROUP BY rally_id, rally_name
                ORDER BY CAST(rally_id AS INTEGER) DESC
            """
        if limit:
            query += f" LIMIT {int(limit)}"

        df = pd.read_sql_query(query, conn)
        conn.close()
        return df.to_dict('records')
    except:
        return []


def get_stages_for_rally(rally_id: str, db_path: Optional[str] = None) -> pd.DataFrame:
    """Belirli bir ralli için etap listesini yükle."""
    path = db_path or get_db_path()

    if not Path(path).exists():
        return pd.DataFrame()

    conn = sqlite3.connect(path)
    if _table_exists(conn, 'stages'):
        query = """
            SELECT
                s.stage_id,
                s.stage_number,
                s.stage_name,
                COALESCE(
                    CASE
                        WHEN s.surface_override = 1 AND s.surface IS NOT NULL THEN s.surface
                        ELSE NULL
                    END,
                    r.surface
                ) AS surface
            FROM stages s
            LEFT JOIN rallies r ON r.rally_id = s.rally_id
            WHERE s.rally_id = ?
            ORDER BY s.stage_number
        """
    else:
        query = """
            SELECT DISTINCT
                rally_id || '_ss' || stage_number as stage_id,
                stage_number,
                stage_name,
                surface
            FROM stage_results
            WHERE rally_id = ?
            ORDER BY stage_number
        """
    df = pd.read_sql_query(query, conn, params=[str(rally_id)])
    conn.close()
    return df


def get_kml_files(kml_folder: Optional[str] = None) -> List[Dict]:
    """KML/KMZ dosya listesini yükle."""
    folder = Path(kml_folder or get_kml_folder())

    if not folder.exists():
        return []

    files = []
    for ext in ['*.kml', '*.kmz']:
        for f in folder.glob(ext):
            files.append({
                'name': f.name,
                'path': str(f),
                'size_kb': round(f.stat().st_size / 1024, 1),
                'modified': datetime.fromtimestamp(f.stat().st_mtime).strftime('%Y-%m-%d')
            })

    files.sort(key=lambda x: x['name'])
    return files


def get_stage_metadata_df(
    rally_id: Optional[str] = None,
    db_path: Optional[str] = None,
    limit: Optional[int] = None,
) -> pd.DataFrame:
    """Geometrik metadata'yı DataFrame olarak yükle (ML-optimized)."""
    path = db_path or get_db_path()

    if not Path(path).exists():
        return pd.DataFrame()

    conn = sqlite3.connect(path)
    if _table_exists(conn, 'stage_geometry'):
        query = """
            SELECT
                sg.stage_id,
                COALESCE(s.rally_id, sg.rally_id) as rally_id,
                COALESCE(s.stage_name, sg.stage_name) as stage_name,
                sg.source_kml as kml_file,
                COALESCE(sg.surface, s.surface, r.surface) as surface,
                sg.distance_km,
                sg.curvature_density,
                sg.p95_curvature,
                sg.max_grade,
                sg.avg_abs_grade,
                sg.straight_ratio,
                sg.sign_changes_per_km,
                sg.total_ascent,
                sg.total_descent,
                sg.hairpin_count,
                sg.hairpin_density,
                sg.curvature_sum,
                sg.max_curvature,
                sg.geometry_points,
                sg.elevation_api_calls,
                sg.cache_hit_rate,
                sg.analyzed_at as processed_at,
                sg.elevation_status,
                sg.geometry_status,
                sg.geometry_hash,
                sg.validated_at
            FROM stage_geometry sg
            LEFT JOIN stages s ON s.stage_id = sg.stage_id
            LEFT JOIN rallies r ON r.rally_id = COALESCE(s.rally_id, sg.rally_id)
        """
        params = []
        if rally_id:
            query += " WHERE COALESCE(s.rally_id, sg.rally_id) = ?"
            params.append(str(rally_id))
        query += " ORDER BY sg.analyzed_at DESC"
        if limit:
            query += f" LIMIT {int(limit)}"
    else:
        query = """
            SELECT
                stage_id,
                rally_id,
                stage_name,
                kml_file,
                surface,
                distance_km,
                curvature_density,
                p95_curvature,
                max_grade,
                avg_abs_grade,
                straight_ratio,
                sign_changes_per_km,
                total_ascent,
                total_descent,
                hairpin_count,
                hairpin_density,
                curvature_sum,
                max_curvature,
                geometry_points,
                elevation_api_calls,
                cache_hit_rate,
                processed_at
            FROM stages_metadata
        """
        params = []
        if rally_id:
            query += " WHERE rally_id = ?"
            params.append(str(rally_id))
        query += " ORDER BY processed_at DESC"
        if limit:
            query += f" LIMIT {int(limit)}"

    df = pd.read_sql_query(query, conn, params=params if params else None)
    conn.close()

    return df


def get_model_status(db_path: Optional[str] = None, model_dir: Optional[str] = None) -> Dict:
    """Model durumunu kontrol et."""
    try:
        import sys
        from .config import PROJECT_ROOT, get_model_dir

        # src klasörünü path'e ekle
        src_path = str(PROJECT_ROOT)
        if src_path not in sys.path:
            sys.path.insert(0, src_path)

        from src.ml.model_trainer import ModelTrainer

        trainer = ModelTrainer(
            db_path=db_path or get_db_path(),
            model_dir=model_dir or get_model_dir()
        )
        return trainer.get_training_status()
    except Exception as e:
        return {
            'model_exists': False,
            'can_train': False,
            'training_data_count': 0,
            'error': str(e)
        }
