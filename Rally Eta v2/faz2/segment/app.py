"""
Rally ETA v2.0 - Ana Router
Streamlit Web Interface - Segmented Version
"""

import streamlit as st
import sys
from pathlib import Path

# Proje yapısını ayarla
SEGMENT_ROOT = Path(__file__).parent
PROJECT_ROOT = SEGMENT_ROOT.parent

# Path'lere ekle
sys.path.insert(0, str(SEGMENT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

# Shared modülleri import et
from shared.config import init_session_state, PAGE_TITLE, PAGE_ICON, get_db_path
from shared.db_helpers import get_database_info, ensure_all_tables
from shared.data_loaders import get_kml_files
from shared.ui_components import apply_custom_css, show_db_status_sidebar

# Page modüllerini import et
from pages import home, scraper, kml_manager, training, prediction, settings


# ========== PAGE CONFIG ==========
st.set_page_config(
    page_title=PAGE_TITLE,
    page_icon=PAGE_ICON,
    layout="wide",
    initial_sidebar_state="expanded"
)

# ========== INITIALIZATION ==========
# Custom CSS
apply_custom_css()

# Session state
init_session_state()

# Tabloları oluştur
active_db_path = get_db_path()
if st.session_state.get("_schema_ready_db") != active_db_path:
    ensure_all_tables(active_db_path)
    st.session_state["_schema_ready_db"] = active_db_path


# ========== SIDEBAR ==========
PAGE_META = {
    "Ana Sayfa": "Kontrol Merkezi",
    "Veri Cek": "Veri Alim Merkezi",
    "KML Yonetimi": "Geometrik Veriler",
    "Model Egitimi": "Model Egitimi",
    "Tahmin Yap": "Tahmin Laboratuvari",
    "Ayarlar": "Calisma Alani Ayarlari",
}

st.sidebar.markdown(
    """
    <section class="sidebar-brand">
        <div class="sidebar-brand__eyebrow">Rally ETA v2</div>
        <h2>Ralli operasyon merkezi</h2>
        <p>Sonuc toplama, etap geometrisi ve tahmin akislari tek masaustu ekranda bir arada.</p>
    </section>
    """,
    unsafe_allow_html=True,
)

db_info = get_database_info()
kml_files = get_kml_files()
show_db_status_sidebar(db_info, kml_count=len(kml_files))

st.sidebar.markdown(
    '<div class="sidebar-section-label" style="margin-top: 1rem;">Gezinme</div>',
    unsafe_allow_html=True,
)

page_options = list(PAGE_META.keys())
page_override = st.session_state.pop("selected_page_override", None)
if page_override in page_options:
    st.session_state["selected_page"] = page_override

page = st.sidebar.radio(
    "Sayfa",
    page_options,
    key="selected_page",
    format_func=lambda option: PAGE_META.get(option, option),
    label_visibility="collapsed",
)

st.sidebar.markdown(
    """
    <div class="sidebar-footer">
        Guncellenen shell, daha hizli tarama ve daha temiz bir manuel test akisi icin optimize edildi.
    </div>
    """,
    unsafe_allow_html=True,
)


# ========== PAGE ROUTING ==========
if page == "Ana Sayfa":
    home.render()

elif page == "Veri Cek":
    scraper.render()

elif page == "KML Yonetimi":
    kml_manager.render()

elif page == "Model Egitimi":
    training.render()

elif page == "Tahmin Yap":
    prediction.render()

elif page == "Ayarlar":
    settings.render()
