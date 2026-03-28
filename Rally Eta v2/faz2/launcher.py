"""
Rally ETA v2.0 - Launcher
PyInstaller frozen app icin olusturulmustur.
"""
import sys
import os
from pathlib import Path


_STDIO_HANDLES = []


def get_resource_path(relative_path):
    """PyInstaller frozen app icin kaynak yolunu dondur."""
    if hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS) / relative_path
    return Path(__file__).parent / relative_path


def get_runtime_root() -> Path:
    """Kalici cikti ve log dosyalari icin uygun kok dizini dondur."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def ensure_stdio(runtime_root: Path):
    """Windowed exe modunda bos olabilen stdio akisini log dosyasina bagla."""
    if sys.stdout is not None and sys.stderr is not None:
        return

    log_dir = runtime_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "launcher.log"
    log_handle = open(log_path, "a", encoding="utf-8", buffering=1)
    _STDIO_HANDLES.append(log_handle)

    if sys.stdout is None:
        sys.stdout = log_handle
    if sys.stderr is None:
        sys.stderr = log_handle

if __name__ == "__main__":
    runtime_root = get_runtime_root()
    ensure_stdio(runtime_root)

    # Kullanici seviyesindeki ~/.streamlit/config.toml ayarlari exe'yi bozmasin.
    # Biz masaustu calisma modunda net olarak production/headless config istiyoruz.
    os.environ["STREAMLIT_GLOBAL_DEVELOPMENT_MODE"] = "false"
    os.environ["STREAMLIT_SERVER_HEADLESS"] = "true"
    os.environ["STREAMLIT_SERVER_PORT"] = "8501"
    os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"

    # Calisma dizinini ayarla
    if hasattr(sys, '_MEIPASS'):
        os.chdir(sys._MEIPASS)

    # Path'leri ayarla
    base_path = Path(sys._MEIPASS) if hasattr(sys, '_MEIPASS') else Path(__file__).parent
    sys.path.insert(0, str(base_path))
    sys.path.insert(0, str(base_path / "segment"))

    # Streamlit'i baslat
    from streamlit.web import cli as stcli
    import webbrowser
    import threading
    import time

    def open_browser():
        time.sleep(2)  # Streamlit'in başlamasını bekle
        webbrowser.open('http://localhost:8501')

    # Browser'ı ayrı thread'de aç
    threading.Thread(target=open_browser, daemon=True).start()

    app_path = get_resource_path("segment/app.py")
    if not app_path.exists():
        app_path = get_resource_path("app.py")
    sys.argv = ["streamlit", "run", str(app_path),
                "--server.headless", "true",
                "--browser.gatherUsageStats", "false"]
    sys.exit(stcli.main())
