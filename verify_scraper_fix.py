import sys
import os
import logging

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__)))

from src.scraper.tosfed_sonuc_scraper import TOSFEDSonucScraper

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify_scraper():
    scraper = TOSFEDSonucScraper()
    
    # Try to find a valid rally ID (scanning a small range of recent IDs)
    # Assuming IDs are sequential and recent ones are around 80-100 based on typical counts
    # Or I can try to find a specific one if I knew it.
    # Let's try a few IDs.
    
    found = False
    for rally_id in range(80, 100):
        logger.info(f"Testing Rally ID: {rally_id}")
        result = scraper.fetch_rally_stages(rally_id)
        
        if result:
            print("\n" + "="*50)
            print(f"SUCCESS! Found Rally: {result['rally_name']}")
            print(f"ID: {result['rally_id']}")
            print(f"Surface: {result['surface']}")
            print(f"Total Stages Found: {len(result['stages'])}")
            print("="*50 + "\n")
            
            # Print first stage details
            if result['stages']:
                first_stage = result['stages'][0]
                print(f"Stage 1: {first_stage['stage_name']} ({first_stage['stage_length_km']} km)")
                print(f"Results count: {len(first_stage['results'])}")
                if first_stage['results']:
                    print(f"Winner: {first_stage['results'][0]['driver_name']} - {first_stage['results'][0]['time_str']}")
            
            found = True
            break
            
    if not found:
        print("No valid rally found in the tested range (80-100).")

if __name__ == "__main__":
    verify_scraper()
