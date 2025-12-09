"""
Portable paket oluştur
"""

import shutil
from pathlib import Path
import zipfile

def create_portable():
    """Portable versiyonu oluştur"""

    print("[PORTABLE] Portable paket olusturuluyor...")

    # Klasör oluştur
    portable_dir = Path('RallyETA_Portable_v1.0')

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

    # Config kopyala
    if Path('config').exists():
        shutil.copytree('config', portable_dir / 'config')
        print("  [OK] Config kopyalandi")

    # .streamlit config kopyala (CRITICAL!)
    if Path('.streamlit').exists():
        shutil.copytree('.streamlit', portable_dir / '.streamlit')
        print("  [OK] .streamlit kopyalandi")

    # Boş klasörler oluştur
    (portable_dir / 'data' / 'raw').mkdir(parents=True)
    (portable_dir / 'data' / 'processed').mkdir(parents=True)
    (portable_dir / 'data' / 'external').mkdir(parents=True)
    (portable_dir / 'models' / 'rally_eta_v1').mkdir(parents=True)
    (portable_dir / 'logs').mkdir(parents=True)
    print("  [OK] Klasorler olusturuldu")

    # README oluştur
    readme = """
RALLY ETA TAHMIN SISTEMI
===========================

KURULUM GEREKMIYOR!

Kullanim:
1. RallyETA.exe dosyasina cift tiklayin
2. Tarayici otomatik acilacak
3. Uygulamayi kullanmaya baslayin

Not: Ilk acilis biraz uzun surebilir (30-60 saniye)

Destek: github.com/yourusername/rally-eta
Versiyon: 1.0
Tarih: 2025
    """

    (portable_dir / 'README.txt').write_text(readme, encoding='utf-8')
    print("  [OK] README olusturuldu")

    # ZIP oluştur
    zip_name = 'RallyETA_Portable_v1.0.zip'

    with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file in portable_dir.rglob('*'):
            if file.is_file():
                zipf.write(file, file.relative_to(portable_dir.parent))

    print(f"\n[SUCCESS] Portable paket hazir!")
    print(f"[ZIP] {zip_name}")
    if Path(zip_name).exists():
        print(f"[SIZE] Boyut: {Path(zip_name).stat().st_size / (1024*1024):.1f} MB")

    print(f"\n[FOLDER] Klasor: {portable_dir}")
    print("\nDagitim icin ZIP dosyasini kullanabilirsiniz.")

if __name__ == '__main__':
    create_portable()
