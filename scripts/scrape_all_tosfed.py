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
import requests

logging.basicConfig(level=logging.INFO)

scraper = TOSFEDSonucScraper()
parser = TimeParser()
db = Database()

# Ralli ID'leri (2023-2025)
rally_ids = range(50, 100)  # Son 50 yarış

results_to_save = []
total_results = 0

# Statistics
stats = {
    'total_checked': 0,
    'rally_found': 0,
    'baja_skipped': 0,
    'offroad_skipped': 0,
    'not_found': 0,
    'error': 0
}

for rally_id in rally_ids:
    stats['total_checked'] += 1

    try:
        print(f"\n{'='*60}")
        print(f"Rally ID: {rally_id}")
        print(f"{'='*60}")

        rally_data = scraper.fetch_rally_stages(rally_id)

        # Check if skipped due to category
        if rally_data is None:
            print(f"[SKIPPED] Rally {rally_id}")
            continue

        stats['rally_found'] += 1

        print(f"Rally: {rally_data['rally_name']}")
        print(f"Etap sayısı: {len(rally_data['stages'])}")

        for stage in rally_data['stages']:
            print(f"  - {stage['stage_name']}: {len(stage['results'])} sonuç")

            for result in stage['results']:
                # Database formatına çevir
                row = {
                    'result_id': f"{rally_data['rally_id']}_ss{stage['stage_number']}_{result['car_number']}",
                    'rally_id': str(rally_data['rally_id']),
                    'rally_name': rally_data['rally_name'],
                    'stage_id': f"{rally_data['rally_id']}_ss{stage['stage_number']}",
                    'stage_name': stage['stage_name'],
                    'stage_number': stage['stage_number'],
                    'stage_length_km': stage['stage_length_km'],
                    'driver_id': result['car_number'],  # Using car number as driver ID for now
                    'driver_name': result['driver_name'],
                    'car_model': result['car_model'],
                    'car_class': result['car_class'],
                    'raw_time_str': result['time_str'],
                    'time_seconds': parser.parse(result['time_str']),
                    'status': result['status'],
                    'surface': 'gravel',  # Varsayılan (elle düzeltilmeli)
                }

                results_to_save.append(row)
                total_results += 1

        # Her 5 rallide bir kaydet
        if len(results_to_save) >= 500:
            print(f"\n[SAVING] {len(results_to_save)} sonuc kaydediliyor...")
            df = pd.DataFrame(results_to_save)
            db.save_dataframe(df, 'stage_results', if_exists='append')
            results_to_save = []

    except requests.exceptions.HTTPError as e:
        if '404' in str(e):
            stats['not_found'] += 1
            print(f"[404] Rally {rally_id} not found")
        else:
            stats['error'] += 1
            logging.error(f"Rally {rally_id} HTTP error: {e}")
        continue
    except Exception as e:
        stats['error'] += 1
        logging.error(f"Rally {rally_id} error: {e}")
        continue

# Kalan veriyi kaydet
if results_to_save:
    print(f"\n[SAVING] Son {len(results_to_save)} sonuc kaydediliyor...")
    df = pd.DataFrame(results_to_save)
    db.save_dataframe(df, 'stage_results', if_exists='append')

print(f"\n{'='*60}")
print(f"[OK] Toplam {total_results} sonuc kaydedildi!")
print(f"\n[STATS]")
print(f"  Total checked: {stats['total_checked']}")
print(f"  Rally found: {stats['rally_found']}")
print(f"  Skipped (non-rally): {stats['total_checked'] - stats['rally_found'] - stats['not_found'] - stats['error']}")
print(f"  Not found (404): {stats['not_found']}")
print(f"  Errors: {stats['error']}")
print(f"{'='*60}")
