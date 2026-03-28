"""
Rally ETA v2.0 - Ayarlar Sayfasi
Uygulama konfigurasyonu.
"""

import streamlit as st
from pathlib import Path
import sys
import tempfile

# Shared modulleri import et
sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.config import (
    get_db_path,
    get_kml_folder,
    get_model_dir,
    VERSION,
    BUILD_DATE,
    PROJECT_ROOT,
)
from shared.ui_components import render_page_header

_src_path = str(PROJECT_ROOT)
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)

from src.data.results_merge import merge_results_database


def render():
    """Ayarlar sayfasini render et."""
    render_page_header(
        "Calisma Alani Ayarlari",
        "Veritabani konumu, KML klasoru ve yerel calisma ortamini bu ekrandan duzenleyebilirsiniz.",
        badge="Yerel Yapilandirma",
        eyebrow="Ortam Yonetimi",
    )

    st.subheader("Veritabani")
    current_db = get_db_path()
    db_exists = Path(current_db).exists()

    if db_exists:
        st.success(f"Mevcut konum: {current_db}")
    else:
        st.warning(f"Veritabani bulunamadi: {current_db}")

    uploaded_db = st.file_uploader(
        "Veritabani dosyasi yukle (surukle-birak)",
        type=["db"],
        key="settings_db_upload",
    )

    if uploaded_db:
        save_location = st.radio(
            "Nereye kaydedilsin?",
            ["Varsayilan konum", "Ozel konum belirt"],
            horizontal=True,
        )

        if save_location == "Ozel konum belirt":
            custom_path = st.text_input(
                "Tam dosya yolu",
                value=str(PROJECT_ROOT / "data" / "raw" / "rally_results.db"),
                help="Ornek: C:/RallyData/rally_results.db",
            )
            save_path = Path(custom_path)
        else:
            save_path = PROJECT_ROOT / "data" / "raw" / "rally_results.db"

        st.info(f"Kaydedilecek konum: {save_path}")
        if save_path.exists():
            st.caption(
                "Hedef veritabani mevcut. Yuklenen dosya ustune yazilmayacak; "
                "birlestirme, yedek ve conflict log akisi kullanilacak."
            )

        action_label = "Veritabanini Birlestir" if save_path.exists() else "Veritabanini Kaydet"
        if st.button(action_label, type="primary"):
            try:
                save_path.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
                    tmp.write(uploaded_db.getbuffer())
                    tmp_path = tmp.name

                if save_path.exists():
                    summary = merge_results_database(
                        master_db_path=str(save_path),
                        incoming_db_path=tmp_path,
                        backup_dir=str(PROJECT_ROOT / "backups"),
                        report_dir=str(PROJECT_ROOT / "reports"),
                    )
                    st.session_state.db_path = str(save_path)
                    st.success(
                        f"Birlestirme tamamlandi: +{summary.inserted_rows} yeni, "
                        f"{summary.skipped_rows} tekrar kayit atlandi, "
                        f"{summary.conflict_rows} conflict loglandi"
                    )
                    st.caption(f"Birlestirme logu: {summary.merge_log_path}")
                else:
                    with open(save_path, "wb") as handle:
                        handle.write(uploaded_db.getbuffer())
                    st.session_state.db_path = str(save_path)
                    st.success(f"Veritabani kaydedildi: {save_path}")

                Path(tmp_path).unlink(missing_ok=True)
                st.rerun()
            except Exception as e:
                st.error(f"Hata: {e}")

    with st.expander("Manuel veritabani yolunu degistir"):
        new_db = st.text_input(
            "Veritabani yolu",
            value=current_db,
            key="manual_db_path",
        )
        if new_db and new_db != current_db:
            if st.button("Yolu guncelle"):
                if Path(new_db).exists():
                    st.session_state.db_path = new_db
                    st.success("Veritabani yolu guncellendi!")
                    st.rerun()
                else:
                    try:
                        Path(new_db).parent.mkdir(parents=True, exist_ok=True)
                        import sqlite3

                        conn = sqlite3.connect(new_db)
                        conn.close()
                        st.session_state.db_path = new_db
                        st.success(f"Yeni veritabani olusturuldu: {new_db}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Hata: {e}")

    st.markdown("---")

    st.subheader("KML Klasoru")
    current_kml = get_kml_folder()
    kml_exists = Path(current_kml).exists()

    if kml_exists:
        st.success(f"Konum: {current_kml}")
    else:
        st.warning(f"Klasor bulunamadi: {current_kml}")

    new_kml = st.text_input("Yeni KML klasoru", key="new_kml_folder")
    if new_kml and st.button("KML klasorunu guncelle"):
        kml_path = Path(new_kml)
        if kml_path.exists():
            st.session_state.kml_folder = new_kml
            st.success("Klasor guncellendi!")
            st.rerun()
        else:
            try:
                kml_path.mkdir(parents=True, exist_ok=True)
                st.session_state.kml_folder = new_kml
                st.success(f"Klasor olusturuldu ve ayarlandi: {new_kml}")
                st.rerun()
            except Exception as e:
                st.error(f"Hata: {e}")

    st.markdown("---")

    st.subheader("Model Klasoru")
    st.text(f"Konum: {get_model_dir()}")

    st.markdown("---")

    st.subheader("Hakkinda")
    st.markdown(f"**Rally Result Prediction v{VERSION}** - Stage result and notional time prediction system")
    st.markdown(f"Build: {BUILD_DATE}")

    st.markdown("---")

    with st.expander("Tani bilgileri"):
        st.markdown("**Uygulama konumu:**")
        st.text(f"PROJECT_ROOT: {PROJECT_ROOT}")

        st.markdown("**Session state:**")
        for key, value in st.session_state.items():
            if not key.startswith("_"):
                st.text(f"{key}: {value}")

        st.markdown("**Sistem yolları:**")
        st.text(f"Python: {sys.executable}")
        st.text(f"Working Dir: {Path.cwd()}")
        st.text(f"Frozen: {getattr(sys, 'frozen', False)}")
