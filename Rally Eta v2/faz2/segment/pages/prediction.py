"""
Rally ETA v2.0 - Tahmin Sayfasi
Tekli, toplu, KML bazli ve canli TOSFED tahmin islemleri.
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
import sys
import tempfile
import sqlite3
import re
from pathlib import Path

# Shared modülleri import et
sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.config import get_db_path, get_model_dir, get_model_path, PROJECT_ROOT, SURFACE_TYPES
from shared.db_helpers import get_database_info
from shared.data_loaders import get_driver_list
from shared.ui_components import (
    render_page_header,
    render_stat_cards,
    show_html_table,
    create_stage_inputs,
    format_surface_label,
    format_confidence_label,
    format_compare_status_label,
    format_boolean_label,
)

# src modulleri
_src_path = str(PROJECT_ROOT)
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)

from src.prediction.manual_calculator import (
    ManualCalculationResult,
    calculate_manual_stage_estimate,
    format_manual_time,
    parse_manual_time_input,
)


MANUAL_REFERENCE_STAGE_COUNT = 6


def render():
    """Tahmin sayfasini render et."""
    render_page_header(
        "Tahmin Laboratuvari",
        "Canli TOSFED akisi, KML bazli analiz ve manuel senaryolar uzerinden notional time tahminlerini calistirin.",
        badge="Tahmin Operasyonlari",
        eyebrow="Zamanlama Zekasi",
    )

    # Database kontrolü
    db_info = get_database_info()
    if not db_info['exists']:
        st.error("Veritabani bulunamadi!")
        st.stop()

    section_options = ["Canli Tahmin", "KML Tahmin", "Manuel Tahmin", "Toplu Tahmin", "Degerlendirme"]
    section_override = st.session_state.pop("prediction_section_override", None)
    if section_override in section_options:
        st.session_state["prediction_section"] = section_override

    section = st.radio(
        "Tahmin Bolumu",
        section_options,
        horizontal=True,
        key="prediction_section",
        label_visibility="collapsed",
    )

    _render_workflow_context_banner("Tahmin Yap", dismiss_key="prediction_workflow_context_dismiss")

    if section == "Canli Tahmin":
        _render_live_prediction()
    elif section == "KML Tahmin":
        _render_kml_prediction()
    elif section == "Manuel Tahmin":
        _render_single_prediction()
    elif section == "Toplu Tahmin":
        _render_batch_prediction()
    elif section == "Degerlendirme":
        _render_prediction_evaluation()


def _get_workflow_context(target_page=None):
    context = st.session_state.get("workflow_context")
    if not isinstance(context, dict):
        return None
    if target_page and context.get("action_target_page") != target_page:
        return None
    return context


def _clear_workflow_context():
    st.session_state.pop("workflow_context", None)


def _render_workflow_context_banner(target_page, dismiss_key):
    context = _get_workflow_context(target_page)
    if not context:
        return

    details = [
        context.get("issue_title") or context.get("issue_type"),
        f"Rally {context['rally_id']}" if context.get("rally_id") else None,
        context.get("stage_id"),
        context.get("driver_name"),
    ]
    summary = " | ".join(part for part in details if part)
    st.info(summary)
    if context.get("recommended_action"):
        st.caption(f"Onerilen aksiyon: {context['recommended_action']}")
    if st.button("Aksiyon Baglamini Temizle", key=dismiss_key):
        _clear_workflow_context()
        st.rerun()


def _open_prediction_issue_action(issue):
    target_page = issue.get("action_target_page")
    target_section = issue.get("action_target_section")

    st.session_state["workflow_context"] = {
        "prediction_id": issue.get("prediction_id"),
        "issue_type": issue.get("issue_type"),
        "issue_title": issue.get("issue_title"),
        "recommended_action": issue.get("recommended_action"),
        "rally_id": issue.get("rally_id"),
        "stage_id": issue.get("stage_id"),
        "driver_id": issue.get("driver_id"),
        "driver_name": issue.get("driver_name"),
        "action_target_page": target_page,
        "action_target_section": target_section,
    }

    if target_page:
        st.session_state["selected_page_override"] = target_page
    if target_page == "KML Yonetimi":
        st.session_state["kml_manager_section_override"] = target_section
        if issue.get("rally_id"):
            st.session_state["kml_manager_rally_override"] = str(issue["rally_id"])
        if issue.get("stage_id"):
            st.session_state["kml_manager_stage_override"] = str(issue["stage_id"])
    elif target_page == "Veri Cek":
        st.session_state["scraper_section_override"] = target_section
    elif target_page == "Tahmin Yap":
        st.session_state["prediction_section_override"] = target_section

    st.rerun()


# =============================================================================
# CANLI TAHMIN (TOSFED URL)
# =============================================================================

def _render_live_prediction():
    """Canli TOSFED verisine dayali tahmin."""
    st.subheader("Canli Tahmin")
    st.info("TOSFED URL'si girerek devam eden ralliden canli tahmin yapin.")

    # TOSFED URL girisi
    tosfed_url = st.text_input(
        "TOSFED Sonuc URL'si",
        placeholder="https://sonuc.tosfed.org.tr/yaris/171/ralli_etap_sonuclari/?etp=7",
        key="tosfed_url"
    )

    # Veri cekme butonu
    if st.button("Verileri Cek", type="secondary", key="fetch_tosfed"):
        if not tosfed_url:
            st.warning("Lutfen bir TOSFED URL'si girin.")
            return

        # URL'den rally_id cikar
        rally_id_match = re.search(r'/yaris/(\d+)', tosfed_url)
        if not rally_id_match:
            st.error("Gecersiz URL! Ornek: https://sonuc.tosfed.org.tr/yaris/171/ralli_etap_sonuclari/")
            return

        with st.spinner("TOSFED'den veriler cekiliyor..."):
            try:
                from src.scraper.tosfed_sonuc_scraper import TOSFEDSonucScraper

                scraper = TOSFEDSonucScraper()
                rally_data = scraper.fetch_rally_from_url(tosfed_url)

                if not rally_data:
                    st.error("Ralli verisi alinamadi! URL'yi kontrol edin.")
                    return

                # Session state'e kaydet
                st.session_state['live_rally_data'] = rally_data
                st.session_state['live_rally_url'] = tosfed_url

                st.success(f"Basarili! {rally_data['rally_name']} - {len(rally_data['stages'])} etap bulundu")

            except Exception as e:
                st.error(f"Veri cekme hatasi: {e}")
                return

    # Cekilen veriyi goster
    if 'live_rally_data' not in st.session_state:
        st.caption("Yukaridaki alana TOSFED sonuc URL'si yapistirin ve 'Verileri Cek' butonuna basin.")
        return

    rally_data = st.session_state['live_rally_data']
    stages = rally_data.get('stages', [])

    if not stages:
        st.warning("Bu rallide etap verisi bulunamadi.")
        return

    st.markdown("---")

    # Ralli ozeti
    st.subheader(f"{rally_data['rally_name']}")
    col1, col2, col3 = st.columns(3)
    col1.metric("Rally ID", rally_data['rally_id'])
    col2.metric("Etap Sayisi", len(stages))
    col3.metric("Zemin", format_surface_label(rally_data.get('surface', 'gravel')))

    # Pilot listesini cikar (tum etaplardan)
    all_drivers = {}
    for stage in stages:
        for result in stage.get('results', []):
            dname = result.get('driver_name', '')
            dclass = result.get('car_class', '')
            if dname and dname not in all_drivers:
                all_drivers[dname] = dclass

    if not all_drivers:
        st.warning("Pilotlar bulunamadi!")
        return

    st.markdown("---")

    # Tahmin edilecek etap secimi
    st.subheader("Tahmin Ayarlari")

    # Etap secimi - bir sonraki etap onerilir
    stage_options = [f"SS{s['stage_number']}: {s.get('stage_name', '')}" for s in stages]
    suggested_idx = rally_data.get('suggested_stage', len(stages)) - 1
    suggested_idx = min(max(0, suggested_idx), len(stage_options) - 1)

    predict_stage_idx = st.selectbox(
        "Tahmin Edilecek Etap",
        range(len(stage_options)),
        index=suggested_idx,
        format_func=lambda i: stage_options[i],
        key="live_predict_stage"
    )
    predict_stage_num = stages[predict_stage_idx]['stage_number']

    # Pilot secimi
    driver_labels = [f"{name} ({cls})" for name, cls in all_drivers.items()]
    selected_driver_idx = st.selectbox(
        "Pilot Sec",
        range(len(driver_labels)),
        format_func=lambda i: driver_labels[i],
        key="live_driver_select"
    )
    selected_driver_name = list(all_drivers.keys())[selected_driver_idx]
    selected_driver_class = list(all_drivers.values())[selected_driver_idx]

    # Zemin secimi
    col1, col2 = st.columns(2)
    with col1:
        surface = st.selectbox(
            "Zemin Tipi",
            SURFACE_TYPES,
            index=SURFACE_TYPES.index(rally_data.get('surface', 'gravel'))
            if rally_data.get('surface', 'gravel') in SURFACE_TYPES else 0,
            format_func=format_surface_label,
            key="live_surface",
        )
    with col2:
        # KML dosyasi (opsiyonel)
        uploaded_kml = st.file_uploader("KML Dosyasi (opsiyonel)", type=['kml', 'kmz'], key="live_kml_upload")

    # Onceki etap sonuclari
    _show_driver_rally_summary(stages, selected_driver_name, selected_driver_class, predict_stage_num)

    st.markdown("---")

    # Tahmin butonu
    if st.button("Onceki Etaplari Karsilastir ve Siradakini Tahmin Et", type="primary", use_container_width=True, key="live_predict_btn"):
        with st.spinner("Tahmin hesaplaniyor..."):
            try:
                # KML analiz (opsiyonel)
                geo_features = None
                if uploaded_kml:
                    geo_features = _analyze_kml_file(uploaded_kml)

                result = _run_live_prediction(
                    rally_data=rally_data,
                    driver_name=selected_driver_name,
                    driver_class=selected_driver_class,
                    predict_stage_num=predict_stage_num,
                    surface=surface,
                    geo_features=geo_features
                )

                st.success("Tahmin tamamlandi!")

                # Sonuclari goster
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Tahmini Zaman", result['predicted_time_str'])
                col2.metric("Hiz (km/h)", f"{result['predicted_speed_kmh']:.1f}")
                col3.metric("Oran", f"{result['predicted_ratio']:.3f}")
                col4.metric("Guven", format_confidence_label(result.get('confidence_level', 'MEDIUM')))

                comparison_summary = result.get('comparison_summary')
                if comparison_summary:
                    st.info(
                        "Onceki etap karsilastirmasi: "
                        f"{comparison_summary.get('matched_count', 0)} eslesen, "
                        f"{comparison_summary.get('missing_actual_count', 0)} gercek sonucu eksik, "
                        f"ortalama hata %{comparison_summary.get('avg_error_pct') if comparison_summary.get('avg_error_pct') is not None else '-'}"
                    )

                # Detayli aciklama
                with st.expander("Detayli Aciklama", expanded=True):
                    st.markdown(result.get('explanation', ''))

            except Exception as e:
                st.error(f"Tahmin hatasi: {e}")
                import traceback
                st.code(traceback.format_exc())


def _show_driver_rally_summary(stages, driver_name, driver_class, predict_stage_num):
    """Pilotun bu rallideki onceki etap sonuclarini goster."""
    st.markdown("#### Pilotun Bu Rallide Performansi")

    rows = []
    for stage in stages:
        if stage['stage_number'] >= predict_stage_num:
            continue  # Tahmin edilecek etaptan onceki etaplari goster

        for result in stage.get('results', []):
            if result.get('driver_name') == driver_name:
                rows.append({
                    'Etap': f"SS{stage['stage_number']}",
                    'Isim': stage.get('stage_name', ''),
                    'Sure': result.get('time_str', '-'),
                    'Sinif': result.get('car_class', '-'),
                    'Sira': result.get('position', '-'),
                })
                break

    if rows:
        df = pd.DataFrame(rows)
        show_html_table(df)
    else:
        st.caption("Henuz etap verisi yok (ilk etap tahmini)")


def _run_live_prediction(rally_data, driver_name, driver_class, predict_stage_num,
                         surface, geo_features=None):
    """Canli TOSFED verisine dayali tahmin."""
    return _get_prediction_service().compare_previous_and_predict_next(
        rally_data=rally_data,
        driver_name=driver_name,
        driver_class=driver_class,
        predict_stage_num=predict_stage_num,
        surface=surface,
        geo_features=geo_features,
    )


# =============================================================================
# KML TAHMIN
# =============================================================================

def _render_kml_prediction():
    """KML bazli tahmin - Ana ozellik."""
    st.subheader("KML Bazli Tahmin")
    st.info("KML/KMZ dosyasi yukleyin, etap karakteristikleri analiz edilsin ve pilotun tahmini suresi hesaplansin.")

    # KML/KMZ yükleme
    uploaded_file = st.file_uploader(
        "KML veya KMZ Dosyasi Yukle",
        type=['kml', 'kmz'],
        key="kml_predict_upload"
    )

    if not uploaded_file:
        st.warning("Lutfen bir KML/KMZ dosyasi yukleyin.")
        return

    # Dosyayı geçici olarak kaydet
    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{uploaded_file.name.split('.')[-1]}") as tmp:
        tmp.write(uploaded_file.getbuffer())
        tmp_path = tmp.name

    # KML analizi
    try:
        from src.stage_analyzer.kml_parser import parse_kml_file
        from src.stage_analyzer.kml_analyzer import KMLAnalyzer

        # KML'den etapları parse et
        kml_stages = parse_kml_file(tmp_path)

        if not kml_stages:
            st.error("KML dosyasinda etap bulunamadi!")
            return

        # Etap seçimi (birden fazla varsa)
        if len(kml_stages) > 1:
            stage_labels = [f"{i+1}. {s.name}" for i, s in enumerate(kml_stages)]
            selected_idx = st.selectbox(
                "Etap Sec",
                range(len(kml_stages)),
                format_func=lambda i: stage_labels[i],
                key="kml_stage_select"
            )
            selected_stage = kml_stages[selected_idx]
        else:
            selected_stage = kml_stages[0]
            st.success(f"Etap: {selected_stage.name}")

        # Analiz parametreleri
        with st.expander("Analiz Parametreleri", expanded=False):
            col1, col2 = st.columns(2)
            with col1:
                geom_step = st.number_input("Geometri Ornekleme (m)", 5.0, 50.0, 10.0, 5.0, key="kml_geom")
                elev_step = st.number_input("Yukselti Ornekleme (m)", 50.0, 500.0, 200.0, 50.0, key="kml_elev")
            with col2:
                smoothing = st.number_input("Smoothing Pencere", 3, 15, 7, 2, key="kml_smooth")
                hairpin_thresh = st.number_input("Hairpin Esik (m)", 10.0, 50.0, 20.0, 1.0, key="kml_hairpin")

        # Zemin seçimi
        surface = st.selectbox("Zemin Tipi", SURFACE_TYPES, format_func=format_surface_label, key="kml_surface")

        # Analiz butonu
        if st.button("Etabi Analiz Et", type="secondary", key="analyze_kml"):
            with st.spinner("KML analiz ediliyor..."):
                # Geçici KML oluştur (tek etap için)
                temp_kml = Path(tempfile.gettempdir()) / f"stage_analysis_{datetime.now().strftime('%H%M%S')}.kml"
                kml_content = '<?xml version="1.0" encoding="UTF-8"?>\n'
                kml_content += '<kml xmlns="http://www.opengis.net/kml/2.2">\n'
                kml_content += '<Document>\n'
                kml_content += f'<Placemark><name>{selected_stage.name}</name>\n'
                kml_content += '<LineString><coordinates>\n'
                for lat, lon in selected_stage.coordinates:
                    kml_content += f'{lon},{lat},0 '
                kml_content += '\n</coordinates></LineString></Placemark>\n'
                kml_content += '</Document>\n</kml>'

                with open(temp_kml, 'w', encoding='utf-8') as f:
                    f.write(kml_content)

                # Analiz
                analyzer = KMLAnalyzer(
                    geom_step=float(geom_step),
                    smoothing_window=int(smoothing),
                    elev_step=float(elev_step)
                )
                geo_features = analyzer.analyze_kml(str(temp_kml), hairpin_threshold=float(hairpin_thresh))
                temp_kml.unlink()  # Temizle

                # Session state'e kaydet
                st.session_state['kml_geo_features'] = geo_features
                st.session_state['kml_stage_name'] = selected_stage.name
                st.session_state['kml_analyzed_surface'] = surface

        # Geometrik özellikler göster
        if 'kml_geo_features' in st.session_state:
            geo = st.session_state['kml_geo_features']

            st.markdown("---")
            st.subheader("Etap Karakteristikleri")

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Mesafe", f"{geo.get('distance_km', 0):.2f} km")
            col2.metric("Hairpin", f"{geo.get('hairpin_count', 0)}")
            col3.metric("Toplam Tirmanis", f"{geo.get('total_ascent', 0):.0f} m")
            col4.metric("Toplam Inis", f"{geo.get('total_descent', 0):.0f} m")

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Hairpin/km", f"{geo.get('hairpin_density', 0):.2f}")
            col2.metric("Ort. Egrilik", f"{geo.get('avg_curvature', 0):.4f}")
            col3.metric("Max Egim", f"{geo.get('max_grade', 0):.1f}%")
            col4.metric("Duz Oran", f"{geo.get('straight_ratio', 0)*100:.1f}%")

            st.markdown("---")

            # Pilot seçimi ve tahmin
            st.subheader("Pilot Tahmini")

            drivers = get_driver_list()
            if not drivers:
                st.warning("Veritabaninda pilot bulunamadi!")
                return

            # Pilot seçimi
            driver_options = {
                f"{d['driver_name']} ({d.get('normalized_class', d['car_class'])})": d
                for d in drivers
            }
            selected_driver_label = st.selectbox(
                "Pilot Sec",
                list(driver_options.keys()),
                key="kml_driver_select"
            )
            selected_driver = driver_options[selected_driver_label]

            # Tahmin butonu
            if st.button("Tahmin Et", type="primary", use_container_width=True, key="kml_predict"):
                with st.spinner("Tahmin hesaplaniyor..."):
                    try:
                        result = _run_kml_prediction(
                            driver_name=selected_driver['driver_name'],
                            geo_features=geo,
                            surface=st.session_state.get('kml_analyzed_surface', 'gravel'),
                            stage_name=st.session_state.get('kml_stage_name', 'KML Etap')
                        )

                        st.success("Tahmin tamamlandi!")

                        # Sonuçları göster
                        col1, col2, col3, col4 = st.columns(4)
                        col1.metric("Tahmini Zaman", result['predicted_time_str'])
                        col2.metric("Hiz (km/h)", f"{result['predicted_speed_kmh']:.1f}")
                        col3.metric("Oran", f"{result['predicted_ratio']:.3f}")
                        col4.metric("Guven", format_confidence_label(result.get('confidence_level', 'MEDIUM')))

                        # Detaylı açıklama
                        with st.expander("Detayli Aciklama", expanded=True):
                            st.markdown(result.get('explanation', ''))

                    except Exception as e:
                        st.error(f"Tahmin hatasi: {e}")

    except Exception as e:
        st.error(f"KML analiz hatasi: {e}")


def _run_kml_prediction(driver_name: str, geo_features: dict, surface: str, stage_name: str) -> dict:
    """KML bazlı tahmin çalıştır - normalized_class ile."""
    return _get_prediction_service().predict_kml_stage(
        driver_name=driver_name,
        geo_features=geo_features,
        surface=surface,
        stage_name=stage_name,
    )


# =============================================================================
# MANUEL TAHMIN
# =============================================================================

def _render_single_prediction():
    """Manuel tekli tahmin bölümü."""
    st.subheader("Manuel Tahmin")
    st.caption("Etap uzunlugu ve zemin girerek basit tahmin")

    drivers = get_driver_list()
    if not drivers:
        st.warning("Pilot bulunamadi!")
        return

    # Pilot seçimi
    selected_driver = create_driver_selector(drivers, key="single_driver")
    if not selected_driver:
        return

    # Etap bilgileri
    stage_info = create_stage_inputs(prefix="single_")

    # Tahmin butonu
    if st.button("Tahmin Et", type="primary", use_container_width=True, key="manual_predict"):
        with st.spinner("Tahmin yapiliyor..."):
            try:
                result = _run_prediction(
                    driver_id=selected_driver['driver_id'],
                    driver_name=selected_driver['driver_name'],
                    stage_length_km=stage_info['stage_length_km'],
                    surface=stage_info['surface'],
                    stage_number=stage_info['stage_number']
                )

                st.success("Tahmin tamamlandi!")

                # Sonuçlar
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Tahmini Zaman", result['predicted_time_str'])
                col2.metric("Hiz (km/h)", f"{result['predicted_speed_kmh']:.1f}")
                col3.metric("Oran", f"{result['predicted_ratio']:.3f}")
                col4.metric("Guven", format_confidence_label(result.get('confidence_level', 'MEDIUM')))

                # Detaylı açıklama
                with st.expander("Detayli Aciklama"):
                    st.write(result.get('explanation', 'N/A'))

            except Exception as e:
                st.error(f"Hata: {e}")


# Override the older manual prediction view with the new commissioner workflow.
def _render_single_prediction():
    """Komiser odakli manuel hesap bolumu."""
    st.subheader("Manuel Hesap")
    st.caption(
        "Önceki etap verilerine göre hedef etap için manuel tahmin hesaplanır. "
        "Aynı sınıfın best dereceleri kullanılmalıdır."
    )
    st.info(
        "Bu modül ham sınıf girdisiyle çalışır. K3, S3, Rally3 gibi sınıflar otomatik eşitlenmez "
        "ve genel best fallback uygulanmaz."
    )

    class_name = st.text_input(
        "Sınıf",
        key="manual_calc_class",
        placeholder="Örn. K3 / S3 / Rally3",
        help="Bu alan bilgi amaçlıdır; sistem burada otomatik sınıf normalizasyonu yapmaz.",
    )

    st.markdown("#### Referans Etap Girişi")
    st.caption("Km + Best Derece + Pilot Süresi birlikte doldurulan satırlar hesaba katılır.")

    header_cols = st.columns([1.0, 1.0, 1.2, 1.2])
    header_cols[0].markdown("**Etap**")
    header_cols[1].markdown("**Km**")
    header_cols[2].markdown("**Best Derece**")
    header_cols[3].markdown("**Pilot Süresi**")

    reference_rows = []
    for index in range(1, MANUAL_REFERENCE_STAGE_COUNT + 1):
        row_cols = st.columns([1.0, 1.0, 1.2, 1.2])
        row_cols[0].markdown(f"**Etap {index}**")
        km_value = row_cols[1].number_input(
            f"Etap {index} Km",
            min_value=0.0,
            step=0.1,
            format="%.3f",
            key=f"manual_ref_{index}_km",
            label_visibility="collapsed",
        )
        best_time = row_cols[2].text_input(
            f"Etap {index} Best Derece",
            key=f"manual_ref_{index}_best",
            placeholder="01:10:800",
            label_visibility="collapsed",
        )
        driver_time = row_cols[3].text_input(
            f"Etap {index} Pilot Süresi",
            key=f"manual_ref_{index}_driver",
            placeholder="01:12:200",
            label_visibility="collapsed",
        )
        reference_rows.append(
            {
                "label": f"Etap {index}",
                "km": km_value,
                "best_time": best_time,
                "driver_time": driver_time,
            }
        )

    st.markdown("#### Hedef Etap")
    target_cols = st.columns(2)
    target_km = target_cols[0].number_input(
        "Hedef Etap Km",
        min_value=0.0,
        step=0.1,
        format="%.3f",
        key="manual_target_km",
    )
    target_best = target_cols[1].text_input(
        "Hedef Etap Best Derece",
        key="manual_target_best",
        placeholder="01:10:800",
    )

    action_cols = st.columns(2)
    calculate_clicked = action_cols[0].button(
        "Hesapla",
        type="primary",
        use_container_width=True,
        key="manual_calc_run",
    )
    action_cols[1].button(
        "Temizle",
        use_container_width=True,
        key="manual_calc_clear",
        on_click=_reset_manual_calculator_state,
    )

    current_payload = {
        "class_name": class_name,
        "references": reference_rows,
        "target": {
            "km": target_km,
            "best_time": target_best,
        },
    }

    stored_result = st.session_state.get("manual_calc_result")
    stored_payload = st.session_state.get("manual_calc_payload")

    if calculate_clicked:
        try:
            stored_result = calculate_manual_stage_estimate(
                reference_rows=reference_rows,
                target_row=current_payload["target"],
                class_name=class_name,
            )
            stored_payload = current_payload
            st.session_state["manual_calc_result"] = stored_result
            st.session_state["manual_calc_payload"] = stored_payload
            st.success("Manuel hesap tamamlandı.")
        except ValueError as exc:
            stored_result = None
            stored_payload = None
            st.session_state.pop("manual_calc_result", None)
            st.session_state.pop("manual_calc_payload", None)
            st.error(str(exc))

    if stored_result and stored_payload != current_payload:
        st.info("Girdiler değişti. Sonucu güncellemek için Hesapla butonuna tekrar basın.")
        return

    if stored_result:
        _render_manual_calculation_result(stored_result)


def _render_manual_calculation_result(result: ManualCalculationResult):
    """Manuel hesap sonucunu goster."""
    render_stat_cards(
        [
            {
                "label": "Km Bazlı",
                "value": format_manual_time(result.km_based_prediction_seconds),
                "meta": f"Ortalama km başı fark: {result.average_diff_per_km:.4f} sn/km",
            },
            {
                "label": "Yüzde Bazlı",
                "value": format_manual_time(result.percentage_prediction_seconds),
                "meta": f"Ortalama oran: {_format_ratio_summary(result.average_ratio)}",
            },
        ]
    )

    summary_cols = st.columns(2)
    summary_cols[0].metric("Kullanılan etap sayısı", result.used_stage_count)
    summary_cols[1].metric("İki yöntem arasındaki fark (saniye)", f"{result.methods_gap_seconds:.3f}")

    if result.class_name:
        st.caption(f"Ham sınıf girdisi: {result.class_name}")

    if result.ignored_references:
        st.caption("Hesaba katılmayan satırlar: " + " | ".join(result.ignored_references))

    for warning in result.warnings:
        st.warning(warning)

    with st.expander("Hesap Adımlarını Göster", expanded=False):
        detail_rows = [
            {
                "Etap": item.label,
                "Km": f"{item.km:.3f}",
                "Best Derece": item.best_time_input,
                "Pilot Süresi": item.driver_time_input,
                "Fark": f"{item.diff_seconds:+.3f} sn",
                "Km Başına Fark": f"{item.diff_per_km:.4f} sn/km",
                "Yüzde / Oran": _format_ratio_summary(item.ratio),
            }
            for item in result.reference_details
        ]
        show_html_table(pd.DataFrame(detail_rows))

        st.markdown("##### Kullanılan Etap Ortalamaları")
        st.markdown(f"- Ortalama km başına fark: `{result.average_diff_per_km:.4f} sn/km`")
        st.markdown(f"- Ortalama oran: `{result.average_ratio:.6f}` ({(result.average_ratio - 1) * 100:+.2f}%)")

        st.markdown("##### Hedef Etap Formülü")
        st.code(
            "\n".join(
                [
                    f"Hedef etap km      : {result.target_km:.3f}",
                    f"Hedef etap best    : {result.target_best_input} ({format_manual_time(result.target_best_seconds)})",
                    "",
                    f"Km Bazlı    = {format_manual_time(result.target_best_seconds)} + ({result.average_diff_per_km:.4f} x {result.target_km:.3f})",
                    f"            = {format_manual_time(result.target_best_seconds)} + {result.target_diff_seconds:.3f} sn",
                    f"            = {format_manual_time(result.km_based_prediction_seconds)}",
                    "",
                    f"Yüzde Bazlı = {format_manual_time(result.target_best_seconds)} x {result.average_ratio:.6f}",
                    f"            = {format_manual_time(result.percentage_prediction_seconds)}",
                ]
            )
        )

        st.markdown("##### Final Sonuç")
        st.markdown(f"- Km Bazlı: `{format_manual_time(result.km_based_prediction_seconds)}`")
        st.markdown(f"- Yüzde Bazlı: `{format_manual_time(result.percentage_prediction_seconds)}`")


def _reset_manual_calculator_state():
    """Manuel hesap alanini sifirla."""
    defaults = {
        "manual_calc_class": "",
        "manual_target_km": 0.0,
        "manual_target_best": "",
    }
    for index in range(1, MANUAL_REFERENCE_STAGE_COUNT + 1):
        defaults[f"manual_ref_{index}_km"] = 0.0
        defaults[f"manual_ref_{index}_best"] = ""
        defaults[f"manual_ref_{index}_driver"] = ""

    for key, value in defaults.items():
        st.session_state[key] = value

    st.session_state.pop("manual_calc_result", None)
    st.session_state.pop("manual_calc_payload", None)


def _format_ratio_summary(ratio: float) -> str:
    """Orani hem katsayi hem yuzde olarak goster."""
    return f"{ratio:.4f} ({(ratio - 1) * 100:+.2f}%)"


# =============================================================================
# TOPLU TAHMIN
# =============================================================================

def _render_batch_prediction():
    """Toplu tahmin bölümü."""
    st.subheader("Toplu Tahmin")
    st.caption("Birden fazla pilot icin ayni etapta tahmin")

    # Etap bilgileri
    stage_info = create_stage_inputs(prefix="batch_")

    # Pilot seçimi (çoklu)
    drivers = get_driver_list()
    if not drivers:
        st.warning("Pilot bulunamadi!")
        return

    driver_options = {
        f"{d['driver_name']} ({d.get('normalized_class', d['car_class'])})": d
        for d in drivers
    }
    selected_labels = st.multiselect("Pilotlar", list(driver_options.keys()))

    # Tahmin butonu
    if selected_labels and st.button("Toplu Tahmin", type="primary", key="batch_predict"):
        progress = st.progress(0)
        results = []

        for i, label in enumerate(selected_labels):
            driver = driver_options[label]
            try:
                result = _run_prediction(
                    driver_id=driver['driver_id'],
                    driver_name=driver['driver_name'],
                    stage_length_km=stage_info['stage_length_km'],
                    surface=stage_info['surface'],
                    stage_number=stage_info['stage_number']
                )
                results.append({
                    'Pilot': driver['driver_name'],
                    'Zaman': result['predicted_time_str'],
                    'Hiz (km/h)': f"{result['predicted_speed_kmh']:.1f}",
                    'Oran': f"{result['predicted_ratio']:.3f}",
                    'Guven': format_confidence_label(result.get('confidence_level', 'MEDIUM'))
                })
            except Exception as e:
                results.append({
                    'Pilot': driver['driver_name'],
                    'Zaman': 'HATA',
                    'Hiz (km/h)': '-',
                    'Oran': '-',
                    'Guven': '-'
                })

            progress.progress((i + 1) / len(selected_labels))

        # Sonuçları göster
        if results:
            df = pd.DataFrame(results)
            show_html_table(df)

            # CSV indirme
            csv = df.to_csv(index=False)
            st.download_button(
                "CSV Olarak Indir",
                csv,
                f"tahmin_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                "text/csv"
            )


def _render_prediction_evaluation():
    """Prediction log ve degerlendirme gorunumu."""
    st.subheader("Tahmin Degerlendirme")
    st.caption("prediction_log kayitlarini, compare durumlarini ve veri kalite bayraklarini izleyin.")

    service = _get_prediction_service()
    filter_options = service.get_prediction_log_filter_options()

    if not filter_options["rally_ids"] and not filter_options["comparison_statuses"]:
        st.info("Henuz prediction_log kaydi yok.")
        return

    all_flags = [item["flag"] for item in service.get_prediction_quality_breakdown()]

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        selected_rally = st.selectbox(
            "Ralli",
            ["Tum Ralliler"] + filter_options["rally_ids"],
            key="prediction_eval_rally",
        )
    with col2:
        selected_status = st.selectbox(
            "Karsilastirma Durumu",
            ["Tum Durumlar"] + filter_options["comparison_statuses"],
            format_func=lambda option: "Tum Durumlar" if option == "Tum Durumlar" else format_compare_status_label(option),
            key="prediction_eval_status",
        )
    with col3:
        selected_flag = st.selectbox(
            "Kalite Bayragi",
            ["Tum Bayraklar"] + all_flags,
            key="prediction_eval_flag",
        )
    with col4:
        row_limit = st.selectbox(
            "Kayit Limiti",
            [50, 100, 250, 500],
            index=1,
            key="prediction_eval_limit",
        )

    rally_filter = None if selected_rally == "Tum Ralliler" else selected_rally
    status_filter = None if selected_status == "Tum Durumlar" else selected_status
    flag_filter = None if selected_flag == "Tum Bayraklar" else selected_flag

    summary = service.get_prediction_log_summary(
        rally_id=rally_filter,
        comparison_status=status_filter,
    )

    metric1, metric2, metric3, metric4, metric5 = st.columns(5)
    metric1.metric("Toplam", summary.get("total_predictions", 0))
    metric2.metric("Beklemede", summary.get("pending_count", 0))
    metric3.metric("Eslesti", summary.get("matched_count", 0))
    metric4.metric(
        "Ort. Hata %",
        f"{summary['avg_error_pct']:.2f}" if summary.get("avg_error_pct") is not None else "-",
    )
    metric5.metric(
        "Kabul Orani",
        f"{summary['acceptance_rate_pct']:.1f}%"
        if summary.get("acceptance_rate_pct") is not None
        else "-",
    )

    metric6, metric7, metric8 = st.columns(3)
    metric6.metric("Geometri Kullanildi", summary.get("geometry_used_count", 0))
    metric7.metric("Sadece Temel Tahmin", summary.get("baseline_only_count", 0))
    metric8.metric(
        "Geometri Kullanimi",
        f"{summary['geometry_usage_rate_pct']:.1f}%"
        if summary.get("geometry_usage_rate_pct") is not None
        else "-",
    )

    quality_breakdown = service.get_prediction_quality_breakdown(
        rally_id=rally_filter,
        comparison_status=status_filter,
    )
    if quality_breakdown:
        st.markdown("#### Kalite Bayraklari")
        quality_df = pd.DataFrame(quality_breakdown)
        show_html_table(quality_df)

    issue_filter_options = service.get_prediction_issue_filter_options(
        rally_id=rally_filter,
        comparison_status=status_filter,
        only_flag=flag_filter,
    )

    st.markdown("#### Aksiyon Listesi")
    st.caption("Gercek sonuc eksigi, geometry/elevation sorunu veya yuksek hata ureten kayitlari is listesi halinde takip edin.")

    issue_col1, issue_col2, issue_col3 = st.columns(3)
    with issue_col1:
        selected_issue_type = st.selectbox(
            "Problem Turu",
            ["Tum Problemler"] + issue_filter_options["issue_types"],
            key="prediction_issue_type",
        )
    with issue_col2:
        selected_priority = st.selectbox(
            "Oncelik",
            ["Tum Oncelikler"] + issue_filter_options["priorities"],
            key="prediction_issue_priority",
        )
    with issue_col3:
        issue_limit = st.selectbox(
            "Aksiyon Limiti",
            [25, 50, 100, 250],
            index=1,
            key="prediction_issue_limit",
        )

    issue_type_filter = None if selected_issue_type == "Tum Problemler" else selected_issue_type
    issue_priority_filter = None if selected_priority == "Tum Oncelikler" else selected_priority

    issue_breakdown = service.get_prediction_issue_breakdown(
        rally_id=rally_filter,
        comparison_status=status_filter,
        only_flag=flag_filter,
    )
    issue_rows = service.get_prediction_issue_worklist(
        limit=issue_limit,
        rally_id=rally_filter,
        comparison_status=status_filter,
        only_flag=flag_filter,
        issue_type=issue_type_filter,
        priority=issue_priority_filter,
    )

    if issue_rows:
        p1_count = sum(1 for item in issue_rows if item["priority"] == "P1")
        unique_predictions = len({item["prediction_id"] for item in issue_rows})
        issue_metric1, issue_metric2, issue_metric3 = st.columns(3)
        issue_metric1.metric("Aksiyon Sayisi", len(issue_rows))
        issue_metric2.metric("P1 Kritik", p1_count)
        issue_metric3.metric("Etkilenen Tahmin", unique_predictions)

        if issue_breakdown:
            issue_df = pd.DataFrame(issue_breakdown)
            show_html_table(issue_df)

        st.markdown("##### Hizli Gecis")
        quick_rows = issue_rows[:10]
        for item in quick_rows:
            action_cols = st.columns([1, 2, 2, 4, 2])
            action_cols[0].markdown(f"**{item['priority']}**")
            action_cols[1].write(item["stage_id"])
            action_cols[2].write(item["driver_name"])
            action_cols[3].write(
                f"{item['issue_title']} -> {item['action_target_page']} / {item['action_target_section']}"
            )
            if action_cols[4].button(
                item["action_target_label"],
                key=f"prediction_issue_action_{item['prediction_id']}_{item['issue_type']}",
            ):
                _open_prediction_issue_action(item)

        if len(issue_rows) > len(quick_rows):
            st.caption(f"Ilk {len(quick_rows)} aksiyon icin hizli gecis butonu gosteriliyor.")

        issue_table_rows = []
        for item in issue_rows:
            issue_table_rows.append(
                {
                    "oncelik": item["priority"],
                    "problem_turu": item["issue_type"],
                    "prediction_id": item["prediction_id"],
                    "rally_id": item["rally_id"],
                    "stage_id": item["stage_id"],
                    "pilot": item["driver_name"],
                    "karsilastirma_durumu": format_compare_status_label(item["comparison_status"]),
                    "hata_yuzdesi": item["error_pct_display"],
                    "kalite_bayraklari": item["quality_flags"],
                    "hedef": f"{item['action_target_page']} / {item['action_target_section']}",
                    "neden": item["issue_reason"],
                    "onerilen_aksiyon": item["recommended_action"],
                }
            )

        issue_table_df = pd.DataFrame(issue_table_rows)
        show_html_table(issue_table_df)

        issue_csv_data = issue_table_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Aksiyon Listesini CSV Olarak Indir",
            issue_csv_data,
            f"prediction_issue_worklist_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            "text/csv",
        )
    else:
        st.success("Secilen filtrelerle problemli kayit bulunamadi.")

    rows = service.get_prediction_log_rows(
        limit=row_limit,
        rally_id=rally_filter,
        comparison_status=status_filter,
        only_flag=flag_filter,
    )
    if not rows:
        st.info("Secilen filtrelerle kayit bulunamadi.")
        return

    st.markdown("#### Tahmin Logu")
    table_rows = []
    for row in rows:
        table_rows.append(
            {
                "prediction_id": row["prediction_id"],
                "tahmin_zamani": row["predicted_at"],
                "rally_id": row["rally_id"],
                "stage_id": row["stage_id"],
                "pilot": row["driver_name"],
                "tahmini_sure": row["predicted_time_str"],
                "gercek_sure": row["actual_time_str"] or "-",
                "hata_yuzdesi": f"{row['error_pct']:.2f}" if row.get("error_pct") is not None else "-",
                "kabul": format_boolean_label(row["accepted_label"]),
                "karsilastirma_durumu": format_compare_status_label(row["comparison_status"]),
                "guven": f"{float(row['confidence']):.1f}" if row.get("confidence") is not None else "-",
                "geometri_kullanildi": format_boolean_label(row["used_geometry_label"]),
                "kalite_bayraklari": row["data_quality_flags_display"] or "-",
                "cozulen_sorunlar": row["resolved_issue_types_display"] or "-",
                "cozulme_zamani": row.get("resolved_at") or "-",
                "cozum_kaynagi": row.get("resolution_source") or "-",
                "model_surumu": row["model_version"],
            }
        )

    table_df = pd.DataFrame(table_rows)
    show_html_table(table_df)

    csv_data = table_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Tahmin Logunu CSV Olarak Indir",
        csv_data,
        f"prediction_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        "text/csv",
    )


def _run_prediction(driver_id: str, driver_name: str, stage_length_km: float,
                    surface: str, stage_number: int) -> dict:
    """Tahmin çalıştır (Manuel/Toplu)."""
    return _get_prediction_service().predict_manual_stage(
        driver_id=driver_id,
        driver_name=driver_name,
        stage_length_km=stage_length_km,
        surface=surface,
        stage_number=stage_number,
        day_or_night='day',
        rally_name='Manuel Tahmin',
    )


def _get_prediction_service():
    """Create the single predictor service used by all prediction screens."""
    from src.prediction.prediction_service import PredictionService

    model_path = get_model_path()
    model_path_str = str(model_path) if model_path.exists() else None
    return PredictionService(db_path=get_db_path(), model_path=model_path_str)


# =============================================================================
# ORTAK YARDIMCI FONKSIYONLAR
# =============================================================================

def _fallback_baseline(db_path: str, driver_name: str) -> float:
    """DB'deki ham veriden basit baseline hesapla (modüller basarisiz olursa)."""
    conn = sqlite3.connect(db_path)
    query = """
        SELECT AVG(ratio_to_class_best) as avg_ratio
        FROM stage_results
        WHERE driver_name = ? AND time_seconds > 0
        AND ratio_to_class_best IS NOT NULL AND ratio_to_class_best > 0
    """
    df = pd.read_sql_query(query, conn, params=[driver_name])
    conn.close()

    if len(df) > 0 and df.iloc[0]['avg_ratio']:
        return float(df.iloc[0]['avg_ratio'])

    return 1.1  # Varsayilan


