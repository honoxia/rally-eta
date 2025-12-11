"""EWRC-Results Scraper for Turkish Rally Championship"""
import requests
from pyquery import PyQuery as pq
import re
from typing import Dict, List, Optional
import logging
import time

logger = logging.getLogger(__name__)


class EWRCScraper:
    """Scraper for EWRC-Results.com"""

    BASE_URL = "https://www.ewrc-results.com"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

    def get_turkish_rallies(self, year: int = 2025) -> List[Dict]:
        """Get all Turkish rallies for a given year"""
        url = f"{self.BASE_URL}/season/{year}/?nat=20"  # nat=20 = Turkey

        logger.info(f"Fetching Turkish rallies for {year}...")

        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()

            doc = pq(response.text)
            rallies = []

            # Find all rally links
            for link in doc('a[href*="/final/"]').items():
                href = link.attr('href')
                if not href or 'final' not in href:
                    continue

                rally_name = link.text().strip()
                rally_id = href.split('/')[2].split('-')[0]

                if rally_name and rally_id:
                    rallies.append({
                        'rally_id': rally_id,
                        'rally_name': rally_name,
                        'url': self.BASE_URL + href
                    })

            logger.info(f"Found {len(rallies)} Turkish rallies for {year}")
            return rallies

        except Exception as e:
            logger.error(f"Error fetching Turkish rallies: {e}")
            return []

    def scrape_rally(self, rally_url: str) -> Optional[Dict]:
        """Scrape a single rally"""
        logger.info(f"Scraping rally: {rally_url}")

        try:
            response = self.session.get(rally_url, timeout=30)
            response.raise_for_status()

            doc = pq(response.text)

            # Extract rally info
            rally_info = self._extract_rally_info(doc)

            # Extract stages
            stages = self._extract_stages(doc, rally_url)

            return {
                'rally_info': rally_info,
                'stages': stages
            }

        except Exception as e:
            logger.error(f"Error scraping rally {rally_url}: {e}")
            return None

    def _extract_rally_info(self, doc) -> Dict:
        """Extract rally metadata"""
        info = {}

        # Rally name
        title = doc('h1').text()
        info['rally_name'] = title.strip()

        # Rally details (date, surface, distance)
        details = doc('div.text-center.text-muted.mb-3').text()

        # Extract date
        date_match = re.search(r'(\d+)\.\s*(\d+)\.\s*–\s*(\d+)\.\s*(\d+)\.\s*(\d{4})', details)
        if date_match:
            day1, month1, day2, month2, year = date_match.groups()
            # Use end date as rally date
            info['rally_date'] = f"{year}-{month2.zfill(2)}-{day2.zfill(2)}"
            info['rally_year'] = int(year)

        # Extract surface
        if 'asphalt' in details.lower():
            info['surface'] = 'asphalt'
        elif 'gravel' in details.lower():
            info['surface'] = 'gravel'
        elif 'snow' in details.lower() or 'ice' in details.lower():
            info['surface'] = 'snow/ice'
        else:
            info['surface'] = 'unknown'

        # Extract total distance
        distance_match = re.search(r'(\d+\.?\d*)\s*km', details)
        if distance_match:
            info['total_distance_km'] = float(distance_match.group(1))

        logger.info(f"Rally: {info.get('rally_name')} ({info.get('rally_date')}) - {info.get('surface')}")

        return info

    def _extract_stages(self, doc, rally_url: str) -> List[Dict]:
        """Extract stage results"""
        stages = []

        # Try to find stages page link
        stages_link = doc('a[href*="/stages/"]')
        if stages_link:
            stages_url = self.BASE_URL + stages_link.attr('href')
            logger.info(f"Fetching stages from: {stages_url}")

            try:
                response = self.session.get(stages_url, timeout=30)
                response.raise_for_status()
                stage_doc = pq(response.text)

                # Parse each stage
                for stage_row in stage_doc('table.stages tr').items():
                    stage_data = self._parse_stage_row(stage_row, rally_url)
                    if stage_data:
                        stages.append(stage_data)

            except Exception as e:
                logger.warning(f"Could not fetch stages page: {e}")

        logger.info(f"Found {len(stages)} stages")
        return stages

    def _parse_stage_row(self, row, rally_url: str) -> Optional[Dict]:
        """Parse a single stage row"""
        try:
            cells = row('td')
            if len(cells) < 3:
                return None

            # Stage number
            stage_num_text = cells.eq(0).text()
            stage_num_match = re.search(r'\d+', stage_num_text)
            if not stage_num_match:
                return None

            stage_number = int(stage_num_match.group())

            # Stage name
            stage_name = cells.eq(1).text().strip()

            # Stage length
            length_text = cells.eq(2).text()
            length_match = re.search(r'(\d+\.?\d*)', length_text)
            stage_length_km = float(length_match.group(1)) if length_match else 0.0

            # Get stage results link
            stage_link = cells.eq(1).find('a').attr('href')
            if stage_link:
                stage_results_url = self.BASE_URL + stage_link
                results = self._fetch_stage_results(stage_results_url)
            else:
                results = []

            return {
                'stage_number': stage_number,
                'stage_name': stage_name,
                'stage_length_km': stage_length_km,
                'results': results
            }

        except Exception as e:
            logger.warning(f"Error parsing stage row: {e}")
            return None

    def _fetch_stage_results(self, stage_url: str) -> List[Dict]:
        """Fetch results for a single stage"""
        try:
            time.sleep(0.5)  # Rate limiting

            response = self.session.get(stage_url, timeout=30)
            response.raise_for_status()

            doc = pq(response.text)
            results = []

            # Parse results table
            for row in doc('table.results tr').items():
                result = self._parse_result_row(row)
                if result:
                    results.append(result)

            logger.info(f"  Stage results: {len(results)} drivers")
            return results

        except Exception as e:
            logger.warning(f"Error fetching stage results from {stage_url}: {e}")
            return []

    def _parse_result_row(self, row) -> Optional[Dict]:
        """Parse a single result row"""
        try:
            cells = row('td')
            if len(cells) < 6:
                return None

            # Position
            position_text = cells.eq(0).text().strip()
            if not position_text or not position_text[0].isdigit():
                return None

            position = int(re.search(r'\d+', position_text).group())

            # Driver name (in entry column)
            entry_cell = cells.eq(1)
            driver_link = entry_cell.find('a')
            driver_name = driver_link.text().strip() if driver_link else entry_cell.text().strip()

            # Car info
            car_cell = cells.eq(2)
            car_model = car_cell.text().strip()

            # Class
            class_cell = cells.eq(3)
            car_class = class_cell.text().strip()

            # Time
            time_cell = cells.eq(4)
            time_str = time_cell.text().strip()

            # Status
            status = 'FINISHED' if position > 0 and time_str else 'DNF'

            return {
                'position': position,
                'driver_name': driver_name,
                'car_model': car_model,
                'car_class': car_class,
                'time_str': time_str,
                'status': status
            }

        except Exception as e:
            logger.debug(f"Error parsing result row: {e}")
            return None


if __name__ == '__main__':
    # Test scraper
    logging.basicConfig(level=logging.INFO)

    scraper = EWRCScraper()

    # Get Turkish rallies
    rallies = scraper.get_turkish_rallies(2025)

    print(f"\nFound {len(rallies)} rallies:")
    for rally in rallies[:5]:
        print(f"  - {rally['rally_name']} (ID: {rally['rally_id']})")

    # Test scrape first rally
    if rallies:
        print(f"\nTest scraping: {rallies[0]['rally_name']}")
        data = scraper.scrape_rally(rallies[0]['url'])

        if data:
            print(f"Rally: {data['rally_info']['rally_name']}")
            print(f"Date: {data['rally_info'].get('rally_date')}")
            print(f"Surface: {data['rally_info'].get('surface')}")
            print(f"Stages: {len(data['stages'])}")
