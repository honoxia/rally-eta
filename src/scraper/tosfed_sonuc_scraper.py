"""TOSFED Rally Results Scraper"""
import requests
from bs4 import BeautifulSoup
from typing import Dict, List, Optional
import logging
import re
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
import sys
import os
import pandas as pd

logger = logging.getLogger(__name__)


class TOSFEDSonucScraper:
    """Scraper for TOSFED rally results"""

    BASE_URL = "https://tosfedsonuc.com"

    def __init__(self, use_selenium=True):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        self.use_selenium = use_selenium
        self.driver = None

    def fetch_rally_stages(self, rally_id: int) -> Optional[Dict]:
        """Fetch all stage results for a rally"""
        if self.use_selenium:
            return self._fetch_rally_stages_selenium(rally_id)
        else:
            return self._fetch_rally_stages_static(rally_id)

    def _fetch_rally_stages_static(self, rally_id: int) -> Optional[Dict]:
        """Fetch rally stages using static HTML parsing (limited)"""
        # Önce herhangi bir etap sayfasını al (kategori kontrolü için)
        check_url = f"{self.BASE_URL}/yaris/{rally_id}/ralli_etap_sonuclari_print/"

        logger.info(f"Checking rally {rally_id} from {check_url}")

        try:
            response = self.session.get(check_url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            # Get rally name
            rally_name = self._extract_rally_name(soup)

            # CATEGORY CHECK - VERY IMPORTANT!
            if not self._is_rally_category(rally_name, soup):
                logger.info(f"[SKIP] Rally {rally_id} - Category: {rally_name}")
                return None

            logger.info(f"[OK] Rally {rally_id} - {rally_name}")

            # TOSFED sitesi JavaScript kullanarak etapları gösterir
            # Bu yüzden tüm etapları direkt çekemiyoruz
            #
            # ÇÖZÜM: Kullanıcıya not göster - manuel veri toplama gerekebilir
            # veya sadece mevcut sayfadaki tabloları parse et

            logger.warning("  TOSFED uses JavaScript for stage navigation")
            logger.warning("  Only fetching stages from current page")
            logger.warning("  For complete data, use TOSFED website directly")

            stages = []
            tables = soup.find_all('table')

            for table in tables:
                stage_data = self._parse_stage_table(table)
                if stage_data and len(stage_data.get('results', [])) > 0:
                    stages.append(stage_data)

            logger.info(f"  [TOTAL] {len(stages)} stages fetched from current page")

            if len(stages) < 5:
                logger.warning(f"  WARNING: Only {len(stages)} stages found - rally may have more stages!")
                logger.warning(f"  Consider manual data collection from TOSFED website")

            return {
                'rally_id': rally_id,
                'rally_name': rally_name,
                'stages': stages
            }

        except requests.RequestException as e:
            logger.error(f"Error fetching rally {rally_id}: {e}")
            raise

    def _find_day_result_links(self, soup: BeautifulSoup, rally_id: int) -> List[str]:
        """Gün sonu sonuç linklerini bul (1.Gün, 2.Gün, ...)"""
        day_links = []

        # Linkler: "/yaris/{rally_id}/{etap_id}/ralli_etap_sonuclari_gunsonu_print/"
        all_links = soup.find_all('a', href=True)

        for link in all_links:
            href = link['href']
            link_text = link.get_text(strip=True).lower()

            # "X.Gün Sonuçları" veya "Leg X" linklerini bul
            if 'gunsonu_print' in href and str(rally_id) in href:
                if 'gün' in link_text or 'leg' in link_text:
                    full_url = href if href.startswith('http') else f"{self.BASE_URL}{href}"
                    if full_url not in day_links:
                        day_links.append(full_url)

        return sorted(set(day_links))

    def _fetch_day_results(self, url: str) -> List[Dict]:
        """Bir günün tüm etap sonuçlarını çek"""
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            # Sayfadaki tüm tabloları parse et (her tablo bir etap)
            tables = soup.find_all('table')
            stages = []

            for table in tables:
                stage_data = self._parse_stage_table(table)
                if stage_data:
                    stages.append(stage_data)

            return stages

        except Exception as e:
            logger.warning(f"Error fetching day results {url}: {e}")
            return []

    def _count_stages(self, soup: BeautifulSoup) -> int:
        """Sayfadaki toplam etap sayısını bul (Etap-1, Etap-2, ... butonlarından)"""
        # Etap butonlarını ara: <a id="et1" ...>Etap-1</a>
        stage_buttons = soup.find_all('a', id=lambda x: x and x.startswith('et'))

        if stage_buttons:
            # En büyük etap numarasını bul
            max_stage = 0
            for button in stage_buttons:
                btn_id = button.get('id', '')
                if btn_id.startswith('et'):
                    try:
                        stage_num = int(btn_id[2:])  # "et10" -> 10
                        max_stage = max(max_stage, stage_num)
                    except ValueError:
                        continue
            return max_stage

        # Alternatif: "Etap-X" metinlerini ara
        all_text = soup.get_text()
        import re
        etap_matches = re.findall(r'Etap[- ](\d+)', all_text, re.IGNORECASE)
        if etap_matches:
            return max([int(m) for m in etap_matches])

        return 0

    def _find_stage_links_in_page(self, soup: BeautifulSoup, rally_id: int) -> List[str]:
        """Sayfadaki etap linklerini bul (eğer varsa)"""
        stage_links = []

        # Linkler genelde: /yaris/{rally_id}/{etap_no}/ralli_etap_sonuclari_print/
        all_links = soup.find_all('a', href=True)

        for link in all_links:
            href = link['href']

            # Etap sonuç linki mi kontrol et
            if 'ralli_etap_sonuclari_print' in href or 'etap_sonuclari' in href:
                if str(rally_id) in href and href.count('/') > 3:  # Etap numarası var mı
                    full_url = href if href.startswith('http') else f"{self.BASE_URL}{href}"
                    if full_url not in stage_links:
                        stage_links.append(full_url)

        return sorted(stage_links)

    def _fetch_single_stage(self, url: str, stage_number: int) -> Optional[Dict]:
        """Tek bir etap sayfasını çek"""
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            # Table'ı bul
            table = soup.find('table')
            if not table:
                return None

            stage_data = self._parse_stage_table(table)
            if stage_data:
                stage_data['stage_number'] = stage_number

            return stage_data

        except Exception as e:
            logger.warning(f"Error fetching stage {url}: {e}")
            return None

    def _fetch_from_print_page(self, url: str, rally_id: int, rally_name: str) -> Optional[Dict]:
        """Eski metot - print sayfasından tüm etapları çek"""
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            # Find all tables (each table is a stage)
            tables = soup.find_all('table')

            stages = []
            for table in tables:
                stage_data = self._parse_stage_table(table)
                if stage_data:
                    stages.append(stage_data)

            return {
                'rally_id': rally_id,
                'rally_name': rally_name,
                'stages': stages
            }

        except Exception as e:
            logger.error(f"Error fetching print page {url}: {e}")
            return None

    def scrape_multiple_rallies(self, rally_ids: list) -> Dict:
        """Scrape multiple rallies and collect statistics"""
        stats = {
            'total_checked': 0,
            'rally_found': 0,
            'baja_skipped': 0,
            'offroad_skipped': 0,
            'not_found': 0,
            'error': 0,
            'rally_details': []
        }

        all_rallies = []

        for rally_id in rally_ids:
            stats['total_checked'] += 1

            try:
                rally_data = self.fetch_rally_stages(rally_id)

                if rally_data is None:
                    # Skipped due to category filter
                    continue

                stats['rally_found'] += 1
                stats['rally_details'].append({
                    'id': rally_id,
                    'name': rally_data['rally_name'],
                    'stages': len(rally_data['stages'])
                })

                all_rallies.append(rally_data)

            except requests.RequestException as e:
                if '404' in str(e):
                    stats['not_found'] += 1
                else:
                    stats['error'] += 1
                    logger.error(f"Rally {rally_id} error: {e}")
                continue
            except Exception as e:
                stats['error'] += 1
                logger.error(f"Rally {rally_id} unexpected error: {e}")
                continue

        return {
            'rallies': all_rallies,
            'stats': stats
        }

    def _extract_rally_name(self, soup: BeautifulSoup) -> str:
        """Extract rally name from page"""
        # Try to find title in h1, h2, or page title
        title_tag = soup.find('h1') or soup.find('h2')
        if title_tag:
            return title_tag.text.strip()

        page_title = soup.find('title')
        if page_title:
            return page_title.text.strip()

        return "Unknown Rally"

    def _is_rally_category(self, rally_name: str, soup: BeautifulSoup) -> bool:
        """
        Check if the event is a real rally (not Baja/Offroad)

        Skip categories:
        - Baja (Turkey Baja Championship)
        - Offroad (Offroad Championship)
        - Cross Country

        Accept:
        - Rally
        - Turkey Rally Championship
        - FIA Rally
        """
        rally_name_lower = rally_name.lower()

        # Categories to skip
        exclude_keywords = [
            'baja',
            'off-road',
            'offroad',
            'cross country',
            'autocross',
            'slalom'
        ]

        for keyword in exclude_keywords:
            if keyword in rally_name_lower:
                return False

        # Categories to accept
        include_keywords = [
            'ralli',
            'rally',
            'türkiye ralli şampiyonası',
            'fia rally'
        ]

        for keyword in include_keywords:
            if keyword in rally_name_lower:
                return True

        # Additional check: look at category tag on page
        category_tag = soup.find('span', class_='category') or soup.find('div', class_='category')
        if category_tag:
            category_text = category_tag.text.lower()
            if 'ralli' in category_text or 'rally' in category_text:
                return True
            if 'baja' in category_text or 'offroad' in category_text:
                return False

        # For uncertain cases: check number of stages
        # Rallies typically have 8+ stages, Baja has 2-4
        tables = soup.find_all('table')
        if len(tables) >= 6:  # 6+ stages likely means rally
            logger.info(f"  [INFO] Accepted as rally based on stage count ({len(tables)} stages)")
            return True

        # Default: skip if uncertain
        logger.warning(f"  [WARN] Uncertain category: {rally_name}")
        return False

    def _parse_stage_table(self, table) -> Optional[Dict]:
        """Parse a single stage results table"""
        try:
            # Get stage name from the row before the table or first row
            stage_name = "Unknown Stage"
            stage_number = 0
            stage_length_km = 0.0

            # Look for stage header (usually in a tr before the header row)
            prev_sibling = table.find_previous_sibling()
            if prev_sibling and prev_sibling.name == 'tr':
                stage_header = prev_sibling.get_text(strip=True)
                stage_name, stage_number, stage_length_km = self._parse_stage_header(stage_header)
            else:
                # Try first row of table
                first_row = table.find('tr')
                if first_row:
                    first_cell = first_row.find(['td', 'th'])
                    if first_cell and 'ÖE' in first_cell.text:
                        stage_header = first_cell.get_text(strip=True)
                        stage_name, stage_number, stage_length_km = self._parse_stage_header(stage_header)

            # Parse results
            results = []
            rows = table.find_all('tr')

            # Skip header rows
            data_rows = []
            for row in rows:
                cells = row.find_all(['td', 'th'])
                if cells and len(cells) >= 6:
                    # Check if it's a header row
                    first_cell_text = cells[0].get_text(strip=True)
                    if first_cell_text.lower() not in ['sıra', 'stage', 'no', 'öe']:
                        data_rows.append(row)

            for row in data_rows:
                result = self._parse_result_row(row)
                if result:
                    results.append(result)

            if not results:
                return None

            return {
                'stage_name': stage_name,
                'stage_number': stage_number,
                'stage_length_km': stage_length_km,
                'results': results
            }

        except Exception as e:
            logger.warning(f"Error parsing stage table: {e}")
            return None

    def _parse_stage_header(self, header_text: str) -> tuple:
        """Parse stage header to extract name, number and length"""
        # Format: "ÖE1 - SSS MARMARİS - 1.85km"
        stage_name = header_text
        stage_number = 0
        stage_length = 0.0

        # Extract stage number (ÖE1, ÖE2, etc.)
        stage_num_match = re.search(r'ÖE\s*(\d+)', header_text, re.IGNORECASE)
        if stage_num_match:
            stage_number = int(stage_num_match.group(1))

        # Extract length
        length_match = re.search(r'(\d+\.?\d*)\s*km', header_text, re.IGNORECASE)
        if length_match:
            stage_length = float(length_match.group(1))

        return stage_name, stage_number, stage_length

    def _parse_result_row(self, row) -> Optional[Dict]:
        """Parse a single result row"""
        try:
            cells = row.find_all(['td', 'th'])

            if len(cells) < 6:
                return None

            # Extract data
            position = cells[0].get_text(strip=True)
            car_number = cells[1].get_text(strip=True)

            # Pilot/Co-Pilot (may have multiple lines)
            pilots_text = cells[2].get_text(separator='\n', strip=True)
            pilot_lines = [line.strip() for line in pilots_text.split('\n') if line.strip()]
            driver_name = pilot_lines[0] if pilot_lines else ""

            # Nationality
            nationality = cells[3].get_text(strip=True)

            # Class
            car_class = cells[4].get_text(strip=True)

            # Team/Car
            team_car_text = cells[5].get_text(separator='\n', strip=True)
            team_car_lines = [line.strip() for line in team_car_text.split('\n') if line.strip()]
            team = team_car_lines[0] if len(team_car_lines) > 0 else ""
            car_model = team_car_lines[1] if len(team_car_lines) > 1 else ""

            # Time/Speed
            time_speed_text = cells[6].get_text(separator='\n', strip=True)
            time_speed_lines = [line.strip() for line in time_speed_text.split('\n') if line.strip()]
            time_str = time_speed_lines[0] if time_speed_lines else ""

            # Time difference (if exists)
            time_diff = ""
            if len(cells) > 7:
                time_diff = cells[7].get_text(strip=True)

            # Determine status based on time string
            status = "OK"
            if not time_str or time_str.upper() in ['DNF', 'DNS', 'DSQ', 'RET', 'N/A', '—']:
                status = time_str.upper() if time_str else "DNS"

            return {
                'position': position,
                'car_number': car_number,
                'driver_name': driver_name,
                'nationality': nationality,
                'car_class': car_class,
                'team': team,
                'car_model': car_model,
                'time_str': time_str,
                'time_diff': time_diff,
                'status': status
            }

        except Exception as e:
            logger.warning(f"Error parsing result row: {e}")
            return None

    def _init_selenium_driver(self):
        """Initialize Selenium WebDriver with headless Chrome"""
        if self.driver:
            return

        try:
            chrome_options = Options()
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--window-size=1920,1080')
            chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')

            # Disable logging
            chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])

            # Use webdriver-manager to auto-download ChromeDriver
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            logger.info("Selenium WebDriver initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Selenium: {e}")
            raise

    def _close_selenium_driver(self):
        """Close Selenium WebDriver"""
        if self.driver:
            try:
                self.driver.quit()
                self.driver = None
                logger.info("Selenium WebDriver closed")
            except Exception as e:
                logger.warning(f"Error closing Selenium: {e}")

    def _fetch_rally_stages_selenium(self, rally_id: int) -> Optional[Dict]:
        """Fetch all stage results using Selenium (full data)"""
        try:
            self._init_selenium_driver()

            url = f"{self.BASE_URL}/yaris/{rally_id}/ralli_etap_sonuclari_print/"
            logger.info(f"[SELENIUM] Fetching rally {rally_id} from {url}")

            self.driver.get(url)

            # Wait for page to load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "table"))
            )

            # Get rally name from title or heading
            try:
                page_source = self.driver.page_source
                soup = BeautifulSoup(page_source, 'html.parser')
                rally_name = self._extract_rally_name(soup)

                # Category check
                if not self._is_rally_category(rally_name, soup):
                    logger.info(f"[SKIP] Rally {rally_id} - Category: {rally_name}")
                    return None

                logger.info(f"[OK] Rally {rally_id} - {rally_name}")
            except Exception as e:
                logger.warning(f"Error extracting rally name: {e}")
                rally_name = f"Rally {rally_id}"

            # Find all stage buttons (et1, et2, et3, ...)
            stage_buttons = self.driver.find_elements(By.CSS_SELECTOR, "a[id^='et']")
            stage_count = len(stage_buttons)

            if stage_count == 0:
                logger.warning(f"No stage buttons found for rally {rally_id}")
                # Fallback to static parsing
                return self._fetch_rally_stages_static(rally_id)

            logger.info(f"  Found {stage_count} stage buttons")

            stages = []

            # Click each button by ID (to avoid stale element)
            for i in range(1, stage_count + 1):
                try:
                    logger.info(f"  [STAGE {i}] Clicking button et{i}...")

                    # Find button by ID fresh each time
                    button = self.driver.find_element(By.ID, f"et{i}")

                    # Scroll button into view
                    self.driver.execute_script("arguments[0].scrollIntoView(true);", button)
                    time.sleep(0.3)

                    # Click button
                    button.click()

                    # Wait for table to update
                    time.sleep(1.5)

                    # Get page source and parse
                    page_source = self.driver.page_source
                    soup = BeautifulSoup(page_source, 'html.parser')

                    # Find the visible table
                    table = soup.find('table')
                    if table:
                        stage_data = self._parse_stage_table(table)
                        if stage_data and len(stage_data.get('results', [])) > 0:
                            stage_data['stage_number'] = i
                            stages.append(stage_data)
                            logger.info(f"  [STAGE {i}] Fetched {len(stage_data['results'])} results")
                        else:
                            logger.warning(f"  [STAGE {i}] No results found")
                    else:
                        logger.warning(f"  [STAGE {i}] No table found")

                except NoSuchElementException:
                    logger.warning(f"  [STAGE {i}] Button not found")
                    break
                except Exception as e:
                    logger.warning(f"  [STAGE {i}] Error: {e}")
                    continue

            logger.info(f"  [TOTAL] {len(stages)} stages fetched with Selenium")

            return {
                'rally_id': rally_id,
                'rally_name': rally_name,
                'stages': stages
            }

        except Exception as e:
            logger.error(f"Error in Selenium scraping: {e}")
            # Fallback to static method
            logger.info("Falling back to static HTML parsing")
            return self._fetch_rally_stages_static(rally_id)
        finally:
            self._close_selenium_driver()


