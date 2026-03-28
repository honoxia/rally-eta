"""
TOSFED Start Listesi Parser
Start listesi sayfasindan pilot bilgilerini ceker.
URL format: https://tosfedsonuc.com/yaris/{rally_id}/1/startlist_ralli_gun1_print/
"""

import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Optional
import logging
import re
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

logger = logging.getLogger(__name__)


class StartlistParser:
    """TOSFED start listesi sayfasindan pilot bilgilerini parse eder."""

    BASE_URLS = [
        "https://tosfedsonuc.com",
        "https://sonuc.tosfed.org.tr",
    ]

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/120.0.0.0 Safari/537.36'
        })

    def fetch_startlist_from_url(self, url: str) -> Optional[Dict]:
        """Verilen URL'den start listesini ceker.

        Args:
            url: TOSFED start listesi URL'si
                 Ornek: https://tosfedsonuc.com/yaris/171/1/startlist_ralli_gun1_print/

        Returns:
            {
                'rally_id': int,
                'rally_name': str,
                'gun': int,  # 1 veya 2
                'pilots': [
                    {
                        'car_number': int,
                        'driver_name': str,
                        'co_driver_name': str,
                        'nationality': str,
                        'car_class': str,
                        'normalized_class': str,
                        'vehicle': str,
                        'team': str,
                        'start_time': str,
                        'championship': str,
                    }, ...
                ]
            }
        """
        try:
            # URL'den rally_id ve gun bilgisi cikar
            rally_id, gun = self._parse_url(url)
            if not rally_id:
                logger.error(f"URL'den rally_id cikarilaamdi: {url}")
                return None

            # Sayfayi cek
            response = self.session.get(url, timeout=30)
            if response.status_code != 200:
                logger.error(f"HTTP {response.status_code}: {url}")
                return None

            soup = BeautifulSoup(response.content, 'html.parser')

            # Ralli adini cikar
            rally_name = self._extract_rally_name(soup)

            # Tabloyu parse et
            pilots = self._parse_startlist_table(soup)

            if not pilots:
                logger.warning(f"Start listesinde pilot bulunamadi: {url}")
                return None

            # Sinif normalizasyonu
            self._normalize_classes(pilots)

            return {
                'rally_id': rally_id,
                'rally_name': rally_name,
                'gun': gun,
                'pilots': pilots,
            }

        except Exception as e:
            logger.error(f"Start listesi parse hatasi: {e}")
            return None

    def fetch_startlist_by_rally_id(self, rally_id: int, gun: int = 1) -> Optional[Dict]:
        """Rally ID ile start listesini ceker. Birden fazla URL dener."""
        url_patterns = [
            f"/yaris/{rally_id}/{gun}/startlist_ralli_gun{gun}_print/",
            f"/yaris/{rally_id}/{gun}/startlist_ralli_gun{gun}/",
            f"/yaris/{rally_id}/startlist_ralli_gun{gun}_print/",
        ]

        for base in self.BASE_URLS:
            for pattern in url_patterns:
                url = base + pattern
                logger.info(f"Deneniyor: {url}")
                result = self.fetch_startlist_from_url(url)
                if result:
                    return result

        logger.error(f"Start listesi bulunamadi: rally_id={rally_id}, gun={gun}")
        return None

    def _parse_url(self, url: str) -> tuple:
        """URL'den rally_id ve gun bilgisi cikar."""
        rally_match = re.search(r'/yaris/(\d+)', url)
        rally_id = int(rally_match.group(1)) if rally_match else None

        gun_match = re.search(r'gun(\d+)', url)
        gun = int(gun_match.group(1)) if gun_match else 1

        return rally_id, gun

    def _extract_rally_name(self, soup: BeautifulSoup) -> str:
        """Sayfa basligindan ralli adini cikar."""
        # h1 veya h2 tag'inde ralli adi
        for tag in ['h1', 'h2', 'h3']:
            header = soup.find(tag)
            if header:
                text = header.get_text(strip=True)
                # "Start Listesi" kismini temizle
                text = re.sub(r'\s*-?\s*Start\s*List.*$', '', text, flags=re.IGNORECASE)
                text = re.sub(r'\s*-?\s*Baslangic\s*List.*$', '', text, flags=re.IGNORECASE)
                if text:
                    return text.strip()

        title = soup.find('title')
        if title:
            return title.get_text(strip=True)

        return "Bilinmeyen Ralli"

    def _parse_startlist_table(self, soup: BeautifulSoup) -> List[Dict]:
        """Start listesi tablosunu parse et."""
        pilots = []

        # En uygun tabloyu bul
        table = self._find_startlist_table(soup)
        if not table:
            logger.warning("Start listesi tablosu bulunamadi")
            return pilots

        rows = table.find_all('tr')

        # Header satirini tespit et
        header_map = {}
        header_row = None
        for row in rows:
            cells = row.find_all(['th', 'td'])
            cell_texts = [c.get_text(strip=True).lower() for c in cells]

            # Header tespiti: "no" veya "pilot" iceren satir
            if any(kw in ' '.join(cell_texts) for kw in ['no', 'pilot', 'sıra']):
                header_map = self._build_header_map(cell_texts)
                header_row = row
                break

        # Header bulunamazsa varsayilan siralama kullan
        # TOSFED standart: Sira, No, Yarismaci, Pilot, Co-Pilot, Uyruk, Otomobil, S/K, Sampiyona, S.Zamani
        if not header_map:
            header_map = {
                'sira': 0, 'no': 1, 'yarismaci': 2, 'pilot': 3,
                'copilot': 4, 'uyruk': 5, 'otomobil': 6,
                'sinif': 7, 'sampiyona': 8, 'saat': 9,
            }

        # Veri satirlarini parse et
        data_started = header_row is not None
        for row in rows:
            if row == header_row:
                data_started = True
                continue
            if not data_started:
                continue

            cells = row.find_all(['td', 'th'])
            if len(cells) < 6:
                continue

            pilot = self._parse_pilot_row(cells, header_map)
            if pilot and pilot.get('car_number'):
                pilots.append(pilot)

        return pilots

    def _find_startlist_table(self, soup: BeautifulSoup):
        """En uygun start listesi tablosunu bul."""
        tables = soup.find_all('table')
        if not tables:
            return None

        # En cok satiri olan tabloyu sec (start listesi genelde en buyuk tablo)
        def score_table(tbl):
            rows = tbl.find_all('tr')
            score = 0
            for r in rows:
                cells = r.find_all(['td', 'th'])
                if len(cells) >= 6:
                    score += 1
            return score

        tables_sorted = sorted(tables, key=score_table, reverse=True)
        best = tables_sorted[0] if tables_sorted else None
        return best if best and score_table(best) > 2 else None

    def _build_header_map(self, cell_texts: List[str]) -> Dict:
        """Header hucre metinlerinden kolon indeks haritasi olustur."""
        hmap = {}
        for i, text in enumerate(cell_texts):
            text = text.strip().lower()
            if text in ['sıra', 'sira', '#']:
                hmap['sira'] = i
            elif text in ['no', 'no.']:
                hmap['no'] = i
            elif text in ['yarışmacı', 'yarismaci', 'takım', 'takim', 'team']:
                hmap['yarismaci'] = i
            elif text in ['pilot', 'sürücü', 'surucu', 'driver']:
                hmap['pilot'] = i
            elif 'co' in text or 'yardımcı' in text or 'navigator' in text:
                hmap['copilot'] = i
            elif text in ['uyruk', 'ülke', 'ulke', 'nat']:
                hmap['uyruk'] = i
            elif text in ['otomobil', 'araç', 'arac', 'car', 'vehicle']:
                hmap['otomobil'] = i
            elif text in ['s/k', 'sınıf', 'sinif', 'class', 'kat']:
                hmap['sinif'] = i
            elif text in ['şampiyona', 'sampiyona', 'champ', 'championship']:
                hmap['sampiyona'] = i
            elif text in ['s.zamanı', 's.zamani', 'saat', 'time', 'start']:
                hmap['saat'] = i
        return hmap

    def _parse_pilot_row(self, cells, header_map: Dict) -> Optional[Dict]:
        """Tek bir pilot satirini parse et."""
        try:
            def get_cell(key, default=''):
                idx = header_map.get(key)
                if idx is not None and idx < len(cells):
                    return cells[idx].get_text(strip=True)
                return default

            car_number_str = get_cell('no')
            # Sayi olmayan karakterleri temizle
            car_number_clean = re.sub(r'[^\d]', '', car_number_str)
            if not car_number_clean:
                return None
            car_number = int(car_number_clean)

            # Pilot - bazen isim ve bayrak ayni hucrede
            pilot_cell_idx = header_map.get('pilot')
            driver_name = ''
            if pilot_cell_idx is not None and pilot_cell_idx < len(cells):
                pilot_cell = cells[pilot_cell_idx]
                # img tag'lerini kaldir (bayrak ikonlari)
                for img in pilot_cell.find_all('img'):
                    img.decompose()
                driver_name = pilot_cell.get_text(strip=True)
                # Birden fazla isim varsa (satir ici) ilkini al
                lines = [l.strip() for l in driver_name.split('\n') if l.strip()]
                driver_name = lines[0] if lines else driver_name

            # Co-pilot
            copilot_cell_idx = header_map.get('copilot')
            co_driver_name = ''
            if copilot_cell_idx is not None and copilot_cell_idx < len(cells):
                copilot_cell = cells[copilot_cell_idx]
                for img in copilot_cell.find_all('img'):
                    img.decompose()
                co_driver_name = copilot_cell.get_text(strip=True)
                lines = [l.strip() for l in co_driver_name.split('\n') if l.strip()]
                co_driver_name = lines[0] if lines else co_driver_name

            # Otomobil - bazen takim ve arac ayni hucrede
            vehicle = get_cell('otomobil')

            # Sinif
            car_class = get_cell('sinif')

            # Diger alanlar
            team = get_cell('yarismaci')
            nationality = get_cell('uyruk')
            start_time = get_cell('saat')
            championship = get_cell('sampiyona')

            return {
                'car_number': car_number,
                'driver_name': driver_name,
                'co_driver_name': co_driver_name,
                'nationality': nationality,
                'car_class': car_class,
                'normalized_class': '',  # _normalize_classes'ta doldurulacak
                'vehicle': vehicle,
                'team': team,
                'start_time': start_time,
                'championship': championship,
            }

        except Exception as e:
            logger.warning(f"Pilot satiri parse hatasi: {e}")
            return None

    def _normalize_classes(self, pilots: List[Dict]):
        """Sinif kodlarini normalize et."""
        try:
            from src.data.car_class_normalizer import CarClassNormalizer
            normalizer = CarClassNormalizer()
            for pilot in pilots:
                raw_class = pilot.get('car_class', '')
                pilot['normalized_class'] = normalizer.normalize(raw_class)
        except ImportError:
            logger.warning("CarClassNormalizer bulunamadi, ham sinif kullaniliyor")
            for pilot in pilots:
                pilot['normalized_class'] = pilot.get('car_class', '')