def _calculate_surface_adjustment(db_path: str, driver_name: str,
                                  normalized_class: str, target_surface: str) -> float:
    """Zemine gore performans ayarlamasi hesapla."""
    conn = sqlite3.connect(db_path)

    # Pilotun hedef zemindeki ortalama ratio
    query_surface = """
        SELECT AVG(ratio_to_class_best) as avg_ratio, COUNT(*) as cnt
        FROM stage_results
        WHERE driver_name = ? AND surface = ?
        AND ratio_to_class_best IS NOT NULL AND ratio_to_class_best > 0
    """
    df_surface = pd.read_sql_query(query_surface, conn, params=[driver_name, target_surface])

    # Pilotun genel ortalama ratio
    query_all = """
        SELECT AVG(ratio_to_class_best) as avg_ratio
        FROM stage_results
        WHERE driver_name = ?
        AND ratio_to_class_best IS NOT NULL AND ratio_to_class_best > 0
    """
    df_all = pd.read_sql_query(query_all, conn, params=[driver_name])
    conn.close()

    if (len(df_surface) > 0 and df_surface.iloc[0]['cnt'] and df_surface.iloc[0]['cnt'] >= 3
            and len(df_all) > 0 and df_all.iloc[0]['avg_ratio']):
        surface_ratio = float(df_surface.iloc[0]['avg_ratio'])
        all_ratio = float(df_all.iloc[0]['avg_ratio'])
        if all_ratio > 0:
            return surface_ratio / all_ratio

    return 1.0


