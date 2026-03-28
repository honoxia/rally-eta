"""TOSFED Rally Results Scraper"""
import requests
from bs4 import BeautifulSoup
from typing import Dict, List, Optional
import logging
import re
import time
import json
import os
import pandas as pd

logger = logging.getLogger(__name__)

class TOSFEDSonucScraper:
    """Scraper for TOSFED rally results"""

    BASE_URLS = [
        "https://sonuc.tosfed.org.tr",
        "https://tosfedsonuc.com",
    ]
    METADATA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "rally_surface_metadata.json")

    def __init__(self, use_selenium=False):
        # Selenium is deprecated in this version in favor of direct URL iteration
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        self.surface_metadata = self._load_surface_metadata()

    def _load_surface_metadata(self) -> Dict:
        """Load rally surface metadata from JSON"""
        try:
            if os.path.exists(self.METADATA_PATH):
                with open(self.METADATA_PATH, 'r', encoding='utf-8') as f:
                    return json.load(f)
            else:
                logger.warning(f"Surface metadata not found at {self.METADATA_PATH}")
                return {"surface_mappings": {}, "default_surface": "gravel"}
        except Exception as e:
            logger.error(f"Error loading surface metadata: {e}")
            return {"surface_mappings": {}, "default_surface": "gravel"}

    def _determine_surface(self, rally_name: str) -> str:
        """Determine surface type based on rally name"""
        rally_name_lower = rally_name.lower()
        mappings = self.surface_metadata.get("surface_mappings", {})
        
        for key, surface in mappings.items():
            if key in rally_name_lower:
                return surface
                
        return self.surface_metadata.get("default_surface", "gravel")

    def fetch_rally_stages(self, rally_id: int) -> Optional[Dict]:
        """Fetch all stage results for a rally using robust URL iteration"""
        
        # 1. Get Rally Info (Name, Date, etc.) from the main page
        base_url = None
        soup = None
        for host in self.BASE_URLS:
            for path in ["ralli_etap_sonuclari_print", "ralli_etap_sonuclari"]:
                candidate = f"{host}/yaris/{rally_id}/{path}/"
                logger.info(f"Fetching rally {rally_id} info from {candidate}")
                try:
                    response = self.session.get(candidate, timeout=30)
                    if response.status_code != 200:
                        continue
                    soup = BeautifulSoup(response.content, 'html.parser')
                    base_url = candidate
                    break
                except requests.RequestException:
                    continue
            if base_url:
                break

        if not base_url or not soup:
            logger.error(f"Error fetching rally {rally_id}: no valid base URL")
            return None

        try:
            rally_name = self._extract_rally_name(soup)
            
            # Category Check
            if not self._is_rally_category(rally_name, soup):
                logger.info(f"[SKIP] Rally {rally_id} - Category: {rally_name}")
                return None
                
            surface = self._determine_surface(rally_name)
            logger.info(f"[OK] Rally {rally_id} - {rally_name} ({surface})")
            
            # 2. Iterate through stages (etp=1, etp=2, ...)
            stages = []
            empty_streak = 0
            max_empty_streak = 3 # Stop after 3 consecutive empty pages
            
            # Try to find max stage from buttons if possible, otherwise just loop
            max_stage_est = self._count_stages(soup)
            loop_limit = max(20, max_stage_est + 5) # Safety limit
            
            for stage_num in range(1, loop_limit + 1):
                stage_url = f"{base_url}?etp={stage_num}"
                logger.info(f"  Fetching Stage {stage_num}...")
                
                stage_data = self._fetch_single_stage_content(stage_url, stage_num)
                
                if stage_data:
                    stage_data['surface'] = surface # Add surface info
                    stages.append(stage_data)
                    empty_streak = 0
                    logger.info(f"    -> Found {len(stage_data['results'])} results for {stage_data['stage_name']}")
                else:
                    empty_streak += 1
                    logger.info(f"    -> No data for stage {stage_num}")
                    
                    # If we estimated max stages and passed it, stop sooner
                    if max_stage_est > 0 and stage_num > max_stage_est:
                        break
                        
                    if empty_streak >= max_empty_streak:
                        logger.info(f"  Stopping after {max_empty_streak} empty responses")
                        break
            
            if not stages:
                logger.warning(f"  No stages found for rally {rally_id}")
                return None
                
            return {
                'rally_id': rally_id,
                'rally_name': rally_name,
                'surface': surface,
                'stages': stages
            }

        except requests.RequestException as e:
            logger.error(f"Error fetching rally {rally_id}: {e}")
            return None

    def _fetch_single_stage_content(self, url: str, stage_number: int) -> Optional[Dict]:
        """Fetch and parse a single stage page"""
        try:
            response = self.session.get(url, timeout=20)
            if response.status_code != 200:
                return None
                
            soup = BeautifulSoup(response.content, 'html.parser')
            table = self._select_results_table(soup)
            if not table:
                return None
                
            # Parse the table
            stage_data = self._parse_stage_table(table)
            
            if stage_data and stage_data.get('results'):
                stage_data['stage_number'] = stage_number
                return stage_data
                
            return None
            
        except Exception as e:
            logger.warning(f"Error fetching stage {url}: {e}")
            return None

    def _select_results_table(self, soup: BeautifulSoup):
        """Select the most likely results table from the page."""
        tables = soup.find_all('table')
        if not tables:
            return None

        def score_table(table):
            rows = table.find_all('tr')
            score = 0
            for row in rows:
                cells = row.find_all(['td', 'th'])
                if len(cells) >= 6:
                    score += 1
            return score

        tables.sort(key=score_table, reverse=True)
        return tables[0] if score_table(tables[0]) > 0 else None

    def _extract_rally_name(self, soup: BeautifulSoup) -> str:
        """Extract rally name from page"""
        title_tag = soup.find('h1') or soup.find('h2')
        if title_tag:
            return title_tag.text.strip()

        page_title = soup.find('title')
        if page_title:
            return page_title.text.strip()

        return "Unknown Rally"

    def _is_rally_category(self, rally_name: str, soup: BeautifulSoup) -> bool:
        """Check if the event is a real rally"""
        rally_name_lower = rally_name.lower()
        
        exclude_keywords = ['baja', 'off-road', 'offroad', 'cross country', 'autocross', 'slalom', 'tırmanma']
        for keyword in exclude_keywords:
            if keyword in rally_name_lower:
                return False

        include_keywords = ['ralli', 'rally', 'türkiye ralli şampiyonası', 'fia rally']
        for keyword in include_keywords:
            if keyword in rally_name_lower:
                return True
                
        # Check category tag
        category_tag = soup.find('span', class_='category') or soup.find('div', class_='category')
        if category_tag:
            category_text = category_tag.text.lower()
            if 'ralli' in category_text or 'rally' in category_text:
                return True
            if 'baja' in category_text or 'offroad' in category_text:
                return False

        # Stage count heuristic
        tables = soup.find_all('table')
        if len(tables) >= 6:
            return True

        return False

    def _count_stages(self, soup: BeautifulSoup) -> int:
        """Estimate total stages from buttons"""
        stage_buttons = soup.find_all('a', id=lambda x: x and x.startswith('et'))
        max_stage = 0
        if stage_buttons:
            for button in stage_buttons:
                btn_id = button.get('id', '')
                if btn_id.startswith('et'):
                    try:
                        stage_num = int(btn_id[2:])
                        max_stage = max(max_stage, stage_num)
                    except ValueError:
                        continue
        return max_stage

    def _parse_stage_table(self, table) -> Optional[Dict]:
        """Parse a single stage results table"""
        try:
            stage_name = "Unknown Stage"
            stage_number = 0
            stage_length_km = 0.0

            # Look for stage header
            # Strategy 1: Previous Sibling
            prev_sibling = table.find_previous_sibling()
            if prev_sibling and prev_sibling.name == 'tr': # Sometimes header is in a separate TR
                 stage_header = prev_sibling.get_text(strip=True)
                 stage_name, stage_number, stage_length_km = self._parse_stage_header(stage_header)
            
            # Strategy 2: First Row of Table
            if stage_name == "Unknown Stage":
                first_row = table.find('tr')
                if first_row:
                    first_cell = first_row.find(['td', 'th'])
                    if first_cell and ('ÖE' in first_cell.text or 'SS' in first_cell.text):
                        stage_header = first_cell.get_text(strip=True)
                        stage_name, stage_number, stage_length_km = self._parse_stage_header(stage_header)

            results = []
            rows = table.find_all('tr')
            
            # Skip header rows
            data_rows = []
            for row in rows:
                cells = row.find_all(['td', 'th'])
                if cells and len(cells) >= 6:
                    first_cell_text = cells[0].get_text(strip=True)
                    # Skip header rows
                    if first_cell_text.lower() in ['sıra', 'stage', 'no', 'öe', 'pos']:
                        continue
                    # Skip rows that are clearly not results (e.g. SR headers inside table)
                    if "SR" in cells[1].get_text(strip=True):
                         continue
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
        stage_name = header_text
        stage_number = 0
        stage_length = 0.0

        # Extract stage number (ÖE1, SS1, etc.)
        stage_num_match = re.search(r'(?:ÖE|SS)\s*(\d+)', header_text, re.IGNORECASE)
        if stage_num_match:
            stage_number = int(stage_num_match.group(1))

        # Extract length (hem nokta hem virgul destegi: 8.25km veya 8,25km)
        length_match = re.search(r'(\d+[,.]?\d*)\s*km', header_text, re.IGNORECASE)
        if length_match:
            stage_length = float(length_match.group(1).replace(',', '.'))

        return stage_name, stage_number, stage_length

    def _parse_result_row(self, row) -> Optional[Dict]:
        """Parse a single result row"""
        try:
            cells = row.find_all(['td', 'th'])
            if len(cells) < 6:
                return None

            position = cells[0].get_text(strip=True)
            car_number = cells[1].get_text(strip=True)

            pilots_text = cells[2].get_text(separator='\n', strip=True)
            pilot_lines = [line.strip() for line in pilots_text.split('\n') if line.strip()]
            driver_name = pilot_lines[0] if pilot_lines else ""

            nationality = cells[3].get_text(strip=True)
            car_class = cells[4].get_text(strip=True)

            team_car_text = cells[5].get_text(separator='\n', strip=True)
            team_car_lines = [line.strip() for line in team_car_text.split('\n') if line.strip()]
            team = team_car_lines[0] if len(team_car_lines) > 0 else ""
            car_model = team_car_lines[1] if len(team_car_lines) > 1 else ""

            time_speed_text = cells[6].get_text(separator='\n', strip=True)
            time_speed_lines = [line.strip() for line in time_speed_text.split('\n') if line.strip()]
            time_str = time_speed_lines[0] if time_speed_lines else ""

            time_diff = ""
            if len(cells) > 7:
                time_diff = cells[7].get_text(strip=True)

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

    def fetch_rally_from_url(self, url: str) -> Optional[Dict]:
        """TOSFED URL'sinden rally_id cikar ve veri cek.

        Desteklenen URL formatlari:
            https://sonuc.tosfed.org.tr/yaris/171/ralli_etap_sonuclari/?etp=7
            https://tosfedsonuc.com/yaris/171/ralli_etap_sonuclari/
            https://tosfedsonuc.com/yaris/171/

        Returns:
            {
                'rally_id': 171,
                'rally_name': '...',
                'surface': '...',
                'stages': [...],
                'suggested_stage': 7  # etp parametresinden (varsa)
            }
        """
        # URL'den rally_id cikar
        rally_id_match = re.search(r'/yaris/(\d+)', url)
        if not rally_id_match:
            logger.error(f"URL'den rally_id cikarildi: {url}")
            return None

        rally_id = int(rally_id_match.group(1))

        # etp parametresinden tahmini etap numarasi cikar (opsiyonel)
        etp_match = re.search(r'[?&]etp=(\d+)', url)
        suggested_stage = int(etp_match.group(1)) if etp_match else None

        # Mevcut fetch_rally_stages ile veri cek
        result = self.fetch_rally_stages(rally_id)

        if result and suggested_stage is not None:
            result['suggested_stage'] = suggested_stage

        return result

    def scrape_multiple_rallies(self, rally_ids: list) -> Dict:
        """Scrape multiple rallies"""
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
                    continue

                stats['rally_found'] += 1
                stats['rally_details'].append({
                    'id': rally_id,
                    'name': rally_data['rally_name'],
                    'stages': len(rally_data['stages'])
                })
                all_rallies.append(rally_data)

            except Exception as e:
                logger.error(f"Rally {rally_id} error: {e}")
                stats['error'] += 1
                continue

        return {
            'rallies': all_rallies,
            'stats': stats
        }
