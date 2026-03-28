# Rally ETA v2.0 - Faz 1 & Faz 2 Implementation

Bu klasör Rally ETA v2.0 projesinin **Faz 1 ve Faz 2** implementasyonunu içerir.

## 📁 Klasör Yapısı

```
faz2/
├── src/
│   ├── data/
│   │   ├── car_class_normalizer.py      # Faz 1A: Araç sınıfı normalizasyonu
│   │   ├── class_best_calculator.py     # Faz 1B: Sınıf en iyi zamanı hesaplama
│   │   ├── kml_parser.py                # Faz 2A: KML/KMZ dosya parser
│   │   ├── geometric_analyzer.py        # Faz 2A: Geometrik analiz
│   │   └── stage_metadata_manager.py    # Faz 2A: Stage metadata yönetimi
│   ├── baseline/
│   │   ├── driver_performance.py        # Faz 1C: Pilot performans analizi
│   │   ├── rally_momentum.py            # Faz 1D: Rally momentum hesaplama
│   │   ├── surface_adjustment.py        # Faz 1E: Zemin bazlı düzeltme
│   │   ├── baseline_predictor.py        # Faz 1F: Ana tahmin orchestrator
│   │   └── driver_geometry_profiler.py  # Faz 2B: Pilot geometri profili
│   └── export/
│       └── excel_exporter.py            # Faz 1F: Excel export
├── tests/
│   ├── test_car_class_normalizer.py     # Faz 1A unit testleri
│   └── test_class_best_calculator.py    # Faz 1B unit testleri
├── scripts/
│   ├── migrate_car_classes.py           # Faz 1A database migration
│   └── process_kml_files.py             # Faz 2A: Toplu KML işleme
└── README.md                             # Bu dosya
```

## 🎯 Tamamlanan Fazlar

### ✅ Faz 1A: Car Class Normalizer
**Dosyalar:**
- `src/data/car_class_normalizer.py`
- `tests/test_car_class_normalizer.py`
- `scripts/migrate_car_classes.py`

**İşlev:** Araç sınıflarını normalize eder (R4 → Rally2, S2000 → Rally2)

**Kullanım:**
```python
from src.data.car_class_normalizer import CarClassNormalizer

normalizer = CarClassNormalizer()
result = normalizer.normalize('R4')  # Returns: 'Rally2'
```

**Test:**
```bash
python -m pytest tests/test_car_class_normalizer.py -v
```

**Migration:**
```bash
# Dry run (önizleme)
python scripts/migrate_car_classes.py --db-path path/to/db.db --dry-run

# Gerçek migration
python scripts/migrate_car_classes.py --db-path path/to/db.db
```

---

### ✅ Faz 1B: Class Best Time Calculator
**Dosyalar:**
- `src/data/class_best_calculator.py`
- `tests/test_class_best_calculator.py`

**İşlev:** Belirli bir etap ve sınıf için en iyi zamanı hesaplar

**Kullanım:**
```python
from src.data.class_best_calculator import ClassBestTimeCalculator

calc = ClassBestTimeCalculator('path/to/db.db')
result = calc.get_class_best('rally_97', 'SS1', 'Rally2')
# Returns: {'class_best_time': 630.5, 'class_best_driver': 'Pilot A', ...}
```

**Test:**
```bash
python -m pytest tests/test_class_best_calculator.py -v
```

---

### ✅ Faz 1C: Driver Performance Analyzer
**Dosyalar:**
- `src/baseline/driver_performance.py`

**İşlev:** Pilot için baseline ratio hesaplar (son 15 etap ortalaması)

**Kullanım:**
```python
from src.baseline.driver_performance import DriverPerformanceAnalyzer

analyzer = DriverPerformanceAnalyzer('path/to/db.db')
result = analyzer.calculate_baseline_ratio('kerem_kazaz')
# Returns: {'baseline_ratio': 1.052, 'data_points': 15, ...}
```

**Test:**
```bash
python src/baseline/driver_performance.py --driver-id kerem_kazaz --window 15
```

---

### ✅ Faz 1D: Rally Momentum Analyzer
**Dosyalar:**
- `src/baseline/rally_momentum.py`

**İşlev:** Rally içindeki form değişimini hesaplar

**Kullanım:**
```python
from src.baseline.rally_momentum import RallyMomentumAnalyzer

analyzer = RallyMomentumAnalyzer('path/to/db.db')
result = analyzer.calculate_momentum(
    driver_id='kerem_kazaz',
    rally_id='bodrum_2025',
    current_stage=3,
    driver_baseline=1.052
)
# Returns: {'momentum': 0.02, 'status': 'Good form', ...}
```