def _apply_geometric_correction(baseline_ratio, momentum_factor, surface_adj,
                                 geo_features, driver_name, normalized_class,
                                 surface, db_path):
    """ML modeli ile geometrik duzeltme uygula."""
    import pickle

    model_path = get_model_path()
    if not model_path.exists():
        return 1.0, "model yok"

    try:
        with open(model_path, 'rb') as f:
            model_data = pickle.load(f)

        model = model_data['model']
        feature_cols = model_data['feature_columns']

        # Feature vektörü oluştur
        # Pilotun DB istatistiklerini al
        conn = sqlite3.connect(db_path)
        driver_stats = pd.read_sql_query("""
            SELECT COUNT(*) as stage_count,
                   AVG(ratio_to_class_best) as avg_ratio
            FROM stage_results
            WHERE driver_name = ? AND time_seconds > 0
            AND ratio_to_class_best IS NOT NULL
        """, conn, params=[driver_name])

        surface_stats = pd.read_sql_query("""
            SELECT AVG(ratio_to_class_best) as surface_ratio
            FROM stage_results
            WHERE driver_name = ? AND surface = ?
            AND ratio_to_class_best IS NOT NULL
        """, conn, params=[driver_name, surface])
        conn.close()

        driver_stage_count = int(driver_stats.iloc[0]['stage_count']) if len(driver_stats) > 0 else 0
        driver_avg_ratio = float(driver_stats.iloc[0]['avg_ratio']) if len(driver_stats) > 0 and driver_stats.iloc[0]['avg_ratio'] else baseline_ratio
        driver_surface_ratio = float(surface_stats.iloc[0]['surface_ratio']) if len(surface_stats) > 0 and surface_stats.iloc[0]['surface_ratio'] else driver_avg_ratio

        features = {
            'baseline_ratio': baseline_ratio,
            'stage_length_km': geo_features.get('distance_km', 15),
            'hairpin_count': geo_features.get('hairpin_count', 0),
            'hairpin_density': geo_features.get('hairpin_density', 0),
            'turn_count': geo_features.get('turn_count', 0),
            'turn_density': geo_features.get('turn_density', 0),
            'total_ascent': geo_features.get('total_ascent', 0),
            'total_descent': geo_features.get('total_descent', 0),
            'avg_curvature': geo_features.get('avg_curvature', 0),
            'max_curvature': geo_features.get('max_curvature', 0),
            'p95_curvature': geo_features.get('p95_curvature', 0),
            'curvature_density': geo_features.get('curvature_density', 0),
            'max_grade': geo_features.get('max_grade', 0),
            'avg_abs_grade': geo_features.get('avg_abs_grade', 0),
            'straight_percentage': geo_features.get('straight_ratio', 0) * 100,
            'curvy_percentage': (1 - geo_features.get('straight_ratio', 0)) * 100,
            'driver_stage_count': driver_stage_count,
            'driver_avg_ratio': driver_avg_ratio,
            'driver_surface_ratio': driver_surface_ratio,
            'momentum_factor': momentum_factor,
            'surface': surface,
            'normalized_class': normalized_class,
        }

        X = pd.DataFrame([features])
        available_cols = [c for c in feature_cols if c in X.columns]
        X = X[available_cols]

        for col in ['surface', 'normalized_class']:
            if col in X.columns:
                X[col] = X[col].astype('category')

        correction = float(model.predict(X)[0])
        correction = np.clip(correction, 0.9, 1.1)
        return correction, "geometric"

    except Exception as e:
        return 1.0, f"fallback ({e})"


