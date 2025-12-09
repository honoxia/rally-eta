import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.scraper.tosfed_sonuc_scraper import TOSFEDSonucScraper
from src.utils.database import Database
from src.preprocessing.time_parser import TimeParser
import pandas as pd
import logging

logging.basicConfig(level=logging.ERROR)  # Sadece hatalar

scraper = TOSFEDSonucScraper()
parser = TimeParser()
db = Database()

# Geniş aralık test et
print("Taranıyor: Rally ID 1-100...")
rally_ids = list(range(1, 101))  # 1-100 arası tüm ID'ler

result = scraper.scrape_multiple_rallies(rally_ids)

# İstatistikleri göster
stats = result['stats']
print("\n" + "="*60)
print("SCRAPING SONUÇLARI")
print("="*60)
print(f"Kontrol edilen toplam: {stats['total_checked']}")
print(f"[OK] Bulunan ralli: {stats['rally_found']}")
print(f"[SKIP] Atlanan (kategori): {stats['total_checked'] - stats['rally_found'] - stats['not_found'] - stats['error']}")
print(f"[404] Bulunamayan: {stats['not_found']}")
print(f"[ERROR] Hata: {stats['error']}")
print("="*60)

# Bulunan rallileri listele
if stats['rally_details']:
    print(f"\nBulunan {len(stats['rally_details'])} Ralli:")
    for detail in stats['rally_details']:
        print(f"  {detail['id']:3d}. {detail['name'][:60]} ({detail['stages']} etap)")

# Database'e kaydet
if result['rallies']:
    print(f"\nToplam {len(result['rallies'])} ralli bulundu.")
    save = input(f"Database'e kaydetmek ister misin? (y/n): ")

    if save.lower() == 'y':
        all_rows = []

        for rally_data in result['rallies']:
            for stage in rally_data['stages']:
                for result_row in stage['results']:
                    row = {
                        'result_id': f"{rally_data['rally_id']}_ss{stage['stage_number']}_{result_row['car_number']}",
                        'rally_id': str(rally_data['rally_id']),
                        'rally_name': rally_data['rally_name'],
                        'stage_id': f"{rally_data['rally_id']}_ss{stage['stage_number']}",
                        'stage_name': stage['stage_name'],
                        'stage_number': stage['stage_number'],
                        'stage_length_km': stage['stage_length_km'],
                        'driver_id': result_row['car_number'],
                        'driver_name': result_row['driver_name'],
                        'car_model': result_row['car_model'],
                        'car_class': result_row['car_class'],
                        'raw_time_str': result_row['time_str'],
                        'time_seconds': parser.parse(result_row['time_str']),
                        'status': result_row['status'],
                        'surface': 'gravel',  # Varsayılan
                    }
                    all_rows.append(row)

        print(f"\n[SAVING] {len(all_rows)} sonuc kaydediliyor...")
        df = pd.DataFrame(all_rows)
        db.save_dataframe(df, 'stage_results', if_exists='append')

        print(f"[OK] {len(all_rows)} sonuc kaydedildi!")
else:
    print("\nHiç ralli bulunamadı.")
