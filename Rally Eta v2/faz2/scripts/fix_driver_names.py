"""
Pilot isimlerini standartlaştırır - büyük/küçük harf uyumsuzluğunu düzeltir.

Her ismi "Title Case" formatına çevirir: ALİ TÜRKKAN -> Ali Türkkan
Türkçe karakterleri doğru işler.
"""

import sqlite3
import sys
from pathlib import Path


def turkish_title_case(name: str) -> str:
    """Türkçe karakterleri destekleyen title case."""
    if not name:
        return name

    # Türkçe karakter eşleştirmeleri
    lower_map = {
        'I': 'ı',  # I -> ı (Türkçe)
        'İ': 'i',  # İ -> i (Türkçe)
    }
    upper_map = {
        'i': 'İ',  # i -> İ (Türkçe)
        'ı': 'I',  # ı -> I (Türkçe)
    }

    words = name.split()
    result = []

    for word in words:
        if not word:
            continue

        # İlk harf büyük
        first_char = word[0]
        if first_char == 'i':
            first_char = 'İ'
        elif first_char == 'ı':
            first_char = 'I'
        else:
            first_char = first_char.upper()

        # Geri kalan harfler küçük
        rest = ''
        for c in word[1:]:
            if c == 'I':
                rest += 'ı'
            elif c == 'İ':
                rest += 'i'
            else:
                rest += c.lower()

        result.append(first_char + rest)

    return ' '.join(result)


def fix_driver_names(db_path: str, dry_run: bool = True):
    """Pilot isimlerini standartlaştır."""

    if not Path(db_path).exists():
        print(f"HATA: Veritabanı bulunamadı: {db_path}")
        return False

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Tüm benzersiz pilot isimlerini al
    cursor.execute("SELECT DISTINCT driver_name FROM stage_results")
    all_names = [row[0] for row in cursor.fetchall() if row[0]]

    print(f"Toplam {len(all_names)} benzersiz pilot ismi bulundu.\n")

    # İsimleri grupla (büyük/küçük harf görmezden gel)
    name_groups = {}
    for name in all_names:
        key = name.upper()
        if key not in name_groups:
            name_groups[key] = []
        name_groups[key].append(name)

    # Birden fazla varyasyonu olan isimleri bul
    duplicates = {k: v for k, v in name_groups.items() if len(v) > 1}

    print(f"Çoklu varyasyon bulunan isimler: {len(duplicates)}\n")

    fixed_count = 0

    for key, variants in duplicates.items():
        # En çok kullanılan varyantı bul
        variant_counts = {}
        for v in variants:
            cursor.execute("SELECT COUNT(*) FROM stage_results WHERE driver_name = ?", [v])
            variant_counts[v] = cursor.fetchone()[0]

        # Title case versiyonunu standart olarak kullan
        standard_name = turkish_title_case(variants[0])

        print(f"  {key}:")
        for v, cnt in variant_counts.items():
            marker = " -> " + standard_name if v != standard_name else " (standart)"
            print(f"    - '{v}' ({cnt} kayıt){marker}")

        # Güncelle
        if not dry_run:
            for v in variants:
                if v != standard_name:
                    cursor.execute(
                        "UPDATE stage_results SET driver_name = ? WHERE driver_name = ?",
                        [standard_name, v]
                    )
                    fixed_count += cursor.rowcount
        else:
            for v in variants:
                if v != standard_name:
                    cursor.execute("SELECT COUNT(*) FROM stage_results WHERE driver_name = ?", [v])
                    fixed_count += cursor.fetchone()[0]

        print()

    if not dry_run:
        conn.commit()

    conn.close()

    print(f"{'='*50}")
    print(f"Sonuç ({'DRY RUN' if dry_run else 'GERÇEK'}):")
    print(f"  - Düzeltilen kayıt sayısı: {fixed_count}")

    if dry_run and fixed_count > 0:
        print(f"\nGerçekten düzeltmek için: python {__file__} <db_path> --apply")

    return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Kullanım: python fix_driver_names.py <database_path> [--apply]")
        print("  --apply: Gerçekten düzelt (olmadan sadece kontrol eder)")
        sys.exit(1)

    db_path = sys.argv[1]
    dry_run = "--apply" not in sys.argv

    fix_driver_names(db_path, dry_run)