def _calculate_reference_time(stage_length, surface, normalized_class, geo_features=None):
    """Referans sure hesapla (sinif lideri icin)."""
    if surface == 'asphalt':
        base_speed = 105
    elif surface == 'snow':
        base_speed = 70
    else:
        base_speed = 85

    class_factors = {
        'WRC': 1.0, 'Rally1': 1.0,
        'Rally2': 1.08, 'R5': 1.08,
        'Rally3': 1.15, 'R2': 1.15,
        'Rally4': 1.12,
        'Rally5': 1.18,
        'N': 1.15,
        'K1': 1.10, 'K2': 1.12, 'K3': 1.18, 'K4': 1.22,
        'H1': 1.10, 'H2': 1.15,
    }
    class_factor = class_factors.get(normalized_class, 1.10)

    # Geometrik zorluk faktörü
    geo_difficulty = 1.0
    if geo_features:
        geo_difficulty += geo_features.get('hairpin_density', 0) * 0.02
        geo_difficulty += geo_features.get('avg_abs_grade', 0) * 0.005
        geo_difficulty = min(geo_difficulty, 1.3)

    adjusted_speed = base_speed / class_factor / geo_difficulty
    reference_time = (stage_length / adjusted_speed) * 3600

    return reference_time, adjusted_speed, geo_difficulty


