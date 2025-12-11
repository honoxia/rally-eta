"""Simple EWRC-Results Scraper for Turkish Rally Championship"""
import requests
from bs4 import BeautifulSoup
import re
from typing import Dict, List, Optional
import logging
import time
import pandas as pd

logger = logging.getLogger(__name__)


class EWRCScraperSimple:
    """Simple scraper for EWRC-Results.com using BeautifulSoup"""

    BASE_URL = "https://www.ewrc-results.com"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

    def get_turkish_rallies_2025(self) -> List[Dict]:
        """Get 2025 Turkish rallies - hardcoded known rallies"""
        return [
            {'rally_id': '93118', 'rally_name': 'Marmaris Ege Rallisi 2025', 'surface': 'asphalt'},
            {'rally_id': '93119', 'rally_name': 'Rally Bodrum 2025', 'surface': 'asphalt'},
            {'rally_id': '93120', 'rally_name': 'Yeşil Bursa Rallisi 2025', 'surface': 'asphalt'},
            {'rally_id': '93121', 'rally_name': 'Kapadokya Rallisi 2025', 'surface': 'gravel'},
            {'rally_id': '92141', 'rally_name': 'ESOK Rally 2025', 'surface': 'asphalt'},
            {'rally_id': '93122', 'rally_name': 'Eskişehir Rallisi 2025', 'surface': 'asphalt'},
        ]

    def scrape_rally_results(self, rally_id: str, rally_name: str, surface: str) -> pd.DataFrame:
        """Scrape rally results page and return as DataFrame"""
        url = f"{self.BASE_URL}/results/{rally_id}-{rally_name.lower().replace(' ', '-')}/"

        logger.info(f"Scraping: {rally_name} ({surface})")
        logger.info(f"URL: {url}")

        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')

            # Extract rally date
            rally_date = self._extract_rally_date(soup)

            # Find all stage tables
            stages_data = []
            tables = soup.find_all('table', class_='results')

            for table in tables:
                # Get stage header (before table)
                stage_info = self._extract_stage_info(table)

                if not stage_info:
                    continue

                # Parse results
                for row in table.find_all('tr')[1:]:  # Skip header
                    result = self._parse_result_row(row, stage_info, rally_name, rally_date, surface)
                    if result:
                        stages_data.append(result)

            df = pd.DataFrame(stages_data)
            logger.info(f"Scraped {len(df)} results from {rally_name}")

            return df

        except Exception as e:
            logger.error(f"Error scraping {rally_name}: {e}")
            return pd.DataFrame()

    def _extract_rally_date(self, soup) -> Optional[str]:
        """Extract rally date from page"""
        try:
            # Look for date pattern in text
            text = soup.get_text()
            date_match = re.search(r'(\d+)\.\s*(\d+)\.\s*–\s*(\d+)\.\s*(\d+)\.\s*(2025|2024)', text)

            if date_match:
                day1, month1, day2, month2, year = date_match.groups()
                return f"{year}-{month2.zfill(2)}-{day2.zfill(2)}"

            return f"2025-01-01"  # Fallback

        except:
            return "2025-01-01"

    def _extract_stage_info(self, table) -> Optional[Dict]:
        """Extract stage number, name and length from table context"""
        try:
            # Look for stage header before table
            prev_elem = table.find_previous_sibling()

            if not prev_elem:
                prev_elem = table.parent.find_previous_sibling()

            if prev_elem:
                text = prev_elem.get_text()

                # Extract stage number (SS1, SS2, etc.)
                stage_num_match = re.search(r'SS\s*(\d+)', text, re.IGNORECASE)
                if not stage_num_match:
                    return None

                stage_number = int(stage_num_match.group(1))

                # Extract stage name and length
                # Format: "SS1 - Stage Name - 12.50 km"
                stage_name = text.strip()

                # Extract length
                length_match = re.search(r'(\d+\.?\d*)\s*km', text, re.IGNORECASE)
                stage_length_km = float(length_match.group(1)) if length_match else 0.0

                return {
                    'stage_number': stage_number,
                    'stage_name': stage_name,
                    'stage_length_km': stage_length_km
                }

        except Exception as e:
            logger.debug(f"Could not extract stage info: {e}")

        return None

    def _parse_result_row(self, row, stage_info: Dict, rally_name: str, rally_date: str, surface: str) -> Optional[Dict]:
        """Parse a single result row"""
        try:
            cells = row.find_all('td')

            if len(cells) < 5:
                return None

            # Position
            pos_text = cells[0].get_text(strip=True)
            if not pos_text or not pos_text[0].isdigit():
                return None

            # Driver name
            driver_cell = cells[1]
            driver_link = driver_cell.find('a')
            driver_name = driver_link.get_text(strip=True) if driver_link else driver_cell.get_text(strip=True)

            if not driver_name:
                return None

            # Car model
            car_cell = cells[2]
            car_model = car_cell.get_text(strip=True)

            # Class
            class_cell = cells[3]
            car_class = class_cell.get_text(strip=True)

            # Time
            time_cell = cells[4]
            time_str = time_cell.get_text(strip=True)

            # Status
            status = 'FINISHED' if time_str and ':' in time_str else 'DNF'

            return {
                'rally_name': rally_name,
                'rally_date': rally_date,
                'rally_year': 2025,
                'stage_name': stage_info['stage_name'],
                'stage_number': stage_info['stage_number'],
                'stage_length_km': stage_info['stage_length_km'],
                'surface': surface,
                'day_or_night': 'day',  # Default
                'driver_name': driver_name,
                'car_model': car_model,
                'car_class': car_class,
                'raw_time_str': time_str,
                'status': status
            }

        except Exception as e:
            logger.debug(f"Error parsing row: {e}")
            return None


if __name__ == '__main__':
    # Test scraper
    logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')

    scraper = EWRCScraperSimple()

    # Test with Marmaris
    rallies = scraper.get_turkish_rallies_2025()

    for rally in rallies[:2]:  # Test first 2
        df = scraper.scrape_rally_results(
            rally['rally_id'],
            rally['rally_name'],
            rally['surface']
        )

        if len(df) > 0:
            print(f"\n✓ {rally['rally_name']}")
            print(f"  Surface: {rally['surface']}")
            print(f"  Results: {len(df)}")
            print(f"  Stages: {df['stage_number'].nunique()}")
            print(f"  Drivers: {df['driver_name'].nunique()}")
            print(f"\n  Sample:")
            print(df[['stage_number', 'stage_name', 'driver_name', 'car_class', 'raw_time_str']].head(3))
        else:
            print(f"\n× {rally['rally_name']} - NO DATA")

        time.sleep(2)  # Rate limiting
