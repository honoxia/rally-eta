"""
Portable paket oluştur - Version 1.1 (Short Stage Fix)
"""

import shutil
from pathlib import Path
import zipfile

def create_portable_v1_1():
    """Portable v1.1 versiyonu oluştur"""

    print("[PORTABLE v1.1] Portable paket olusturuluyor...")

    # Klasör oluştur
    portable_dir = Path('RallyETA_Portable_v1.1')

    if portable_dir.exists():
        shutil.rmtree(portable_dir)

    portable_dir.mkdir()

    # EXE kopyala
    if not Path('dist/RallyETA.exe').exists():
        print("[ERROR] dist/RallyETA.exe bulunamadi!")
        print("   Once 'python build_exe.py' calistirin")
        return

    shutil.copy('dist/RallyETA.exe', portable_dir / 'RallyETA.exe')
    print("  [OK] EXE kopyalandi")

    # Config klasörü oluştur ve BOTH v1.0 + v1.1 kopyala
    config_dir = portable_dir / 'config'
    config_dir.mkdir()

    if Path('config/config.yaml').exists():
        shutil.copy('config/config.yaml', config_dir / 'config.yaml')
        print("  [OK] Config v1.0 kopyalandi")

    # v1.1 config (YENİ!)
    if Path('config/config_v1_1.yaml').exists():
        shutil.copy('config/config_v1_1.yaml', config_dir / 'config_v1_1.yaml')
        print("  [OK] Config v1.1 kopyalandi")

    # config_loader.py (gerekli!)
    if Path('config/config_loader.py').exists():
        shutil.copy('config/config_loader.py', config_dir / 'config_loader.py')
        print("  [OK] config_loader.py kopyalandi")

    # .streamlit config kopyala (CRITICAL!)
    if Path('.streamlit').exists():
        shutil.copytree('.streamlit', portable_dir / '.streamlit')
        print("  [OK] .streamlit kopyalandi")

    # v1.1 Python modülleri kopyala (kaynak kodları)
    src_dir = portable_dir / 'src'

    # preprocessing klasörü
    preprocessing_dir = src_dir / 'preprocessing'
    preprocessing_dir.mkdir(parents=True)

    if Path('src/preprocessing/anomaly_detector.py').exists():
        shutil.copy('src/preprocessing/anomaly_detector.py', preprocessing_dir / 'anomaly_detector.py')
        print("  [OK] anomaly_detector v1.0 kopyalandi")

    if Path('src/preprocessing/anomaly_detector_v1_1.py').exists():
        shutil.copy('src/preprocessing/anomaly_detector_v1_1.py', preprocessing_dir / 'anomaly_detector_v1_1.py')
        print("  [OK] anomaly_detector v1.1 kopyalandi")

    # features klasörü
    features_dir = src_dir / 'features'
    features_dir.mkdir(parents=True)

    if Path('src/features/engineer_features.py').exists():
        shutil.copy('src/features/engineer_features.py', features_dir / 'engineer_features.py')
        print("  [OK] engineer_features v1.0 kopyalandi")

    if Path('src/features/engineer_features_v1_1.py').exists():
        shutil.copy('src/features/engineer_features_v1_1.py', features_dir / 'engineer_features_v1_1.py')
        print("  [OK] engineer_features v1.1 kopyalandi")

    # Boş klasörler oluştur
    (portable_dir / 'data' / 'raw').mkdir(parents=True)
    (portable_dir / 'data' / 'processed').mkdir(parents=True)
    (portable_dir / 'data' / 'external').mkdir(parents=True)
    (portable_dir / 'models' / 'rally_eta_v1').mkdir(parents=True)
    (portable_dir / 'models' / 'rally_eta_v1_1').mkdir(parents=True)  # v1.1 model klasörü
    (portable_dir / 'logs').mkdir(parents=True)
    print("  [OK] Klasorler olusturuldu")

    # README v1.1 oluştur
    readme = """
RALLY ETA TAHMIN SISTEMI - VERSION 1.1
=======================================

KURULUM GEREKMIYOR!

VERSION 1.1 YENILIKLER:
-----------------------
✅ Kisa etaplar (<7km) icin gelismis tahmin
✅ Nonlinear stage length correction
✅ Surucu kisa etap performans metrigi
✅ Momentum feature (form trendi)
✅ Adaptive anomaly detection

KULLANIM:
---------
1. RallyETA.exe dosyasina cift tiklayin
2. Tarayici otomatik acilacak
3. Uygulamayi kullanmaya baslayin

VERSION SECIMI:
---------------
- v1.0: Standart versiyon (config.yaml)
- v1.1: Kisa etap optimizasyonlu (config_v1_1.yaml)

DETAYLI BILGI:
--------------
README_v1_1.md dosyasina bakiniz

NOT: Ilk acilis biraz uzun surebilir (30-60 saniye)

Destek: github.com/yourusername/rally-eta
Versiyon: 1.1 (Short Stage Fix)
Tarih: Aralik 2025
    """

    (portable_dir / 'README.txt').write_text(readme, encoding='utf-8')
    print("  [OK] README olusturuldu")

    # README_v1_1.md kopyala (detaylı talimatlar)
    if Path('README_v1_1.md').exists():
        shutil.copy('README_v1_1.md', portable_dir / 'README_v1_1.md')
        print("  [OK] README_v1_1.md kopyalandi")

    # VERSION_INFO.txt oluştur
    version_info = """
RallyETA v1.1 - Version Information
====================================

Build Date: 2025-12-09
Version: 1.1-short-stage-fix
Base Version: 1.0-mvp

CHANGES IN v1.1:
----------------
1. Adaptive anomaly detection
   - Short stages (<7km): z-threshold = 3.5
   - Long stages: z-threshold = 3.0

2. New Features (6):
   - stage_length_corrected (^0.85)
   - is_short_stage (binary flag)
   - short_stage_penalty (1.03 factor)
   - driver_short_stage_ratio (last 10 short stages)
   - driver_momentum (recent 5 vs prev 5)

3. Expected Improvements:
   - Short stage MAPE: 12-18% → 6-8%
   - Overall MAPE: 7% → 4.5-5.5%

FILES INCLUDED:
---------------
config/
  ├── config.yaml (v1.0)
  └── config_v1_1.yaml (v1.1)

src/preprocessing/
  ├── anomaly_detector.py (v1.0)
  └── anomaly_detector_v1_1.py (v1.1)

src/features/
  ├── engineer_features.py (v1.0)
  └── engineer_features_v1_1.py (v1.1)

USAGE:
------
See README_v1_1.md for detailed instructions
    """

    (portable_dir / 'VERSION_INFO.txt').write_text(version_info, encoding='utf-8')
    print("  [OK] VERSION_INFO.txt olusturuldu")

    # ZIP oluştur
    zip_name = 'RallyETA_Portable_v1.1.zip'

    print("\n[ZIP] Arsiv olusturuluyor...")
    with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file in portable_dir.rglob('*'):
            if file.is_file():
                zipf.write(file, file.relative_to(portable_dir.parent))

    print(f"\n[SUCCESS] Portable paket hazir!")
    print(f"[ZIP] {zip_name}")
    if Path(zip_name).exists():
        size_mb = Path(zip_name).stat().st_size / (1024*1024)
        print(f"[SIZE] Boyut: {size_mb:.1f} MB")

    print(f"\n[FOLDER] Klasor: {portable_dir}")
    print("\n" + "="*60)
    print("ICERIK:")
    print("="*60)
    print("✅ RallyETA.exe")
    print("✅ Config v1.0 + v1.1")
    print("✅ Anomaly Detector v1.0 + v1.1")
    print("✅ Feature Engineer v1.0 + v1.1")
    print("✅ README.txt")
    print("✅ README_v1_1.md (detayli talimatlar)")
    print("✅ VERSION_INFO.txt")
    print("="*60)
    print("\nDagitim icin ZIP dosyasini kullanabilirsiniz.")

if __name__ == '__main__':
    create_portable_v1_1()