def _calculate_confidence(baseline_result, momentum_info, geo_mode, surface_adj):
    """Guven skoru hesapla."""
    score = 30  # Baz skor

    # Baseline verisi
    if baseline_result:
        rallies = baseline_result.get('data_points', 0)
        stages = baseline_result.get('total_stages', 0)
        score += min(rallies * 5, 20)  # Max 20 puan
        score += min(stages, 15)  # Max 15 puan

    # Momentum verisi
    if momentum_info and momentum_info.get('stages_analyzed', 0) > 0:
        score += min(momentum_info['stages_analyzed'] * 3, 15)

    # Geometrik model
    if geo_mode == "geometric":
        score += 10

    # Surface deneyimi
    if surface_adj != 1.0:
        score += 5  # Zemin verisi var

    return min(100, score)


def _analyze_kml_file(uploaded_file):
    """KML dosyasini analiz et ve geo_features don."""
    try:
        from src.stage_analyzer.kml_parser import parse_kml_file
        from src.stage_analyzer.kml_analyzer import KMLAnalyzer

        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{uploaded_file.name.split('.')[-1]}") as tmp:
            tmp.write(uploaded_file.getbuffer())
            tmp_path = tmp.name

        kml_stages = parse_kml_file(tmp_path)
        if not kml_stages:
            return None

        selected_stage = kml_stages[0]

        temp_kml = Path(tempfile.gettempdir()) / f"live_analysis_{datetime.now().strftime('%H%M%S')}.kml"
        kml_content = '<?xml version="1.0" encoding="UTF-8"?>\n'
        kml_content += '<kml xmlns="http://www.opengis.net/kml/2.2">\n<Document>\n'
        kml_content += f'<Placemark><name>{selected_stage.name}</name>\n'
        kml_content += '<LineString><coordinates>\n'
        for lat, lon in selected_stage.coordinates:
            kml_content += f'{lon},{lat},0 '
        kml_content += '\n</coordinates></LineString></Placemark>\n</Document>\n</kml>'

        with open(temp_kml, 'w', encoding='utf-8') as f:
            f.write(kml_content)

        analyzer = KMLAnalyzer(geom_step=10.0, smoothing_window=7, elev_step=200.0)
        geo_features = analyzer.analyze_kml(str(temp_kml), hairpin_threshold=20.0)
        temp_kml.unlink()
        Path(tmp_path).unlink()

        return geo_features
    except Exception:
        return None


def _parse_time_str(time_str: str) -> float:
    """Zaman string'ini saniyeye cevir."""
    try:
        return parse_manual_time_input(time_str)
    except ValueError:
        pass
    return 0


def _format_time(seconds):
    """Saniyeyi MM:SS.ss formatina cevir."""
    return format_manual_time(seconds if seconds > 0 else 0.0)