**Test:**
```bash
python src/baseline/rally_momentum.py \
    --driver-id kerem_kazaz \
    --rally-id bodrum_2025 \
    --current-stage 3 \
    --baseline 1.052
```

---

### ✅ Faz 1E: Surface Adjustment Calculator
**Dosyalar:**
- `src/baseline/surface_adjustment.py`

**İşlev:** Zemin bazlı performans düzeltmesi (gravel vs asphalt)

**Kullanım:**
```python
from src.baseline.surface_adjustment import SurfaceAdjustmentCalculator

calc = SurfaceAdjustmentCalculator('path/to/db.db')
result = calc.calculate_adjustment('kerem_kazaz', 'gravel')
# Returns: {'adjustment': 0.98, 'target_avg': 1.048, ...}
```

**Test:**
```bash
python src/baseline/surface_adjustment.py \
    --driver-id kerem_kazaz \
    --surface gravel
```

---

### ✅ Faz 1F: Baseline Predictor & Excel Exporter
**Dosyalar:**
- `src/baseline/baseline_predictor.py`
- `src/export/excel_exporter.py`

**İşlev:** Tüm modülleri birleştirerek tam tahmin yapar ve Excel'e aktarır

**Kullanım:**
```python
from src.baseline.baseline_predictor import BaselinePredictor
from src.export.excel_exporter import ExcelExporter

# Tahmin yap
predictor = BaselinePredictor('path/to/db.db')
result = predictor.predict(
    driver_id='kerem_kazaz',
    rally_id='bodrum_2025',
    stage_id='SS3',
    current_stage=3,
    surface='gravel',
    normalized_class='Rally2'
)

print(result['explanation'])
print(f"Predicted time: {result['predicted_time_str']}")

# Excel'e aktar
exporter = ExcelExporter()
exporter.export_prediction(
    prediction=result,
    driver_name='Kerem Kazaz',
    stage_name='SS3 Bodrum',
    output_path='prediction.xlsx'
)
```

---

## 🧪 Testler

### Unit Testlerin Çalıştırılması

```bash
# Tüm testler
python -m pytest tests/ -v

# Sadece car_class_normalizer testleri
python -m pytest tests/test_car_class_normalizer.py -v

# Sadece class_best_calculator testleri
python -m pytest tests/test_class_best_calculator.py -v
```

### Manuel Testler

Her modülün kendi main() fonksiyonu var ve bağımsız test edilebilir:

```bash
# CarClassNormalizer test
python src/data/car_class_normalizer.py

# ClassBestTimeCalculator test
python src/data/class_best_calculator.py --rally-id 97 --stage-id SS1

# DriverPerformanceAnalyzer test
python src/baseline/driver_performance.py --driver-id kerem_kazaz

# RallyMomentumAnalyzer test
python src/baseline/rally_momentum.py \
    --driver-id kerem_kazaz \
    --rally-id bodrum_2025 \
    --current-stage 3 \
    --baseline 1.052

# SurfaceAdjustmentCalculator test
python src/baseline/surface_adjustment.py --driver-id kerem_kazaz --surface gravel
```

---

## 📋 Gereksinimler

```
numpy
pandas
openpyxl
sqlite3 (Python standard library)
```

Kurulum:
```bash
pip install numpy pandas openpyxl
```

---

## 🚀 Hızlı Başlangıç

1. **Database Migration (Faz 1A)**
```bash
python scripts/migrate_car_classes.py --db-path ../data/raw/rally_results.db
```

2. **Unit Testleri Çalıştır**
```bash
python -m pytest tests/ -v
```

3. **Tam Pipeline Testi**
```python
from src.baseline.baseline_predictor import BaselinePredictor

predictor = BaselinePredictor('../data/raw/rally_results.db')
result = predictor.predict(
    driver_id='kerem_kazaz',
    rally_id='97',
    stage_id='SS1',
    current_stage=2,
    surface='gravel',
    normalized_class='Rally2'
)

print(result['explanation'])
```

---

## 📝 Notlar

- Tüm Faz 1 (1A-1F) modülleri tamamlanmıştır
- Her modül bağımsız olarak test edilebilir
- Database migration Faz 1A'da yapılmalıdır (normalized_class kolonu eklenir)
- BaselinePredictor tüm modülleri orchestrate eder
- Excel export v1.2 formatı ile uyumludur

