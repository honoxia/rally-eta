"""
Rally ETA - EXE Builder
PyInstaller ile EXE oluşturur
"""

import PyInstaller.__main__
import shutil
from pathlib import Path
import time

def clean_build_dirs():
    """Eski build dosyalarını temizle"""
    print("[CLEAN] Eski build dosyalari temizleniyor...")

    dirs_to_clean = ['build', 'dist', '__pycache__']

    for dir_name in dirs_to_clean:
        if Path(dir_name).exists():
            shutil.rmtree(dir_name)
            print(f"  [OK] {dir_name} silindi")

def create_icon():
    """Basit bir ikon oluştur"""
    icon_path = Path('assets/icon.ico')

    if icon_path.exists():
        print("[OK] Icon zaten var")
        return

    print("[ICON] Icon olusturuluyor...")
    icon_path.parent.mkdir(exist_ok=True)

    try:
        from PIL import Image, ImageDraw

        # 256x256 ikon
        img = Image.new('RGBA', (256, 256), (255, 255, 255, 0))
        draw = ImageDraw.Draw(img)

        # Basit bir ralli bayrağı çiz
        # Kırmızı arka plan
        draw.rectangle([0, 0, 256, 256], fill='#FF4B4B')

        # Beyaz çapraz çizgiler (finish flag pattern)
        for i in range(0, 256, 64):
            for j in range(0, 256, 64):
                if (i + j) % 128 == 0:
                    draw.rectangle([i, j, i+64, j+64], fill='white')

        # Kaydet
        img.save(icon_path, format='ICO')
        print(f"  [OK] Icon olusturuldu: {icon_path}")

    except ImportError:
        print("  [WARN] PIL bulunamadi, icon olusturulamadi")

def create_streamlit_config():
    """Streamlit config klasörünü oluştur"""
    config_path = Path('.streamlit')
    config_path.mkdir(exist_ok=True)

    # Streamlit config dosyası
    config_content = """[server]
headless = true
port = 8501
address = "localhost"
enableCORS = false
enableXsrfProtection = false

[browser]
gatherUsageStats = false

[global]
developmentMode = false
showWarningOnDirectExecution = false
"""
    (config_path / 'config.toml').write_text(config_content)
    print("[OK] Streamlit config olusturuldu")

