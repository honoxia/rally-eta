"""
Rally ETA v2.0 - Ana sayfa / kontrol merkezi
"""

from html import escape
from pathlib import Path
import sys
from textwrap import dedent

import streamlit as st


sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.db_helpers import get_database_info
from shared.data_loaders import (
    get_kml_files,
    get_model_status,
    get_rally_list,
    get_stage_metadata_df,
)
from shared.ui_components import render_page_header, render_stat_cards


def render():
    """Ana sayfa icerigini render et."""
    db_info = get_database_info()
    kml_files = get_kml_files()
    model_status = get_model_status()
    rallies = get_rally_list(limit=5)
    geometry_df = get_stage_metadata_df(limit=8)

    render_page_header(
        "Kontrol Merkezi",
        "Ralli verisi, etap geometrisi ve notional time pipeline'ini tek bir masaustu kabugunda yonetin.",
        badge=_get_readiness_badge(db_info, model_status),
        eyebrow="Operasyon Gozetimi",
    )

    _render_spotlight(db_info, kml_files, model_status, geometry_df)
    _render_quick_actions()

    render_stat_cards(
        [
            {
                "label": "Toplam Sonuc",
                "value": f"{db_info.get('result_count', 0):,}" if db_info.get("exists") else "0",
                "meta": "Sonuc veritabanindaki toplam etap sonucu kaydi.",
            },
            {
                "label": "Pilot Havuzu",
                "value": str(db_info.get("driver_count", 0)) if db_info.get("exists") else "0",
                "meta": "Tahmin ve karsilastirma icin hazir benzersiz pilot kaydi.",
            },
            {
                "label": "KML Arsivi",
                "value": str(len(kml_files)),
                "meta": "Etap geometrisini zenginlestirmek icin kullanilan yerel dosyalar.",
            },
            {
                "label": "Model Durumu",
                "value": "Hazir" if model_status.get("model_exists") else "Bekliyor",
                "meta": _model_meta(model_status),
            },
        ]
    )

    top_left, top_right = st.columns([1.15, 0.85], gap="large")
    with top_left:
        _render_pipeline_board(db_info, model_status)
    with top_right:
        _render_recent_activity(rallies, geometry_df)

    bottom_left, bottom_right = st.columns([1, 1], gap="large")
    with bottom_left:
        _render_manual_test_path()
    with bottom_right:
        _render_system_notes(db_info, model_status, geometry_df)


def _render_spotlight(db_info, kml_files, model_status, geometry_df):
    last_geometry = "-"
    if not geometry_df.empty:
        row = geometry_df.iloc[0]
        stage_name = row.get("stage_name") or row.get("stage_id") or "Bilinmeyen etap"
        analyzed_at = row.get("processed_at") or row.get("analyzed_at")
        if analyzed_at:
            last_geometry = f"{stage_name} | {str(analyzed_at)[:16]}"
        else:
            last_geometry = str(stage_name)

    pills = [
        _pill_html("Veri", "success" if db_info.get("exists") else "warning"),
        _pill_html("Geometri", "success" if db_info.get("geometry_count", 0) else "warning"),
        _pill_html("Model", "success" if model_status.get("model_exists") else "info"),
        _pill_html("KML", "info" if kml_files else "warning"),
    ]

    st.markdown(
        _html(f"""
        <section class="surface-card surface-card--solid">
            <div class="section-kicker">Anlik calisma ozeti</div>
            <h3>Bugun en hizli akisi bu panelden yonetebilirsiniz.</h3>
            <p>
                Once sonuc verisini alin, ardindan etap geometrisini zenginlestirin, modeli guncelleyin
                ve son olarak tahmin veya canli karsilastirma ekranina gecin. Ana akista kritik blokaj
                varsa onu burada hemen gorursunuz.
            </p>
            <div class="pill-row">{''.join(pills)}</div>
            <div class="list-stack">
                <div class="list-row">
                    <div>
                        <div class="list-row__title">Son geometri isleme</div>
                        <div class="list-row__text">{escape(last_geometry)}</div>
                    </div>
                    <div class="list-row__meta">{db_info.get('geometry_count', 0):,} kayit</div>
                </div>
                <div class="list-row">
                    <div>
                        <div class="list-row__title">Tahmin hazirlik seviyesi</div>
                        <div class="list-row__text">{escape(_prediction_readiness_text(db_info, model_status))}</div>
                    </div>
                    <div class="list-row__meta">{_get_readiness_badge(db_info, model_status)}</div>
                </div>
            </div>
        </section>
        """),
        unsafe_allow_html=True,
    )


