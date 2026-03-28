"""
Mevcut veritabanındaki yanlış time_seconds değerlerini düzeltir.

Sorun: time_str "04:02:1" (4 dakika 2.1 saniye) iken
       time_seconds 14521.0 (4 saat 2 dakika) olarak kaydedilmiş.

Bu script tüm kayıtları okuyup time_seconds'ı doğru hesaplar.
"""

import sqlite3
import sys
from pathlib import Path


def parse_time_correct(time_str: str) -> float:
    """Zaman string'ini doğru şekilde saniyeye çevir.

    Ralli zaman formatları:
    - MM:SS.d veya MM:SS:d (4:02.1 veya 04:02:1) -> 4 dakika 2.1 saniye
    - HH:MM:SS.d (1:04:02.1) -> 1 saat 4 dakika 2.1 saniye (uzun etaplar)
    """
    if not time_str or ':' not in time_str:
        return 0

    try:
        time_str = time_str.replace(',', '.')
        parts = time_str.split(':')

        if len(parts) == 2:
            # MM:SS.d formatı
            minutes = float(parts[0])
            seconds = float(parts[1])
            return minutes * 60 + seconds

        elif len(parts) == 3:
            first = float(parts[0])
            second = float(parts[1])
            third = float(parts[2])

            # Üçüncü değer 10'dan küçükse muhtemelen onda bir saniye (MM:SS:d)
            if third < 10 and second < 60:
                # MM:SS:d formatı (örn: 04:02:1 = 4 dakika 2.1 saniye)
                minutes = first
                seconds = second + third / 10.0
                return minutes * 60 + seconds
            else:
                # HH:MM:SS formatı
                hours = first
                minutes = second
                seconds = third
                return hours * 3600 + minutes * 60 + seconds
    except:
        pass

    return 0


def parse_stage_length_from_name(stage_name: str) -> float:
    """stage_name içinden etap uzunluğunu parse et.

    Örnek: "ÖE1 - BURSA BÜYÜKŞEHİR BELEDİYE - 1 - 8.0km" -> 8.0
    """
    import re

    if not stage_name:
        return 0

    # "X.Xkm" veya "X,Xkm" formatını ara
    match = re.search(r'(\d+[.,]?\d*)\s*km', stage_name, re.IGNORECASE)
    if match:
        length_str = match.group(1).replace(',', '.')
        try:
            return float(length_str)
        except:
            pass

    return 0


def fix_database(db_path: str, dry_run: bool = True):
    """Veritabanındaki time_seconds değerlerini düzelt."""

    if not Path(db_path).exists():
        print(f"HATA: Veritabanı bulunamadı: {db_path}")
        return False

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Mevcut kolonları kontrol et
    cursor.execute("PRAGMA table_info(stage_results)")
    columns = {row[1] for row in cursor.fetchall()}

    has_stage_length = 'stage_length_km' in columns

    # stage_length_km kolonu yoksa ekle
    if not has_stage_length:
        print("stage_length_km kolonu ekleniyor...")
        cursor.execute("ALTER TABLE stage_results ADD COLUMN stage_length_km REAL")
        conn.commit()
        has_stage_length = True

    # Tüm kayıtları al
    cursor.execute("SELECT result_id, time_str, time_seconds, stage_name FROM stage_results")
    rows = cursor.fetchall()

    print(f"Toplam {len(rows)} kayıt kontrol ediliyor...")

    fixed_time = 0
    fixed_length = 0
    errors = 0

    for result_id, time_str, old_time_seconds, stage_name in rows:
        try:
            # Yeni time_seconds hesapla
            new_time_seconds = parse_time_correct(time_str)

            # stage_length_km hesapla
            stage_length = parse_stage_length_from_name(stage_name)

            # Fark var mı kontrol et
            time_diff = abs(old_time_seconds - new_time_seconds) if old_time_seconds else 0

            if time_diff > 1:  # 1 saniyeden fazla fark varsa
                if dry_run:
                    print(f"  {result_id}: {time_str} -> {old_time_seconds:.1f}s (yanlis) -> {new_time_seconds:.1f}s (dogru)")
                else:
                    cursor.execute(
                        "UPDATE stage_results SET time_seconds = ?, stage_length_km = ? WHERE result_id = ?",
                        [new_time_seconds, stage_length, result_id]
                    )
                fixed_time += 1
            elif stage_length > 0 and has_stage_length:
                # Sadece stage_length güncelle
                if not dry_run:
                    cursor.execute(
                        "UPDATE stage_results SET stage_length_km = ? WHERE result_id = ?",
                        [stage_length, result_id]
                    )
                fixed_length += 1

        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"  HATA {result_id}: {e}")

    if not dry_run:
        conn.commit()

    conn.close()

    print(f"\n{'='*50}")
    print(f"Sonuç ({'DRY RUN' if dry_run else 'GERCEK'}):")
    print(f"  - time_seconds düzeltilecek: {fixed_time}")
    print(f"  - stage_length_km eklenecek: {fixed_length}")
    print(f"  - Hatalar: {errors}")

    if dry_run and fixed_time > 0:
        print(f"\nGerçekten düzeltmek için: python {__file__} <db_path> --apply")

    return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Kullanım: python fix_time_seconds.py <database_path> [--apply]")
        print("  --apply: Gerçekten düzelt (olmadan sadece kontrol eder)")
        sys.exit(1)

    db_path = sys.argv[1]
    dry_run = "--apply" not in sys.argv

    fix_database(db_path, dry_run)
