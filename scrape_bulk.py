import sys
import os
import logging
import pandas as pd
from datetime import datetime

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__)))

from src.scraper.tosfed_sonuc_scraper import TOSFEDSonucScraper

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scraping_v2.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def scrape_bulk():
    scraper = TOSFEDSonucScraper()
    all_stages = []
    
    # Widen range to capture 2023
    start_id = 1
    end_id = 120
    
    logger.info(f"Starting bulk scrape V1.2 from ID {start_id} to {end_id}")
    
    found_rallies = []
    
    for rally_id in range(start_id, end_id + 1):
        logger.info(f"Checking Rally ID: {rally_id}")
        
        try:
            result = scraper.fetch_rally_stages(rally_id)
            
            if result:
                rally_name = result['rally_name']
                surface = result['surface']
                year = "Unknown"
                
                # Improved year extraction
                if "2023" in rally_name: year = "2023"
                elif "2024" in rally_name: year = "2024"
                elif "2025" in rally_name: year = "2025"
                elif "2022" in rally_name: year = "2022" # Just in case
                
                # Accept 2023, 2024, 2025, and Unknown (we can filter later)
                # But skip 2022 and older if explicitly found
                if year in ["2022", "2021", "2020"]:
                    logger.info(f"Skipping {rally_name} (Year: {year})")
                    continue
                    
                logger.info(f"FOUND: {rally_name} ({year}) - Surface: {surface}")
                found_rallies.append({
                    "id": rally_id,
                    "name": rally_name,
                    "year": year,
                    "surface": surface,
                    "stages": len(result['stages'])
                })
                
                # Process stages into flat records
                for stage in result['stages']:
                    for row in stage['results']:
                        all_stages.append({
                            'rally_id': rally_id,
                            'rally_name': rally_name,
                            'season': year,
                            'surface': surface,
                            'stage_name': stage['stage_name'],
                            'stage_number': stage['stage_number'],
                            'stage_length_km': stage['stage_length_km'],
                            'driver_name': row['driver_name'],
                            'car_class': row['car_class'],
                            'car_model': row['car_model'],
                            'team': row['team'],
                            'time_str': row['time_str'],
                            'status': row['status']
                        })
                        
        except Exception as e:
            logger.error(f"Failed to scrape ID {rally_id}: {e}")
            
    # Save results
    if all_stages:
        df = pd.DataFrame(all_stages)
        
        # Ensure data directory exists
        os.makedirs(os.path.join("data", "raw"), exist_ok=True)
        
        # Save as CSV
        csv_path = os.path.join("data", "raw", "rally_results_v1.2.csv")
        df.to_csv(csv_path, index=False)
        logger.info(f"Saved {len(df)} records to CSV: {csv_path}")
        
        # Save as Excel for verification
        excel_path = os.path.join("data", "raw", "rally_results_v1.2.xlsx")
        try:
            df.to_excel(excel_path, index=False, engine='openpyxl')
            logger.info(f"Saved {len(df)} records to Excel: {excel_path}")
        except Exception as e:
            logger.error(f"Failed to save Excel file: {e}")
            print(f"Warning: Could not save Excel file. Ensure openpyxl is installed. Error: {e}")
        
        print("\n" + "="*50)
        print("SCRAPING SUMMARY V1.2")
        print("="*50)
        print(f"Total Rallies Found: {len(found_rallies)}")
        print(f"Total Records: {len(df)}")
        print(f"Output files:\n- {csv_path}\n- {excel_path}")
        print("\nRallies Found:")
        
        for r in found_rallies:
            print(f"- [ID {r['id']}] {r['name']} ({r['year']}) -> {r['surface']}")
            
    else:
        logger.warning("No data found!")

if __name__ == "__main__":
    scrape_bulk()