def _render_quick_actions():
    st.markdown("### Hemen Basla")
    col1, col2, col3, col4 = st.columns(4, gap="medium")

    with col1:
        if st.button("Veri hattini ac", key="home_action_scraper", use_container_width=True):
            _open_page("Veri Cek", "TOSFED Scraper")
        st.caption("TOSFED tarama, merge ve database yukleme.")

    with col2:
        if st.button("Geometrik verilere git", key="home_action_kml", use_container_width=True):
            _open_page("KML Yonetimi", "Yukle")
        st.caption("Geometrik veri yukleme, manuel analiz ve geometri kaydi.")

    with col3:
        if st.button("Model egitimi", key="home_action_training", use_container_width=True):
            _open_page("Model Egitimi")
        st.caption("Model hazirligini kontrol et ve gerekiyorsa egitimi calistir.")

    with col4:
        if st.button("Tahmin laboratuvari", key="home_action_prediction", use_container_width=True):
            _open_page("Tahmin Yap", "Canli Tahmin")
        st.caption("Canli, KML bazli veya manuel tahmin akislari.")


def _render_pipeline_board(db_info, model_status):
    items = [
        {
            "title": "1. Sonuc toplama",
            "text": (
                f"{db_info.get('result_count', 0):,} sonuc ve {db_info.get('rally_count', 0)} ralli kaydi mevcut."
                if db_info.get("exists")
                else "Veritabani henuz hazir degil. Once Veri Cek ekranindan kaynak veriyi alin."
            ),
            "meta": "Hazir" if db_info.get("exists") else "Blokeli",
        },
        {
            "title": "2. Geometri kapsami",
            "text": (
                f"{db_info.get('geometry_count', 0):,} etap geometrisi kaydi ile modelleme destekleniyor."
                if db_info.get("geometry_count", 0)
                else "KML yukleyip en az bir etap analiz etmeniz gerekiyor."
            ),
            "meta": "Hazir" if db_info.get("geometry_count", 0) else "KML gerekli",
        },
        {
            "title": "3. Model hazirligi",
            "text": _model_meta(model_status),
            "meta": "Hazir" if model_status.get("model_exists") else "Egit",
        },
        {
            "title": "4. Tahmin operasyonu",
            "text": _prediction_readiness_text(db_info, model_status),
            "meta": _get_readiness_badge(db_info, model_status),
        },
    ]

    html_items = "".join(
        _html(f"""
        <div class="list-row">
            <div>
                <div class="list-row__title">{escape(item['title'])}</div>
                <div class="list-row__text">{escape(item['text'])}</div>
            </div>
            <div class="list-row__meta">{escape(item['meta'])}</div>
        </div>
        """)
        for item in items
    )

    st.markdown(
        _html(f"""
        <section class="surface-card">
            <div class="section-kicker">Akis ozeti</div>
            <h3>Operasyon akisi</h3>
            <p>Asagidaki dort adim uygulamanin ana is akisini temsil eder. Her adim bir sonrakini acar.</p>
            <div class="list-stack">{html_items}</div>
        </section>
        """),
        unsafe_allow_html=True,
    )


def _render_recent_activity(rallies, geometry_df):
    recent_rows = []
    for rally in rallies[:5]:
        recent_rows.append(
            _html(f"""
            <div class="list-row">
                <div>
                    <div class="list-row__title">{escape(str(rally.get('rally_name', rally.get('rally_id', 'Rally'))))}</div>
                    <div class="list-row__text">Rally ID: {escape(str(rally.get('rally_id', '-')))}</div>
                </div>
                <div class="list-row__meta">{rally.get('stage_count', 0)} etap</div>
            </div>
            """)
        )

    if not recent_rows:
        recent_rows.append(
            _html("""
            <div class="list-row">
                <div>
                    <div class="list-row__title">Ralli kaydi bulunamadi</div>
                    <div class="list-row__text">Veri Cek ekranindan ilk sonuclari eklediginizde burada gorunecek.</div>
                </div>
                <div class="list-row__meta">Bos</div>
            </div>
            """)
        )

    last_validated = "-"
    if not geometry_df.empty:
        validated = geometry_df.iloc[0].get("validated_at") or geometry_df.iloc[0].get("processed_at")
        if validated:
            last_validated = str(validated)[:16]

    st.markdown(
        _html(f"""
        <section class="surface-card">
            <div class="section-kicker">Son baglam</div>
            <h3>Son aktif veriler</h3>
            <p>Yeni import edilen ralliler ve en son geometri dokunuslari burada ozetlenir.</p>
            <div class="list-stack">{''.join(recent_rows)}</div>
            <div class="pill-row">
                {_pill_html(f"Son geometri: {last_validated}", "info")}
                {_pill_html(f"Kayit: {len(geometry_df)}", "success" if len(geometry_df) else "warning")}
            </div>
        </section>
        """),
        unsafe_allow_html=True,
    )


