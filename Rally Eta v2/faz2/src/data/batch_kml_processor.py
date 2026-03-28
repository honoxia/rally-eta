"""
Batch KML Processor - Toplu KML dosyasi isleme ve stages_metadata guncelleme.

Birden fazla KML/KMZ dosyasini isleyip geometrik ozellikleri
stages_metadata tablosuna kaydeder.
"""
import sqlite3
import logging
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime

from src.data.geometry_merge import merge_geometry_rows
from src.data.master_schema import ensure_stage_geometry_table

logger = logging.getLogger(__name__)


@dataclass
class ProcessingResult:
    """KML isleme sonucu."""
    kml_file: str
    success: bool
    stages_processed: int
    error_message: Optional[str] = None
    geometry_data: Optional[Dict] = None


class BatchKMLProcessor:
    """
    Toplu KML dosyasi isleyici.

    KML dosyalarini parse eder, geometrik analiz yapar ve
    stages_metadata tablosuna kaydeder.
    """

    def __init__(self, db_path: str):
        """
        Initialize processor.

        Args:
            db_path: Veritabani yolu
        """
        self.db_path = db_path
        self._ensure_tables()
        self._stage_metadata_columns = None

    def _ensure_tables(self):
        """Gerekli tablolarin varligini kontrol et, yoksa olustur."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        ensure_stage_geometry_table(conn)

        # kml_files tablosu - islenen KML dosyalarini takip et
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS kml_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT UNIQUE,
                file_name TEXT,
                rally_id TEXT,
                stages_count INTEGER,
                processed_at TEXT,
                status TEXT
            )
        """)

        conn.commit()
        conn.close()
        self._ensure_columns()

    def _ensure_columns(self):
        """Eksik kolonlari ekle (mevcut DB'ler icin)."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("PRAGMA table_info(stage_geometry)")
        existing = {row[1] for row in cursor.fetchall()}

        desired = {
            'max_elevation': 'REAL',
            'min_elevation': 'REAL',
            'curvature_sum': 'REAL',
            'straight_ratio': 'REAL',
            'sign_changes_per_km': 'REAL',
            'geometry_points': 'INTEGER',
            'elevation_api_calls': 'INTEGER',
            'cache_hit_rate': 'REAL',
            'analyzer_version': 'TEXT',
        }

        for col, col_type in desired.items():
            if col not in existing:
                cursor.execute(f"ALTER TABLE stage_geometry ADD COLUMN {col} {col_type}")

        conn.commit()
        conn.close()

    def _get_stage_metadata_columns(self) -> set:
        if self._stage_metadata_columns is None:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(stage_geometry)")
            self._stage_metadata_columns = {row[1] for row in cursor.fetchall()}
            conn.close()
        return self._stage_metadata_columns

    def process_single_kml(self, kml_path: str, rally_id: str,
                          stage_mappings: Optional[Dict[int, str]] = None) -> ProcessingResult:
        """
        Tek bir KML dosyasini isle.

        Args:
            kml_path: KML dosya yolu
            rally_id: Hedef rally ID
            stage_mappings: {kml_index: stage_id} eslestirme dict'i

        Returns:
            ProcessingResult
        """
        from src.data.kml_parser import KMLData
        from src.stage_analyzer.kml_parser import parse_kml_file
        from src.stage_analyzer.kml_analyzer import KMLAnalyzer

        try:
            # Parse KML (multi-stage)
            kml_multi = parse_kml_file(kml_path)
            if not kml_multi:
                return ProcessingResult(
                    kml_file=kml_path,
                    success=False,
                    stages_processed=0,
                    error_message="KML parse hatasi"
                )

            analyzer = KMLAnalyzer(geom_step=10.0, smoothing_window=7, elev_step=200.0)

            stages_processed = 0
            last_geometry = None
            geometry_rows = []

            for idx, stage in enumerate(kml_multi):
                stage_name = stage.name if hasattr(stage, 'name') else ''
                if not (stage_mappings and idx in stage_mappings):
                    if self._should_skip_stage(stage_name, 0):
                        continue

                temp_kml = self._write_temp_stage_kml(stage, rally_id, idx)
                try:
                    results = analyzer.analyze_kml(str(temp_kml), hairpin_threshold=20.0)
                finally:
                    if temp_kml.exists():
                        temp_kml.unlink()

                kml_data = KMLData(
                    name=stage_name,
                    coordinates=[],
                    distance_km=results.get('distance_km', 0),
                    total_ascent=results.get('total_ascent', 0),
                    total_descent=results.get('total_descent', 0),
                    min_altitude=0,
                    max_altitude=0,
                )

                geom_dict = self._map_kml_analyzer_results(results)

                # Determine stage_id
                if stage_mappings and idx in stage_mappings:
                    stage_id = stage_mappings[idx]
                else:
                    match = self._find_best_stage_match(rally_id, kml_data, kml_path)
                    if match:
                        stage_id = match['stage_id']
                        stage_name = match['stage_name']
                    else:
                        stage_id = f"{rally_id}_{Path(kml_path).stem}_stage_{idx+1}"
                        stage_name = kml_data.name

                geometry_rows.append(self._build_geometry_payload(
                    stage_id=stage_id,
                    rally_id=rally_id,
                    stage_name=stage_name,
                    geometry=geom_dict,
                    kml_file=kml_path
                ))
                stages_processed += 1
                last_geometry = geom_dict

            if geometry_rows:
                self._merge_geometry_payloads(geometry_rows, kml_path)

            # Log KML file
            self._log_kml_file(kml_path, rally_id, stages_processed, 'success')

            return ProcessingResult(
                kml_file=kml_path,
                success=True,
                stages_processed=stages_processed,
                geometry_data=asdict(last_geometry) if hasattr(last_geometry, '__dict__') else last_geometry
            )

        except Exception as e:
            logger.error(f"KML isleme hatasi: {kml_path} - {e}")
            return ProcessingResult(
                kml_file=kml_path,
                success=False,
                stages_processed=0,
                error_message=str(e)
            )

    def _write_temp_stage_kml(self, stage, rally_id: str, idx: int) -> Path:
        """Write a temporary single-stage KML for analyzer compatibility."""
        temp_kml = Path(f"temp_stage_{rally_id}_{idx+1}.kml")
        stage_name = stage.name if hasattr(stage, 'name') else f"Stage {idx+1}"
        coords = stage.coordinates if hasattr(stage, 'coordinates') else []

        kml_content = '<?xml version="1.0" encoding="UTF-8"?>\n'
        kml_content += '<kml xmlns="http://www.opengis.net/kml/2.2">\n'
        kml_content += '<Document>\n'
        kml_content += f'<Placemark><name>{stage_name}</name>\n'
        kml_content += '<LineString><coordinates>\n'
        for lat, lon in coords:
            kml_content += f'{lon},{lat},0 '
        kml_content += '\n</coordinates></LineString></Placemark>\n'
        kml_content += '</Document>\n</kml>'

        with open(temp_kml, 'w', encoding='utf-8') as f:
            f.write(kml_content)

        return temp_kml

    def _map_kml_analyzer_results(self, results: Dict) -> Dict:
        """Map KMLAnalyzer results to stages_metadata fields."""
        return {
            'distance_km': results.get('distance_km', 0),
            'curvature_sum': results.get('curvature_sum', 0),
            'curvature_density': results.get('curvature_density', 0),
            'p95_curvature': results.get('p95_curvature', 0),
            'max_curvature': results.get('max_curvature', 0),
            'avg_curvature': results.get('avg_curvature', 0),
            'hairpin_count': results.get('hairpin_count', 0),
            'hairpin_density': results.get('hairpin_density', 0),
            'straight_ratio': results.get('straight_ratio', 0),
            'sign_changes_per_km': results.get('sign_changes_per_km', 0),
            'total_ascent': results.get('total_ascent', 0),
            'total_descent': results.get('total_descent', 0),
            'max_grade': results.get('max_grade', 0),
            'avg_abs_grade': results.get('avg_abs_grade', 0),
            'geometry_points': results.get('geometry_samples', 0),
            'elevation_api_calls': results.get('elevation_samples', 0),
            'cache_hit_rate': 0,
            'turn_count': 0,
            'turn_density': 0,
            'avg_grade': 0,
            'straight_percentage': results.get('straight_ratio', 0) * 100,
            'curvy_percentage': max(0.0, 100.0 - (results.get('straight_ratio', 0) * 100)),
            'analyzer_version': 'kml_analyzer_v2',
        }
    def _should_skip_stage(self, stage_name: str, distance_km: float) -> bool:
        """Heuristic filter for non-stage placemarks (service/start/finish)."""
        name = (stage_name or '').lower()
        skip_terms = [
            'servis', 'service', 'start', 'finish', 'finiş', 'finish',
            'zk', 'transfer', 'liaison', 'park',
        ]
        if any(term in name for term in skip_terms):
            return True
        if distance_km and distance_km < 0.5:
            return True
        return False

    def _find_best_stage_match(self, rally_id: str, kml_data, kml_path: str) -> Optional[Dict]:
        """Find the best matching stage_id for a single-stage KML."""
        from src.data.kml_stage_matcher import KMLStageMatcher

        matcher = KMLStageMatcher(self.db_path)
        stages = matcher.get_rally_stages(rally_id)
        if not stages:
            return None

        kml_name = kml_data.name or Path(kml_path).stem
        file_name = Path(kml_path).stem
        stage_number = self._extract_stage_number(kml_name) or self._extract_stage_number(file_name)

        if stage_number:
            numbered = [s for s in stages if s.get('stage_number') == stage_number]
            if len(numbered) == 1:
                return numbered[0]
            if numbered:
                stages = numbered

        best = None
        best_score = 0.0

        for stage in stages:
            name_score = max(
                matcher.calculate_similarity(kml_name, stage['stage_name']),
                matcher.calculate_similarity(file_name, stage['stage_name'])
            )

            distance_score = None
            if stage.get('stage_length_km') and kml_data.distance_km:
                diff = abs(stage['stage_length_km'] - kml_data.distance_km)
                denom = max(stage['stage_length_km'], kml_data.distance_km, 1.0)
                distance_score = max(0.0, 1.0 - (diff / denom))

            if stage_number and stage.get('stage_number') == stage_number:
                name_score = min(1.0, name_score + 0.25)

            if distance_score is not None:
                score = (name_score * 0.7) + (distance_score * 0.3)
            else:
                score = name_score

            if score > best_score:
                best_score = score
                best = stage

        if best and best_score >= 0.45:
            return best

        logger.warning(
            "Stage match not found for rally_id=%s kml=%s (best_score=%.2f)",
            rally_id,
            Path(kml_path).name,
            best_score
        )
        return None

    def _extract_stage_number(self, text: str) -> Optional[int]:
        """Extract stage number from text like SS1, SS 2, or Etap 3."""
        if not text:
            return None

        patterns = [
            r'\bsss\s*0*(\d+)\b',
            r'\bss\s*0*(\d+)\b',
            r'\b[öo]e\s*0*(\d+)\b',
            r'\b[öo]\.\s*e\.?\s*0*(\d+)\b',
            r'\betap\s*0*(\d+)\b',
            r'\bstage\s*0*(\d+)\b',
            r'\b(\d+)\.\s*etap\b'
        ]

        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                try:
                    return int(match.group(1))
                except ValueError:
                    return None

        return None

    def process_multi_stage_kml(self, kml_path: str, rally_id: str,
                                stage_mappings: Dict[str, str]) -> ProcessingResult:
        """
        Birden fazla etap iceren KML dosyasini isle.

        Args:
            kml_path: KML dosya yolu
            rally_id: Hedef rally ID
            stage_mappings: {kml_stage_name: stage_id} eslestirme

        Returns:
            ProcessingResult
        """
        from src.data.kml_parser import KMLParser
        from src.data.geometric_analyzer import GeometricAnalyzer

        try:
            parser = KMLParser()
            analyzer = GeometricAnalyzer()

            # Parse KML - multi-geometry support
            kml_data = parser.parse_multi(kml_path)

            if not kml_data:
                return ProcessingResult(
                    kml_file=kml_path,
                    success=False,
                    stages_processed=0,
                    error_message="Multi-KML parse hatasi"
                )

            stages_processed = 0
            geometry_rows = []

            for stage_data in kml_data:
                stage_name = stage_data.get('name', f'Stage_{stages_processed}')

                # Find matching stage_id
                stage_id = stage_mappings.get(stage_name)
                if not stage_id:
                    # Fuzzy match dene
                    for kml_name, sid in stage_mappings.items():
                        if stage_name.lower() in kml_name.lower() or kml_name.lower() in stage_name.lower():
                            stage_id = sid
                            break

                if not stage_id:
                    logger.warning(f"Eslestirme bulunamadi: {stage_name}")
                    continue

                # Analyze
                coords = stage_data.get('coordinates', [])
                if not coords:
                    continue

                geometry = analyzer.analyze(coords)
                if geometry:
                    geometry_rows.append(self._build_geometry_payload(
                        stage_id=stage_id,
                        rally_id=rally_id,
                        stage_name=stage_name,
                        geometry=geometry,
                        kml_file=kml_path
                    ))
                    stages_processed += 1

            if geometry_rows:
                self._merge_geometry_payloads(geometry_rows, kml_path)

            self._log_kml_file(kml_path, rally_id, stages_processed, 'success')

            return ProcessingResult(
                kml_file=kml_path,
                success=True,
                stages_processed=stages_processed
            )

        except Exception as e:
            logger.error(f"Multi-KML isleme hatasi: {e}")
            return ProcessingResult(
                kml_file=kml_path,
                success=False,
                stages_processed=0,
                error_message=str(e)
            )

    def process_folder(self, kml_folder: str, auto_match: bool = True) -> List[ProcessingResult]:
        """
        Klasordeki tum KML/KMZ dosyalarini isle.

        Args:
            kml_folder: KML klasoru
            auto_match: Otomatik rally eslestirme yap

        Returns:
            List of ProcessingResults
        """
        from src.data.kml_stage_matcher import KMLStageMatcher

        folder = Path(kml_folder)
        results = []

        if auto_match:
            matcher = KMLStageMatcher(self.db_path)

        for ext in ['*.kml', '*.kmz']:
            for kml_file in folder.glob(ext):
                if auto_match:
                    # Otomatik eslestirme
                    match = matcher.match_kml_to_rally(str(kml_file))
                    if match.matched_rally_id:
                        result = self.process_single_kml(
                            str(kml_file),
                            match.matched_rally_id
                        )
                    else:
                        result = ProcessingResult(
                            kml_file=str(kml_file),
                            success=False,
                            stages_processed=0,
                            error_message="Rally eslestirme bulunamadi"
                        )
                else:
                    # Rally ID olmadan isle (generic)
                    rally_id = folder.name
                    result = self.process_single_kml(str(kml_file), rally_id)

                results.append(result)
                logger.info(f"Islendi: {kml_file.name} - {'OK' if result.success else 'FAIL'}")

        return results

    def _build_geometry_payload(self, stage_id: str, rally_id: str, stage_name: str,
                               geometry, kml_file: str) -> Dict:
        """Geometrik verileri canonical merge payload'una donustur."""
        # Geometry object'ten degerleri al
        if hasattr(geometry, '__dict__'):
            geom_dict = vars(geometry)
        elif isinstance(geometry, dict):
            geom_dict = geometry
        else:
            geom_dict = {}

        if 'straight_ratio' in geom_dict and 'straight_percentage' not in geom_dict:
            geom_dict['straight_percentage'] = geom_dict['straight_ratio'] * 100

        if 'curvy_percentage' not in geom_dict:
            geom_dict['curvy_percentage'] = max(0.0, 100.0 - geom_dict.get('straight_percentage', 0))

        geom_dict.setdefault('analyzer_version', 'ml_optimized_v1')

        analyzed_at = datetime.now().isoformat()
        return {
            'stage_id': stage_id,
            'rally_id': rally_id,
            'stage_name': stage_name,
            'distance_km': geom_dict.get('distance_km', 0),
            'total_ascent': geom_dict.get('total_ascent', 0),
            'total_descent': geom_dict.get('total_descent', 0),
            'max_elevation': geom_dict.get('max_elevation', geom_dict.get('max_altitude', 0)),
            'min_elevation': geom_dict.get('min_elevation', geom_dict.get('min_altitude', 0)),
            'max_altitude': geom_dict.get('max_altitude', geom_dict.get('max_elevation', 0)),
            'min_altitude': geom_dict.get('min_altitude', geom_dict.get('min_elevation', 0)),
            'hairpin_count': geom_dict.get('hairpin_count', 0),
            'hairpin_density': geom_dict.get('hairpin_density', 0),
            'turn_count': geom_dict.get('turn_count', 0),
            'turn_density': geom_dict.get('turn_density', 0),
            'avg_curvature': geom_dict.get('avg_curvature', 0),
            'max_curvature': geom_dict.get('max_curvature', 0),
            'p95_curvature': geom_dict.get('p95_curvature', 0),
            'curvature_density': geom_dict.get('curvature_density', 0),
            'curvature_sum': geom_dict.get('curvature_sum', 0),
            'straight_ratio': geom_dict.get('straight_ratio', 0),
            'sign_changes_per_km': geom_dict.get('sign_changes_per_km', 0),
            'geometry_points': geom_dict.get('geometry_points', 0),
            'elevation_api_calls': geom_dict.get('elevation_api_calls', 0),
            'cache_hit_rate': geom_dict.get('cache_hit_rate', 0),
            'avg_grade': geom_dict.get('avg_grade', 0),
            'max_grade': geom_dict.get('max_grade', 0),
            'avg_abs_grade': geom_dict.get('avg_abs_grade', 0),
            'straight_percentage': geom_dict.get('straight_percentage', 0),
            'curvy_percentage': geom_dict.get('curvy_percentage', 0),
            'analyzer_version': geom_dict.get('analyzer_version', 'ml_optimized_v1'),
            'analysis_version': geom_dict.get('analyzer_version', 'ml_optimized_v1'),
            'kml_file': kml_file,
            'source_kml': kml_file,
            'processed_at': analyzed_at,
            'analyzed_at': analyzed_at,
            'geometry_json': json.dumps(geom_dict),
        }

    def _merge_geometry_payloads(self, geometry_rows: List[Dict], source_label: str) -> None:
        """KML kaynakli geometry satirlarini merkezi merge servisiyle kaydet."""
        if not geometry_rows:
            return

        summary = merge_geometry_rows(
            master_db_path=self.db_path,
            incoming_rows=geometry_rows,
            source_label=source_label,
            backup_dir="backups",
            report_dir="reports",
        )

        if summary.conflict_rows:
            logger.warning(
                "Geometry merge conflicts for %s: %s",
                source_label,
                ", ".join(summary.conflict_stage_ids),
            )

    def _save_geometry(self, stage_id: str, rally_id: str, stage_name: str,
                      geometry, kml_file: str):
        """Geriye donuk uyumluluk icin tek kaydi merge servisiyle kaydet."""
        payload = self._build_geometry_payload(stage_id, rally_id, stage_name, geometry, kml_file)
        self._merge_geometry_payloads([payload], kml_file)

    def _log_kml_file(self, file_path: str, rally_id: str, stages_count: int, status: str):
        """KML dosya kaydini logla."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT OR REPLACE INTO kml_files
            (file_path, file_name, rally_id, stages_count, processed_at, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, [
            file_path,
            Path(file_path).name,
            rally_id,
            stages_count,
            datetime.now().isoformat(),
            status
        ])

        conn.commit()
        conn.close()

    def get_processed_files(self) -> List[Dict]:
        """Islenmis KML dosyalarini getir."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT file_path, file_name, rally_id, stages_count, processed_at, status
            FROM kml_files
            ORDER BY processed_at DESC
        """)

        files = []
        for row in cursor.fetchall():
            files.append({
                'file_path': row[0],
                'file_name': row[1],
                'rally_id': row[2],
                'stages_count': row[3],
                'processed_at': row[4],
                'status': row[5]
            })

        conn.close()
        return files

    def get_stages_with_geometry(self) -> List[Dict]:
        """Geometrik verisi olan etaplari getir."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT stage_id, rally_id, stage_name, distance_km,
                   hairpin_count, hairpin_density, curvature_density,
                   p95_curvature, max_grade, avg_abs_grade,
                   straight_ratio, sign_changes_per_km,
                   total_ascent, total_descent, geometry_points,
                   elevation_api_calls, cache_hit_rate, processed_at
            FROM stage_geometry
            ORDER BY processed_at DESC
        """)

        stages = []
        for row in cursor.fetchall():
            stages.append({
                'stage_id': row[0],
                'rally_id': row[1],
                'stage_name': row[2],
                'distance_km': row[3],
                'hairpin_count': row[4],
                'hairpin_density': row[5],
                'curvature_density': row[6],
                'p95_curvature': row[7],
                'max_grade': row[8],
                'avg_abs_grade': row[9],
                'straight_ratio': row[10],
                'sign_changes_per_km': row[11],
                'total_ascent': row[12],
                'total_descent': row[13],
                'geometry_points': row[14],
                'elevation_api_calls': row[15],
                'cache_hit_rate': row[16],
                'processed_at': row[17]
            })

        conn.close()
        return stages

    def get_geometry_stats(self) -> Dict:
        """Geometrik veri istatistiklerini getir."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # stage_geometry sayisi
        cursor.execute("SELECT COUNT(*) FROM stage_geometry")
        metadata_count = cursor.fetchone()[0]

        # stage_results sayisi - stage_id yok, rally_id + stage_number kombinasyonu kullan
        try:
            cursor.execute("""
                SELECT COUNT(*) FROM (
                    SELECT DISTINCT rally_id, stage_number FROM stage_results
                )
            """)
            total_stages = cursor.fetchone()[0]
        except:
            total_stages = 0

        # kml_files sayisi
        try:
            cursor.execute("SELECT COUNT(*) FROM kml_files WHERE status = 'success'")
            kml_count = cursor.fetchone()[0]
        except:
            kml_count = 0

        conn.close()

        coverage = (metadata_count / total_stages * 100) if total_stages > 0 else 0

        return {
            'stages_with_geometry': metadata_count,
            'total_stages': total_stages,
            'coverage_percent': coverage,
            'kml_files_processed': kml_count
        }


def main():
    """Test batch processor."""
    import argparse

    parser = argparse.ArgumentParser(description="Batch KML Processor")
    parser.add_argument('--db-path', default='data/raw/rally_results.db')
    parser.add_argument('--kml-folder', default='kml-kmz')
    parser.add_argument('--process', action='store_true', help='Klasoru isle')

    args = parser.parse_args()

    processor = BatchKMLProcessor(args.db_path)

    if args.process:
        print(f"Klasor isleniyor: {args.kml_folder}")
        results = processor.process_folder(args.kml_folder, auto_match=True)

        success = sum(1 for r in results if r.success)
        print(f"\nSonuc: {success}/{len(results)} basarili")
    else:
        print("Geometrik veri istatistikleri:")
        stats = processor.get_geometry_stats()
        for key, value in stats.items():
            print(f"  {key}: {value}")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
