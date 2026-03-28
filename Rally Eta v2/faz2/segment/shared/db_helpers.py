"""
Rally ETA v2.0 - Database Yardımcı Fonksiyonları
Veritabanı bağlantısı, tablo oluşturma ve durum kontrolü.
"""

import sqlite3
import sys
from pathlib import Path
from typing import Optional
from .config import get_db_path


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.master_schema import (
    apply_master_schema,
    ensure_results_master_tables,
    ensure_stage_geometry_table,
    ensure_stage_results_columns,
)


def get_db_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """SQLite veritabanı bağlantısı oluştur."""
    path = db_path or get_db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(path)


def ensure_stage_results_table(db_path: Optional[str] = None, force_recreate: bool = False):
    """stage_results tablosunu oluştur (yoksa) veya yeniden oluştur.

    Args:
        db_path: Database yolu
        force_recreate: True ise tabloyu sil ve yeniden oluştur

    NOT: Yeni yapı:
    - result_id TEXT PRIMARY KEY (format: rally_id_ss{stage}_carnumber)
    - INSERT OR IGNORE ile duplicate'ler atlanır
    """
    conn = get_db_connection(db_path)
    ensure_results_master_tables(conn)
    ensure_stage_results_columns(conn)
    conn.commit()
    conn.close()
    if not force_recreate:
        return

    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    # Tablo var mı ve doğru yapıda mı kontrol et
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='stage_results'")
    table_exists = cursor.fetchone() is not None

    if table_exists:
        # Mevcut kolonları kontrol et
        cursor.execute("PRAGMA table_info(stage_results)")
        existing_cols = {row[1] for row in cursor.fetchall()}
        required_cols = {'result_id', 'rally_id', 'rally_name', 'stage_number', 'stage_name',
                        'car_number', 'driver_name', 'co_driver_name', 'car_class', 'vehicle',
                        'time_str', 'time_seconds', 'diff_str', 'diff_seconds', 'surface',
                        'stage_length_km'}  # Yeni eklenen kolon

        missing_cols = required_cols - existing_cols

        # Eksik kolonları ALTER TABLE ile ekle (tablo yeniden oluşturmadan)
        for col in missing_cols:
            try:
                if col == 'stage_length_km':
                    cursor.execute("ALTER TABLE stage_results ADD COLUMN stage_length_km REAL")
                    print(f"[DB] Kolon eklendi: {col}")
            except Exception as e:
                print(f"[DB] Kolon eklenemedi {col}: {e}")

        # Sadece kritik kolonlar eksikse yeniden oluştur
        critical_missing = missing_cols - {'stage_length_km'}
        if critical_missing or force_recreate:
            # Eski tabloyu yedekle ve sil
            cursor.execute("DROP TABLE IF EXISTS stage_results_backup")
            cursor.execute("ALTER TABLE stage_results RENAME TO stage_results_backup")
            table_exists = False
            print(f"[DB] Eski tablo yedeklendi (eksik kolonlar: {critical_missing})")

    if not table_exists:
        cursor.execute("""
            CREATE TABLE stage_results (
                result_id TEXT PRIMARY KEY,
                rally_id TEXT,
                rally_name TEXT,
                stage_number INTEGER,
                stage_name TEXT,
                stage_length_km REAL,
                car_number TEXT,
                driver_name TEXT,
                co_driver_name TEXT,
                car_class TEXT,
                vehicle TEXT,
                time_str TEXT,
                time_seconds REAL,
                diff_str TEXT,
                diff_seconds REAL,
                surface TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("[DB] stage_results tablosu oluşturuldu")

    conn.commit()
    conn.close()


def ensure_stages_metadata_table(db_path: Optional[str] = None):
    """stages_metadata tablosunu oluştur ve eksik kolonları ekle."""
    conn = get_db_connection(db_path)
    ensure_stage_geometry_table(conn)
    conn.commit()
    conn.close()
    return

    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    # Tablo oluştur
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stages_metadata (
            stage_id TEXT PRIMARY KEY,
            rally_id TEXT,
            stage_name TEXT,
            kml_file TEXT,
            surface TEXT,
            distance_km REAL,
            curvature_sum REAL,
            curvature_density REAL,
            p95_curvature REAL,
            max_curvature REAL,
            avg_curvature REAL,
            hairpin_count INTEGER,
            hairpin_density REAL,
            turn_count INTEGER,
            turn_density REAL,
            straight_ratio REAL,
            sign_changes_per_km REAL,
            total_ascent REAL,
            total_descent REAL,
            max_grade REAL,
            avg_abs_grade REAL,
            max_elevation REAL,
            min_elevation REAL,
            geometry_points INTEGER,
            elevation_api_calls INTEGER,
            cache_hit_rate REAL,
            straight_percentage REAL,
            curvy_percentage REAL,
            analyzer_version TEXT,
            processed_at TEXT
        )
    """)

    # Eksik kolonları ekle (mevcut tabloya)
    existing_cols = {row[1] for row in cursor.execute("PRAGMA table_info(stages_metadata)").fetchall()}
    new_columns = [
        ("turn_count", "INTEGER"),
        ("turn_density", "REAL"),
        ("max_elevation", "REAL"),
        ("min_elevation", "REAL"),
    ]
    for col_name, col_type in new_columns:
        if col_name not in existing_cols:
            try:
                cursor.execute(f"ALTER TABLE stages_metadata ADD COLUMN {col_name} {col_type}")
            except:
                pass

    conn.commit()
    conn.close()


