"""
Rally ETA v2.0 - Merkezi Konfigürasyon
Tüm sabit değerler ve varsayılan yollar burada tanımlanır.
"""

from pathlib import Path
import streamlit as st
import sys
import os

def get_app_root() -> Path:
    """
    Uygulama kök dizinini döndür.
    PyInstaller exe için: exe'nin bulunduğu klasör
    Normal çalışma için: segment klasörünün bir üstü
    """
    if getattr(sys, 'frozen', False):
        # PyInstaller exe - exe'nin bulunduğu klasörü kullan
        return Path(sys.executable).parent
    else:
        # Normal Python çalışması
        return Path(__file__).parent.parent.parent

# Proje kök dizini
PROJECT_ROOT = get_app_root()

# Varsayılan yollar
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "raw" / "rally_results.db"
DEFAULT_KML_FOLDER = PROJECT_ROOT / "kml-kmz"
DEFAULT_MODEL_DIR = PROJECT_ROOT / "models"

# Alternatif DB yolları (sırayla kontrol edilir)
DB_SEARCH_PATHS = [
    PROJECT_ROOT / "data" / "raw" / "rally_results.db",
    PROJECT_ROOT / "rally_results.db",  # Exe yanında
    Path.home() / "RallyETA" / "rally_results.db",  # Kullanıcı klasörü
    Path("data/raw/rally_results.db"),
]

# Alternatif KML yolları
KML_SEARCH_PATHS = [
    PROJECT_ROOT / "kml-kmz",
    Path.home() / "RallyETA" / "kml-kmz",
]

# Zemin tipleri
SURFACE_TYPES = ["gravel", "asphalt", "mixed", "snow"]

# Durum değerleri
VALID_STATUSES = ["FINISHED", "OK", "DNF", "DNS", "RETIRED"]
FINISHED_STATUSES = ["FINISHED", "OK"]

# Model dosya adı
MODEL_FILENAME = "geometric_model_latest.pkl"

# UI sabitleri
MAX_TABLE_ROWS = 50
PAGE_ICON = "R"
PAGE_TITLE = "Rally Result Prediction"

# Versiyon
VERSION = "2.0.1"
BUILD_DATE = "2026-03-29"


def init_session_state():
    """Session state'i varsayılan değerlerle başlat."""

    # Database path
    if 'db_path' not in st.session_state:
        for path in DB_SEARCH_PATHS:
            if path.exists():
                st.session_state.db_path = str(path)
                break
        else:
            st.session_state.db_path = str(DEFAULT_DB_PATH)

    # KML folder
    if 'kml_folder' not in st.session_state:
        for path in KML_SEARCH_PATHS:
            if path.exists():
                st.session_state.kml_folder = str(path)
                break
        else:
            st.session_state.kml_folder = str(DEFAULT_KML_FOLDER)

    # Model directory
    if 'model_dir' not in st.session_state:
        st.session_state.model_dir = str(DEFAULT_MODEL_DIR)

    # Predictions cache
    if 'predictions' not in st.session_state:
        st.session_state.predictions = []


def get_db_path() -> str:
    """Aktif database yolunu döndür."""
    return st.session_state.get('db_path', str(DEFAULT_DB_PATH))


def get_kml_folder() -> str:
    """Aktif KML klasör yolunu döndür."""
    return st.session_state.get('kml_folder', str(DEFAULT_KML_FOLDER))


def get_model_dir() -> str:
    """Aktif model klasör yolunu döndür."""
    return st.session_state.get('model_dir', str(DEFAULT_MODEL_DIR))


def get_model_path() -> Path:
    """Tam model dosya yolunu döndür."""
    return Path(get_model_dir()) / MODEL_FILENAME