def _render_manual_test_path():
    steps = [
        "Veri Cek ekraninda kisa bir rally taramasi yap.",
        "Geometrik Veriler ekraninda bir etap secip analiz kaydet.",
        "Model Egitimi ekraninda model durumunu kontrol et ve gerekiyorsa modeli egit.",
        "Tahmin Yap ekraninda canli veya manuel tahmin sonucu uret.",
    ]

    step_html = "".join(
        _html(f"""
        <div class="list-row">
            <div>
                <div class="list-row__title">{index}. Manuel kontrol</div>
                <div class="list-row__text">{escape(text)}</div>
            </div>
            <div class="list-row__meta">Adim {index}</div>
        </div>
        """)
        for index, text in enumerate(steps, start=1)
    )

    st.markdown(
        _html(f"""
        <section class="surface-card">
            <div class="section-kicker">Manuel kontrol</div>
            <h3>Kendiniz hizli test etmek isterseniz</h3>
            <p>Bu akisi tamamladiginizda veriden tahmine kadar ana yolun saglam calistigini rahatca gorebilirsiniz.</p>
            <div class="list-stack">{step_html}</div>
        </section>
        """),
        unsafe_allow_html=True,
    )


def _render_system_notes(db_info, model_status, geometry_df):
    notes = [
        {
            "title": "Veritabani",
            "text": "Yerel veritabani baglantisi aktif." if db_info.get("exists") else "Veritabani yolu kontrol edilmeli.",
            "tone": "success" if db_info.get("exists") else "warning",
        },
        {
            "title": "Geometri",
            "text": (
                f"{db_info.get('geometry_count', 0)} geometri kaydi tahmin hattina hazir."
                if db_info.get("geometry_count", 0)
                else "Geometrik analiz olmadan model sadece taban performans uzerinden calisir."
            ),
            "tone": "success" if db_info.get("geometry_count", 0) else "warning",
        },
        {
            "title": "Model",
            "text": _model_meta(model_status),
            "tone": "success" if model_status.get("model_exists") else "info",
        },
        {
            "title": "Kapsam",
            "text": (
                f"En son analiz edilen satir: {geometry_df.iloc[0].get('stage_id', '-')}"
                if not geometry_df.empty
                else "Yeni KML importu ile kapsam genisletilebilir."
            ),
            "tone": "info" if not geometry_df.empty else "warning",
        },
    ]

    note_html = "".join(
        _html(f"""
        <div class="list-row">
            <div>
                <div class="list-row__title">{escape(note['title'])}</div>
                <div class="list-row__text">{escape(note['text'])}</div>
            </div>
            <div class="pill pill--{note['tone']}">{escape(_tone_label(note['tone']))}</div>
        </div>
        """)
        for note in notes
    )

    st.markdown(
        _html(f"""
        <section class="surface-card">
            <div class="section-kicker">Sistem notlari</div>
            <h3>Calisma ortami sinyalleri</h3>
            <p>Bu blok, bugunun test veya build turunda once bakilmasi gereken kisa isaretleri listeler.</p>
            <div class="list-stack">{note_html}</div>
        </section>
        """),
        unsafe_allow_html=True,
    )


def _model_meta(model_status):
    if model_status.get("model_exists"):
        metrics = model_status.get("metrics", {})
        mape = metrics.get("mape")
        return f"Egitilmis model aktif. MAPE: {mape:.2f}%" if mape is not None else "Egitilmis model dosyasi mevcut."

    training_rows = model_status.get("training_data_count", 0)
    reason = model_status.get("reason") or model_status.get("error") or "Egitim icin daha fazla hazir veri gerekli."
    if training_rows:
        return f"{training_rows} egitim satiri hazir. {reason}"
    return reason


def _prediction_readiness_text(db_info, model_status):
    if not db_info.get("exists"):
        return "Tahmin ekranina gecmeden once en az bir veritabani olusturulmali."
    if not model_status.get("model_exists"):
        return "Manuel ve canli akislari deneyebilirsiniz fakat ML katmani icin model egitimi onerilir."
    return "Canli, KML bazli ve manuel tahmin akislari icin sistem hazir durumda."


def _get_readiness_badge(db_info, model_status):
    if db_info.get("exists") and model_status.get("model_exists"):
        return "Tahmine hazir"
    if db_info.get("exists"):
        return "Veri hazir"
    return "Kurulum gerekli"


def _pill_html(text, tone):
    return f'<span class="pill pill--{escape(tone)}">{escape(text)}</span>'


def _tone_label(tone):
    return {
        "success": "hazir",
        "warning": "dikkat",
        "info": "bilgi",
        "danger": "kritik",
    }.get(tone, tone)


def _html(block):
    return dedent(block).strip()


def _open_page(page, section=None):
    st.session_state["selected_page_override"] = page
    if page == "Veri Cek" and section:
        st.session_state["scraper_section_override"] = section
    elif page == "KML Yonetimi" and section:
        st.session_state["kml_manager_section_override"] = section
    elif page == "Tahmin Yap" and section:
        st.session_state["prediction_section_override"] = section
    st.rerun()