def migrate_add_normalized_columns(db_path: Optional[str] = None):
    """stage_results tablosuna normalized_class, ratio_to_class_best, class_position kolonlarini ekle
    ve mevcut verileri hesapla.

    Bu migration idempotent: kolonlar varsa tekrar eklenmez, veriler doluysa tekrar hesaplanmaz.
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    # 1. Eksik kolonlari ekle
    existing_cols = {row[1] for row in cursor.execute("PRAGMA table_info(stage_results)").fetchall()}

    new_columns = [
        ("normalized_class", "TEXT"),
        ("ratio_to_class_best", "REAL"),
        ("class_position", "INTEGER"),
    ]

    for col_name, col_type in new_columns:
        if col_name not in existing_cols:
            try:
                cursor.execute(f"ALTER TABLE stage_results ADD COLUMN {col_name} {col_type}")
                print(f"[Migration] Kolon eklendi: {col_name}")
            except Exception as e:
                print(f"[Migration] Kolon eklenemedi {col_name}: {e}")

    conn.commit()

    # 2. normalized_class kolonunu doldur (bos olanlari)
    cursor.execute("SELECT COUNT(*) FROM stage_results WHERE normalized_class IS NULL AND car_class IS NOT NULL")
    null_count = cursor.fetchone()[0]

    if null_count > 0:
        print(f"[Migration] {null_count} kayit icin normalized_class hesaplaniyor...")
        try:
            from .config import PROJECT_ROOT
            src_path = str(PROJECT_ROOT)
            if src_path not in sys.path:
                sys.path.insert(0, src_path)
            from src.data.car_class_normalizer import CarClassNormalizer

            normalizer = CarClassNormalizer()

            cursor.execute("SELECT DISTINCT car_class FROM stage_results WHERE car_class IS NOT NULL")
            classes = [row[0] for row in cursor.fetchall()]

            for raw_class in classes:
                normalized = normalizer.normalize(raw_class)
                cursor.execute(
                    "UPDATE stage_results SET normalized_class = ? WHERE car_class = ? AND normalized_class IS NULL",
                    [normalized, raw_class]
                )
            conn.commit()
            print(f"[Migration] normalized_class tamamlandi ({len(classes)} sinif normalize edildi)")
        except Exception as e:
            print(f"[Migration] normalized_class hatasi: {e}")

    # 3. ratio_to_class_best ve class_position hesapla (bos olanlari)
    cursor.execute("""
        SELECT COUNT(*) FROM stage_results
        WHERE ratio_to_class_best IS NULL AND time_seconds > 0 AND time_seconds IS NOT NULL
    """)
    ratio_null_count = cursor.fetchone()[0]

    if ratio_null_count > 0:
        print(f"[Migration] {ratio_null_count} kayit icin ratio_to_class_best ve class_position hesaplaniyor...")
        try:
            # Her (rally_id, stage_number, normalized_class) grubu icin class best hesapla
            cursor.execute("""
                SELECT DISTINCT rally_id, stage_number, COALESCE(normalized_class, car_class) as nclass
                FROM stage_results
                WHERE time_seconds > 0 AND time_seconds IS NOT NULL
            """)
            groups = cursor.fetchall()

            updated = 0
            for rally_id, stage_number, nclass in groups:
                # Class best (en hizli sure)
                cursor.execute("""
                    SELECT MIN(time_seconds) FROM stage_results
                    WHERE rally_id = ? AND stage_number = ?
                    AND COALESCE(normalized_class, car_class) = ?
                    AND time_seconds > 0
                """, [rally_id, stage_number, nclass])
                row = cursor.fetchone()
                if not row or not row[0]:
                    continue
                class_best = row[0]

                # ratio_to_class_best guncelle
                cursor.execute("""
                    UPDATE stage_results
                    SET ratio_to_class_best = time_seconds / ?
                    WHERE rally_id = ? AND stage_number = ?
                    AND COALESCE(normalized_class, car_class) = ?
                    AND time_seconds > 0
                    AND ratio_to_class_best IS NULL
                """, [class_best, rally_id, stage_number, nclass])

                # class_position hesapla (siralama)
                cursor.execute("""
                    SELECT rowid, time_seconds FROM stage_results
                    WHERE rally_id = ? AND stage_number = ?
                    AND COALESCE(normalized_class, car_class) = ?
                    AND time_seconds > 0
                    ORDER BY time_seconds ASC
                """, [rally_id, stage_number, nclass])
                ranked_rows = cursor.fetchall()

                for pos, (rid, _) in enumerate(ranked_rows, 1):
                    cursor.execute(
                        "UPDATE stage_results SET class_position = ? WHERE rowid = ? AND class_position IS NULL",
                        [pos, rid]
                    )

                updated += len(ranked_rows)

            conn.commit()
            print(f"[Migration] ratio_to_class_best ve class_position tamamlandi ({updated} kayit guncellendi)")
        except Exception as e:
            print(f"[Migration] ratio hesaplama hatasi: {e}")

    conn.close()


def ensure_all_tables(db_path: Optional[str] = None):
    """Tüm gerekli tabloları oluştur."""
    apply_master_schema(db_path or get_db_path())
    migrate_add_normalized_columns(db_path)


def get_database_info(db_path: Optional[str] = None) -> dict:
    """Database durumu ve istatistiklerini döndür."""
    path = db_path or get_db_path()

    if not Path(path).exists():
        return {
            'exists': False,
            'message': f'Veritabani bulunamadi: {path}'
        }

    try:
        conn = sqlite3.connect(path)
        cursor = conn.cursor()

        # Sonuç sayısı
        cursor.execute("SELECT COUNT(*) FROM stage_results")
        result_count = cursor.fetchone()[0]

        # Pilot sayısı
        cursor.execute(
            """
            SELECT COUNT(*) FROM sqlite_master
            WHERE type='table' AND name='drivers'
            """
        )
        if cursor.fetchone()[0]:
            cursor.execute("SELECT COUNT(*) FROM drivers")
        else:
            cursor.execute("SELECT COUNT(DISTINCT driver_name) FROM stage_results")
        driver_count = cursor.fetchone()[0]

        # Ralli sayısı
        cursor.execute(
            """
            SELECT COUNT(*) FROM sqlite_master
            WHERE type='table' AND name='rallies'
            """
        )
        if cursor.fetchone()[0]:
            cursor.execute("SELECT COUNT(*) FROM rallies")
        else:
            cursor.execute("SELECT COUNT(DISTINCT rally_id) FROM stage_results")
        rally_count = cursor.fetchone()[0]

        # Geometrik veri sayısı
        try:
            cursor.execute("SELECT COUNT(*) FROM stage_geometry")
            geometry_count = cursor.fetchone()[0]
        except:
            geometry_count = 0

        conn.close()

        return {
            'exists': True,
            'result_count': result_count,
            'driver_count': driver_count,
            'rally_count': rally_count,
            'geometry_count': geometry_count
        }
    except Exception as e:
        return {
            'exists': False,
            'message': str(e)
        }


def execute_query(query: str, params: list = None, db_path: Optional[str] = None) -> list:
    """SQL sorgusu çalıştır ve sonuçları döndür."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    if params:
        cursor.execute(query, params)
    else:
        cursor.execute(query)
    results = cursor.fetchall()
    conn.close()
    return results


def execute_write(query: str, params: list = None, db_path: Optional[str] = None) -> int:
    """SQL yazma sorgusu çalıştır ve etkilenen satır sayısını döndür."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    if params:
        cursor.execute(query, params)
    else:
        cursor.execute(query)
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected
