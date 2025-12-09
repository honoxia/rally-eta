import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.scraper.tosfed_sonuc_scraper import TOSFEDSonucScraper
import logging

logging.basicConfig(level=logging.INFO)

scraper = TOSFEDSonucScraper()

# Bilinen farklı kategorileri test et
test_ids = [
    97,  # Ralli - Marmaris
    82,  # Baja (atlanmalı)
    80,  # Offroad (atlanmalı)
    99,  # Ralli - Bodrum
    64,  # Ralli - Hitit
]

print("="*60)
print("KATEGORI FILTRE TESTI")
print("="*60)

for rally_id in test_ids:
    print(f"\n--- Rally ID: {rally_id} ---")

    try:
        rally_data = scraper.fetch_rally_stages(rally_id)

        if rally_data:
            print(f"[OK] KABUL EDILDI: {rally_data['rally_name']}")
            print(f"   Etap sayisi: {len(rally_data['stages'])}")
        else:
            print(f"[SKIP] ATLANDI")
    except Exception as e:
        print(f"[ERROR] Hata: {e}")

print("\n" + "="*60)
print("Test tamamlandi!")
print("="*60)