def parse_html(html: str) -> pd.DataFrame:
    """
    Parse a TOSFED rally results HTML string into a DataFrame.

    This is a pure parsing helper that reuses the scraper's HTML parsers without
    performing any HTTP requests or Selenium calls.
    """
    scraper = TOSFEDSonucScraper(use_selenium=False)
    soup = BeautifulSoup(html, 'html.parser')

    rally_name = scraper._extract_rally_name(soup)
    tables = soup.find_all('table')

    stages = []
    for table in tables:
        stage_data = scraper._parse_stage_table(table)
        if stage_data:
            stages.append(stage_data)

    rows = []
    for idx, stage in enumerate(stages, start=1):
        stage_number = stage.get('stage_number') or idx
        for result in stage.get('results', []):
            rows.append({
                'rally_name': rally_name,
                'stage_name': stage.get('stage_name'),
                'stage_number': stage_number,
                'stage_length_km': stage.get('stage_length_km'),
                'position': result.get('position'),
                'car_number': result.get('car_number'),
                'driver_name': result.get('driver_name'),
                'nationality': result.get('nationality'),
                'car_class': result.get('car_class'),
                'team': result.get('team'),
                'car_model': result.get('car_model'),
                'time_str': result.get('time_str'),
                'time_diff': result.get('time_diff'),
                'status': result.get('status')
            })

    return pd.DataFrame(rows)