---

## ✅ Faz 2A: KML Collection & Geometric Analysis

**Dosyalar:**
- `src/data/kml_parser.py` - KML/KMZ dosya parser
- `src/data/geometric_analyzer.py` - Geometrik özellik hesaplama
- `src/data/stage_metadata_manager.py` - Database yönetimi
- `scripts/process_kml_files.py` - Toplu KML işleme

**İşlev:** Rally etap KML dosyalarını analiz ederek geometrik özellikleri (hairpin, viraj, tırmanış) çıkarır

### KML Parser Kullanımı
```python
from src.data.kml_parser import KMLParser

parser = KMLParser()
data = parser.parse('stage_ss1.kml')
print(f"Distance: {data.distance_km:.2f} km")
print(f"Ascent: {data.total_ascent:.0f} m")
```

### Geometric Analyzer Kullanımı
```python
from src.data.geometric_analyzer import GeometricAnalyzer

analyzer = GeometricAnalyzer()
geometry = analyzer.analyze_file('stage_ss1.kml')

print(f"Hairpins: {geometry.hairpin_count}")
print(f"Turn density: {geometry.turn_density:.2f}/km")
print(f"Max grade: {geometry.max_grade:.1f}%")
```

### Toplu KML İşleme
```bash
# Tek dosya işle
python scripts/process_kml_files.py --file stage.kml --rally-id bodrum_2025 --surface gravel

# Klasör işle
python scripts/process_kml_files.py --dir ./kml_files/ --rally-id bodrum_2025 --surface gravel

# Önizleme (dry run)
python scripts/process_kml_files.py --dir ./kml_files/ --rally-id test --dry-run
```

### Stage Metadata Manager
```python
from src.data.stage_metadata_manager import StageMetadataManager

manager = StageMetadataManager('path/to/db.db')

# İstatistikleri al
stats = manager.get_statistics()
print(f"Total stages: {stats['total_stages']}")

# Benzer etapları bul
similar = manager.get_similar_stages('bodrum_2025_ss1', limit=5)

# Yüksek hairpin'li etaplar
hairpin_stages = manager.get_high_hairpin_stages(min_hairpin_density=1.0)
```

---

## ✅ Faz 2B: Driver Geometry Profiler

**Dosyalar:**
- `src/baseline/driver_geometry_profiler.py`

**İşlev:** Pilotların geometrik karakteristiklerdeki performansını analiz eder

**Hesaplanan Metrikler:**
- **Hairpin Performance** - Virajlı etaplarda performans
- **Climb Performance** - Yokuşlu etaplarda performans
- **Curvature Sensitivity** - Kıvrımlı yollarda hassasiyet
- **Grade Performance** - Eğimli yollarda performans

### Kullanım
```python
from src.baseline.driver_geometry_profiler import DriverGeometryProfiler

profiler = DriverGeometryProfiler('path/to/db.db')
profile = profiler.create_profile('kerem_kazaz')

if profile:
    print(f"Hairpin Performance: {profile.hairpin_performance:.3f}")
    print(f"Climb Performance: {profile.climb_performance:.3f}")
    print(f"Confidence: {profile.confidence}")

    # Detaylı açıklama
    explanation = profiler.get_profile_explanation(profile)
    print(explanation)
```

### Komut Satırı Testi
```bash
python src/baseline/driver_geometry_profiler.py --driver-id kerem_kazaz
```

### Örnek Çıktı
```
DRIVER GEOMETRY PROFILE - Kerem Kazaz
============================================================

HAIRPIN PERFORMANCE
────────────────────────────────────────
  • High hairpin stages: 35
  • Low hairpin stages: 65
  • Performance ratio: 1.004
  • Interpretation: 0.4% slower on hairpin-heavy stages

CLIMB PERFORMANCE
────────────────────────────────────────
  • High climb stages: 25
  • Low climb stages: 75
  • Performance ratio: 1.014
  • Interpretation: 1.4% slower on climb-heavy stages

SUMMARY
============================================================
  Strengths: Curvy sections
  Weaknesses: Climbs
```

---

## 🔜 Sonraki Fazlar

- **Faz 3A**: LightGBM Training
- **Faz 3B**: SHAP Integration
- **Faz 4**: Confidence & Production

---

**Hazırlayan:** Claude
**Tarih:** 2025-12-29
**Plan Referansı:** planfazv2.md, planv2.md
**Versiyon:** Faz 1 + Faz 2 Complete
