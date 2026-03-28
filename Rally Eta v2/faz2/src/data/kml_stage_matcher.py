"""
KML-Stage Matcher - Otomatik ve manuel KML-Stage eslestirme.

Fuzzy matching ile KML dosya adlarini veritabanindaki
rally/stage kayitlariyla eslestirir.
"""
import sqlite3
import re
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    """KML-Stage eslestirme sonucu."""
    kml_file: str
    kml_name: str
    matched_rally_id: Optional[str]
    matched_rally_name: Optional[str]
    matched_stages: List[Dict]
    confidence: float  # 0-1
    match_type: str  # 'exact', 'fuzzy', 'manual', 'none'


class KMLStageMatcher:
    """
    KML dosyalarini veritabanindaki etaplarla eslestirir.

    Eslestirme stratejisi:
    1. Exact match (dosya adi = rally adi)
    2. Fuzzy match (benzerlik skoru)
    3. Manuel eslestirme (kullanici secimi)
    """

    # Rally adi normalizasyon patterns
    NORMALIZE_PATTERNS = [
        (r'\d{4}', ''),  # Yil kaldir
        (r'rallisi?', 'rally', re.IGNORECASE),
        (r'günü?|gun|day', '', re.IGNORECASE),
        (r'\d+\.\s*', ''),  # "1. " gibi numaralari kaldir
        (r'[_\-\+]+', ' '),  # _ - + -> space
        (r'\s+', ' '),  # Multiple spaces
        (r'\.kml|\.kmz', '', re.IGNORECASE),
    ]

    def __init__(self, db_path: str):
        """
        Initialize matcher.

        Args:
            db_path: Veritabani yolu
        """
        self.db_path = db_path
        self._rally_cache = None
        self._stage_cache = None
        self._stage_results_columns = None

    def _get_stage_results_columns(self) -> set:
        """Cache current stage_results schema for compatibility queries."""
        if self._stage_results_columns is None:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(stage_results)")
            self._stage_results_columns = {row[1] for row in cursor.fetchall()}
            conn.close()

        return self._stage_results_columns

    def get_all_rallies(self) -> List[Dict]:
        """Veritabanindaki tum rallileri getir."""
        if self._rally_cache is not None:
            return self._rally_cache

        cols = self._get_stage_results_columns()
        rally_date_expr = "MAX(rally_date) as rally_date" if 'rally_date' in cols else "NULL as rally_date"
        stage_count_expr = (
            "COUNT(DISTINCT stage_id) as stage_count"
            if 'stage_id' in cols else
            "COUNT(DISTINCT stage_number) as stage_count"
        )
        order_expr = (
            "rally_date DESC, CAST(rally_id AS INTEGER) DESC, rally_id DESC"
            if 'rally_date' in cols else
            "CAST(rally_id AS INTEGER) DESC, rally_id DESC"
        )

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(f"""
            SELECT
                rally_id,
                COALESCE(MAX(rally_name), rally_id) as rally_name,
                {rally_date_expr},
                {stage_count_expr}
            FROM stage_results
            GROUP BY rally_id
            ORDER BY {order_expr}
        """)

        rallies = []
        for row in cursor.fetchall():
            rallies.append({
                'rally_id': row[0],
                'rally_name': row[1],
                'rally_date': row[2],
                'stage_count': row[3]
            })

        conn.close()
        self._rally_cache = rallies
        return rallies

    def get_rally_stages(self, rally_id: str) -> List[Dict]:
        """Belirli bir rallinin etaplarini getir."""
        cols = self._get_stage_results_columns()
        stage_id_expr = (
            "MAX(stage_id) as stage_id"
            if 'stage_id' in cols else
            "MAX(rally_id || '_ss' || stage_number) as stage_id"
        )
        stage_length_expr = (
            "MAX(stage_length_km) as stage_length_km"
            if 'stage_length_km' in cols else
            "NULL as stage_length_km"
        )
        surface_expr = (
            "LOWER(MAX(surface)) as surface"
            if 'surface' in cols else
            "NULL as surface"
        )

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(f"""
            SELECT
                {stage_id_expr},
                COALESCE(MAX(stage_name), 'SS' || stage_number) as stage_name,
                stage_number,
                {stage_length_expr},
                {surface_expr}
            FROM stage_results
            WHERE rally_id = ?
            GROUP BY stage_number
            ORDER BY stage_number
        """, [rally_id])

        stages = []
        for row in cursor.fetchall():
            stages.append({
                'stage_id': row[0],
                'stage_name': row[1],
                'stage_number': row[2],
                'stage_length_km': row[3],
                'surface': row[4]
            })

        conn.close()
        return stages

    def normalize_name(self, name: str) -> str:
        """Rally/dosya adini normalize et."""
        result = name.lower().strip()

        for pattern, replacement, *flags in self.NORMALIZE_PATTERNS:
            flag = flags[0] if flags else 0
            result = re.sub(pattern, replacement, result, flags=flag)

        return result.strip()

    def calculate_similarity(self, str1: str, str2: str) -> float:
        """Iki string arasindaki benzerlik skorunu hesapla (0-1)."""
        norm1 = self.normalize_name(str1)
        norm2 = self.normalize_name(str2)

        # SequenceMatcher ile benzerlik
        ratio = SequenceMatcher(None, norm1, norm2).ratio()

        # Ek bonus: Anahtar kelimeler eslesiyor mu?
        keywords1 = set(norm1.split())
        keywords2 = set(norm2.split())

        if keywords1 and keywords2:
            keyword_overlap = len(keywords1 & keywords2) / max(len(keywords1), len(keywords2))
            ratio = (ratio + keyword_overlap) / 2

        return ratio

    def match_kml_to_rally(self, kml_path: str, threshold: float = 0.5) -> MatchResult:
        """
        KML dosyasini en uygun rally ile esle.

        Args:
            kml_path: KML dosya yolu
            threshold: Minimum benzerlik esigi (0-1)

        Returns:
            MatchResult with best match
        """
        kml_name = Path(kml_path).stem
        rallies = self.get_all_rallies()

        best_match = None
        best_score = 0.0

        for rally in rallies:
            rally_name = rally['rally_name'] or rally['rally_id']
            score = self.calculate_similarity(kml_name, rally_name)

            if score > best_score:
                best_score = score
                best_match = rally

        if best_match and best_score >= threshold:
            stages = self.get_rally_stages(best_match['rally_id'])
            match_type = 'exact' if best_score > 0.9 else 'fuzzy'

            return MatchResult(
                kml_file=kml_path,
                kml_name=kml_name,
                matched_rally_id=best_match['rally_id'],
                matched_rally_name=best_match['rally_name'],
                matched_stages=stages,
                confidence=best_score,
                match_type=match_type
            )

        return MatchResult(
            kml_file=kml_path,
            kml_name=kml_name,
            matched_rally_id=None,
            matched_rally_name=None,
            matched_stages=[],
            confidence=best_score,
            match_type='none'
        )

    def match_all_kmls(self, kml_folder: str, threshold: float = 0.5) -> List[MatchResult]:
        """
        Klasordeki tum KML/KMZ dosyalarini esle.

        Args:
            kml_folder: KML dosyalarinin bulundugu klasor
            threshold: Minimum benzerlik esigi

        Returns:
            List of MatchResults
        """
        folder = Path(kml_folder)
        results = []

        for ext in ['*.kml', '*.kmz']:
            for kml_file in folder.glob(ext):
                result = self.match_kml_to_rally(str(kml_file), threshold)
                results.append(result)

        # Confidence'a gore sirala
        results.sort(key=lambda x: x.confidence, reverse=True)
        return results

    def extract_day_number(self, filename: str) -> Optional[int]:
        """Dosya adindan gun numarasini cikar."""
        patterns = [
            r'(\d+)\.\s*g[uü]n',  # "1. gun", "2. gün"
            r'day[- ]?(\d+)',  # "day-1", "day 2"
            r'g[uü]n[- ]?(\d+)',  # "gun-1"
        ]

        for pattern in patterns:
            match = re.search(pattern, filename, re.IGNORECASE)
            if match:
                return int(match.group(1))

        return None

    def suggest_stage_mapping(self, kml_path: str, rally_id: str) -> List[Dict]:
        """
        KML icindeki etaplari veritabanindaki etaplarla esle.

        Args:
            kml_path: KML dosya yolu
            rally_id: Hedef rally ID

        Returns:
            List of suggested mappings
        """
        from src.data.kml_parser import KMLParser

        parser = KMLParser()
        kml_data = parser.parse(kml_path)

        if not kml_data:
            return []

        db_stages = self.get_rally_stages(rally_id)
        suggestions = []

        # KML'deki her LineString icin
        for i, coords in enumerate(kml_data.coordinates if hasattr(kml_data, 'coordinates') else [kml_data.coordinates]):
            kml_stage_name = kml_data.name if hasattr(kml_data, 'name') else f"Stage {i+1}"

            # En iyi eslesen DB stage'i bul
            best_match = None
            best_score = 0

            for db_stage in db_stages:
                score = self.calculate_similarity(kml_stage_name, db_stage['stage_name'])
                if score > best_score:
                    best_score = score
                    best_match = db_stage

            suggestions.append({
                'kml_index': i,
                'kml_name': kml_stage_name,
                'suggested_stage': best_match,
                'confidence': best_score
            })

        return suggestions


def main():
    """Test KML-Stage matcher."""
    import argparse

    parser = argparse.ArgumentParser(description="KML-Stage Matcher")
    parser.add_argument('--db-path', default='data/raw/rally_results.db',
                       help='Database path')
    parser.add_argument('--kml-folder', default='kml-kmz',
                       help='KML folder path')

    args = parser.parse_args()

    print("KML-Stage Matcher Test")
    print("=" * 60)

    matcher = KMLStageMatcher(args.db_path)

    # Tum rallileri listele
    print("\nVeritabanindaki Ralliler:")
    rallies = matcher.get_all_rallies()
    for rally in rallies[:10]:
        print(f"  - {rally['rally_name']} ({rally['rally_id']}) - {rally['stage_count']} etap")

    # KML eslestirme
    print(f"\n{args.kml_folder} klasorundeki KML'ler:")
    results = matcher.match_all_kmls(args.kml_folder)

    for result in results:
        status = "OK" if result.match_type != 'none' else "NO MATCH"
        print(f"  [{status}] {result.kml_name}")
        if result.matched_rally_name:
            print(f"       -> {result.matched_rally_name} (confidence: {result.confidence:.2f})")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