def build_exe():
    """PyInstaller ile EXE oluştur"""
    print("\n" + "="*60)
    print("RALLY ETA - EXE BUILD")
    print("="*60 + "\n")

    # Temizlik
    clean_build_dirs()

    # Icon
    create_icon()

    # Streamlit config
    create_streamlit_config()

    # PyInstaller komutu
    print("\n[BUILD] PyInstaller ile build basliyor...")
    print("   (Bu 5-10 dakika surebilir)\n")

    start_time = time.time()

    try:
        PyInstaller.__main__.run([
            'launcher.py',
            '--onefile',
            '--windowed',  # Console'u gizle
            '--name=RallyETA',
            '--icon=assets/icon.ico',

            # Data dosyaları
            '--add-data=app.py;.',
            '--add-data=src;src',
            '--add-data=config;config',
            '--add-data=.streamlit;.streamlit',

            # Hidden imports
            '--hidden-import=streamlit',
            '--hidden-import=streamlit.web.cli',
            '--hidden-import=streamlit.web.bootstrap',
            '--hidden-import=streamlit.runtime',
            '--hidden-import=streamlit.runtime.scriptrunner',
            '--hidden-import=lightgbm',
            '--hidden-import=sklearn',
            '--hidden-import=sklearn.utils._weight_vector',
            '--hidden-import=pandas',
            '--hidden-import=numpy',
            '--hidden-import=selenium',
            '--hidden-import=selenium.webdriver',
            '--hidden-import=selenium.webdriver.chrome',
            '--hidden-import=selenium.webdriver.chrome.service',
            '--hidden-import=selenium.webdriver.chrome.options',
            '--hidden-import=selenium.webdriver.common.by',
            '--hidden-import=selenium.webdriver.support.ui',
            '--hidden-import=selenium.webdriver.support.expected_conditions',
            '--hidden-import=webdriver_manager',
            '--hidden-import=webdriver_manager.chrome',
            '--hidden-import=bs4',
            '--hidden-import=requests',
            
            # Scipy hidden imports - critical for fixing ModuleNotFoundError
            '--hidden-import=scipy',
            '--hidden-import=scipy.stats',
            '--hidden-import=scipy.sparse',
            '--hidden-import=scipy.sparse.linalg',
            '--hidden-import=scipy.sparse.csgraph',
            '--hidden-import=scipy.special',
            '--hidden-import=scipy._lib',
            '--hidden-import=scipy._lib.messagestream',
            '--hidden-import=scipy.spatial',
            '--hidden-import=scipy.spatial.distance',
            '--hidden-import=scipy.integrate',
            '--hidden-import=scipy.interpolate',
            '--hidden-import=scipy.optimize',
            
            # Sklearn hidden imports - critical for fixing ModuleNotFoundError
            '--hidden-import=sklearn',
            '--hidden-import=sklearn.ensemble',
            '--hidden-import=sklearn.ensemble._forest',
            '--hidden-import=sklearn.ensemble._gb_losses',
            '--hidden-import=sklearn.tree',
            '--hidden-import=sklearn.tree._tree',
            '--hidden-import=sklearn.neighbors',
            '--hidden-import=sklearn.neighbors._partition_nodes',
            '--hidden-import=sklearn.utils',
            '--hidden-import=sklearn.utils._cython_blas',
            '--hidden-import=sklearn.utils._weight_vector',
            '--hidden-import=sklearn.utils.murmurhash',
            '--hidden-import=sklearn.utils.lgamma',
            '--hidden-import=sklearn.utils.sparsefuncs_fast',
            '--hidden-import=sklearn.utils._logistic_sigmoid',
            '--hidden-import=sklearn.utils._random',
            '--hidden-import=sklearn.utils._seq_dataset',
            '--hidden-import=sklearn.utils._typedefs',
            '--hidden-import=sklearn.metrics',
            '--hidden-import=sklearn.metrics.pairwise',
            '--hidden-import=sklearn.metrics._pairwise_distances_reduction',
            '--hidden-import=sklearn.metrics._dist_metrics',
            '--hidden-import=sklearn.preprocessing',
            '--hidden-import=sklearn.preprocessing._csr_polynomial_expansion',
            '--hidden-import=sklearn.linear_model',
            '--hidden-import=sklearn.svm',

            # Streamlit paketlerini topla
            '--collect-all=streamlit',
            '--collect-all=altair',
            '--collect-all=plotly',
            '--collect-all=scipy',
            '--collect-all=sklearn',
            '--collect-all=pyarrow',
            '--collect-all=selenium',

            # Exclude gereksizler (boyut küçültmek için)
            '--exclude-module=matplotlib.tests',
            '--exclude-module=IPython',
            '--exclude-module=jupyter',

            # Clean
            '--clean',
            '--noconfirm',
        ])

        elapsed = time.time() - start_time

        exe_path = Path('dist/RallyETA.exe')

        print("\n" + "="*60)
        print("[SUCCESS] BUILD BASARILI!")
        print("="*60)
        print(f"[TIME] Sure: {elapsed:.1f} saniye")
        print(f"[EXE] Dosya: {exe_path}")
        if exe_path.exists():
            print(f"[SIZE] Boyut: {exe_path.stat().st_size / (1024*1024):.1f} MB")

        # Build sonrası klasörleri kopyala
        print("\n[COPY] Gerekli klasorler kopyalaniyor...")
        dist_dir = Path('dist')

        # Boş data klasörleri oluştur
        (dist_dir / 'data' / 'raw').mkdir(parents=True, exist_ok=True)
        (dist_dir / 'data' / 'processed').mkdir(parents=True, exist_ok=True)
        (dist_dir / 'data' / 'external').mkdir(parents=True, exist_ok=True)
        (dist_dir / 'models' / 'rally_eta_v1').mkdir(parents=True, exist_ok=True)
        (dist_dir / 'logs').mkdir(parents=True, exist_ok=True)
        print("  [OK] Bos klasorler olusturuldu")

        print("\n[RUN] Calistirmak icin:")
        print("   cd dist")
        print("   ./RallyETA.exe")
        print("="*60 + "\n")

        return True

    except Exception as e:
        print("\n[ERROR] BUILD BASARISIZ!")
        print(str(e))
        return False

def create_installer():
    """Inno Setup ile installer oluştur (opsiyonel)"""
    print("\n[INSTALLER] Installer olusturmak ister misin? (y/n): ", end='')

    try:
        response = input().strip().lower()
    except EOFError:
        response = 'n'

    if response != 'y':
        return

    # Inno Setup script
    iss_content = """
[Setup]
AppName=Rally ETA Tahmin Sistemi
AppVersion=1.2
DefaultDirName={autopf}\\RallyETA
DefaultGroupName=Rally ETA
OutputDir=installer
OutputBaseFilename=RallyETA_Setup
Compression=lzma2
SolidCompression=yes
SetupIconFile=assets\\icon.ico

[Files]
Source: "dist\\RallyETA.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "config\\*"; DestDir: "{app}\\config"; Flags: ignoreversion recursesubdirs
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\\Rally ETA"; Filename: "{app}\\RallyETA.exe"
Name: "{group}\\Uninstall Rally ETA"; Filename: "{uninstallexe}"
Name: "{autodesktop}\\Rally ETA"; Filename: "{app}\\RallyETA.exe"

[Run]
Filename: "{app}\\RallyETA.exe"; Description: "Launch Rally ETA"; Flags: nowait postinstall skipifsilent
    """

    iss_path = Path('RallyETA.iss')
    iss_path.write_text(iss_content)

    print("[OK] RallyETA.iss olusturuldu")
    print("\nInno Setup ile derlemek icin:")
    print("  1. Inno Setup'i indir: https://jrsoftware.org/isinfo.php")
    print("  2. RallyETA.iss dosyasini ac")
    print("  3. Compile -> Build")

if __name__ == "__main__":
    success = build_exe()

    if success:
        create_installer()

        print("\n[DONE] Tamamlandi!")
        print("\nTest etmek icin:")
        print("  cd dist")
        print("  RallyETA.exe")
