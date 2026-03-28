"""
Rally ETA v2.0 - UI bilesenleri
Ortak Streamlit stilleri ve tekrar eden arayuz parcaciklari.
"""

from html import escape
from textwrap import dedent
from typing import Optional

import pandas as pd
import streamlit as st

from .config import MAX_TABLE_ROWS


SURFACE_LABELS = {
    "gravel": "Toprak",
    "asphalt": "Asfalt",
    "mixed": "Karisik",
    "snow": "Kar",
}

CONFIDENCE_LABELS = {
    "HIGH": "Yuksek",
    "MEDIUM": "Orta",
    "LOW": "Dusuk",
}

COMPARE_STATUS_LABELS = {
    "pending": "Beklemede",
    "matched": "Eslesti",
    "actual_missing": "Gercek sonuc eksik",
    "not_applicable": "Karsilastirma yok",
}

BOOLEAN_LABELS = {
    "yes": "Evet",
    "no": "Hayir",
}


CUSTOM_CSS = """
<style>
    :root {
        --bg-deep: #06111f;
        --bg-panel: rgba(11, 20, 36, 0.90);
        --bg-panel-strong: rgba(14, 26, 48, 0.96);
        --bg-panel-dark: linear-gradient(135deg, rgba(7, 17, 31, 0.98), rgba(15, 23, 42, 0.96));
        --line-soft: rgba(148, 163, 184, 0.16);
        --text-main: #f8fbff;
        --text-soft: #cad7ee;
        --text-muted: #8fa4c4;
        --text-inverse: #f8fafc;
        --blue: #60a5fa;
        --blue-soft: #bfdbfe;
        --amber: #f59e0b;
        --emerald: #34d399;
        --rose: #fb7185;
        --shadow-soft: 0 24px 60px rgba(2, 8, 23, 0.22);
        --shadow-strong: 0 28px 80px rgba(2, 6, 23, 0.42);
        --radius-xl: 28px;
        --radius-lg: 22px;
    }

    html, body, [class*="css"] {
        font-family: "Segoe UI Variable Text", "Aptos", "Segoe UI", sans-serif;
    }

    h1, h2, h3, h4, h5, h6,
    .page-hero__eyebrow,
    .page-hero__badge,
    .stat-card__label,
    .pill,
    .sidebar-brand__eyebrow,
    .sidebar-section-label {
        font-family: "Bahnschrift", "Segoe UI Variable Display", "Segoe UI", sans-serif;
    }

    code, pre, .mono {
        font-family: "Cascadia Code", "Fira Code", "Consolas", monospace;
    }

    .stApp {
        background:
            radial-gradient(960px 620px at 0% 0%, rgba(37, 99, 235, 0.18), transparent 58%),
            radial-gradient(720px 520px at 100% 0%, rgba(245, 158, 11, 0.12), transparent 52%),
            linear-gradient(180deg, #040915 0%, #07111f 42%, #08111d 100%);
        color: var(--text-main);
    }

    [data-testid="stAppViewContainer"],
    [data-testid="stAppViewContainer"] > .main {
        background: transparent;
    }

    .main .block-container {
        max-width: 1420px;
        padding-top: 1.4rem;
        padding-bottom: 4rem;
        color: var(--text-main);
    }

    .main .block-container h1,
    .main .block-container h2,
    .main .block-container h3,
    .main .block-container h4,
    .main .block-container h5,
    .main .block-container h6,
    .main .block-container label,
    .main .block-container [data-testid="stMarkdownContainer"] p,
    .main .block-container [data-testid="stCaptionContainer"] {
        color: var(--text-main);
    }

    .main .block-container p,
    .main .block-container li,
    .main .block-container small,
    .main .block-container span {
        color: var(--text-soft);
    }

    hr {
        border-color: rgba(148, 163, 184, 0.12);
    }

    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, rgba(3, 7, 18, 0.97), rgba(11, 23, 48, 0.96));
        border-right: 1px solid rgba(148, 163, 184, 0.14);
        backdrop-filter: blur(20px);
    }

    [data-testid="stSidebar"] .block-container {
        padding-top: 1.2rem;
        padding-bottom: 1.6rem;
    }

    [data-testid="stSidebar"] * {
        color: var(--text-inverse);
    }

    .sidebar-brand,
    .sidebar-status-card {
        padding: 1.05rem 1.1rem;
        border-radius: 24px;
        border: 1px solid rgba(148, 163, 184, 0.16);
        background: linear-gradient(180deg, rgba(15, 23, 42, 0.82), rgba(30, 41, 59, 0.56));
        box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
    }

    .sidebar-brand {
        margin-bottom: 0.9rem;
    }

    .sidebar-brand__eyebrow,
    .sidebar-section-label {
        font-size: 0.7rem;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        color: #93c5fd;
        margin-bottom: 0.45rem;
    }

    .sidebar-brand h2 {
        margin: 0;
        font-size: 1.4rem;
        color: #f8fafc;
    }

    .sidebar-brand p,
    .sidebar-status-card p,
    .sidebar-footer {
        color: #cbd5e1;
        margin: 0.45rem 0 0;
        line-height: 1.55;
        font-size: 0.92rem;
    }

    .sidebar-status-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 0.65rem;
        margin-top: 0.85rem;
    }

    .sidebar-status-tile {
        padding: 0.75rem 0.8rem;
        border-radius: 16px;
        background: rgba(15, 23, 42, 0.72);
        border: 1px solid rgba(148, 163, 184, 0.12);
    }

    .sidebar-status-tile__label {
        font-size: 0.66rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: #93c5fd;
        margin-bottom: 0.25rem;
        line-height: 1.25;
    }

    .sidebar-status-tile__value {
        font-size: 1.08rem;
        font-weight: 700;
        color: #f8fafc;
    }

    .sidebar-footer {
        margin-top: 1rem;
        font-size: 0.84rem;
        color: #94a3b8;
    }

    .page-hero {
        position: relative;
        overflow: hidden;
        padding: 1.45rem 1.55rem;
        margin-bottom: 1.15rem;
        border-radius: var(--radius-xl);
        border: 1px solid rgba(148, 163, 184, 0.16);
        background: var(--bg-panel-dark);
        color: var(--text-inverse);
        box-shadow: var(--shadow-strong);
    }

    .page-hero::before,
    .page-hero::after {
        content: "";
        position: absolute;
        border-radius: 999px;
        pointer-events: none;
        filter: blur(8px);
    }

    .page-hero::before {
        width: 220px;
        height: 220px;
        top: -60px;
        right: -40px;
        background: radial-gradient(circle, rgba(245, 158, 11, 0.28), transparent 70%);
    }

    .page-hero::after {
        width: 320px;
        height: 320px;
        bottom: -180px;
        left: -120px;
        background: radial-gradient(circle, rgba(37, 99, 235, 0.34), transparent 72%);
    }

    .page-hero__eyebrow {
        position: relative;
        z-index: 1;
        font-size: 0.74rem;
        text-transform: uppercase;
        letter-spacing: 0.18em;
        color: var(--blue-soft);
        margin-bottom: 0.6rem;
    }

    .page-hero__title-row {
        position: relative;
        z-index: 1;
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 0.85rem;
    }

    .page-hero__title-row h1 {
        margin: 0;
        font-size: clamp(2rem, 4vw, 3.2rem);
        line-height: 1.02;
        color: var(--text-inverse);
    }

    .page-hero__body {
        position: relative;
        z-index: 1;
        margin: 0.85rem 0 0;
        max-width: 780px;
        color: #dbeafe;
        line-height: 1.65;
        font-size: 1rem;
    }

    .page-hero__badge {
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        padding: 0.42rem 0.8rem;
        border-radius: 999px;
        background: rgba(248, 250, 252, 0.12);
        border: 1px solid rgba(248, 250, 252, 0.18);
        color: #f8fafc;
        font-size: 0.76rem;
        text-transform: uppercase;
        letter-spacing: 0.14em;
    }

    .surface-card,
    [data-testid="stMetric"],
    .stAlert,
    details[data-testid="stExpander"] {
        border-radius: var(--radius-lg);
        border: 1px solid var(--line-soft);
        background: var(--bg-panel);
        box-shadow: var(--shadow-soft);
    }

    .surface-card {
        padding: 1.1rem 1.15rem;
        margin-bottom: 1rem;
    }

    .surface-card--solid {
        background: var(--bg-panel-strong);
    }

    .surface-card h3,
    .surface-card h4 {
        margin-top: 0;
        color: var(--text-main);
    }

    .surface-card p,
    .surface-card li {
        color: var(--text-soft);
    }

    .stat-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 0.95rem;
        margin: 0.15rem 0 1.25rem;
    }

    .stat-card {
        border-radius: 22px;
        border: 1px solid var(--line-soft);
        background: linear-gradient(180deg, rgba(14, 26, 48, 0.96), rgba(9, 18, 34, 0.94));
        padding: 1rem 1.05rem;
        box-shadow: var(--shadow-soft);
    }

    .stat-card__label {
        font-size: 0.72rem;
        text-transform: uppercase;
        letter-spacing: 0.16em;
        color: var(--text-muted);
        margin-bottom: 0.4rem;
    }

    .stat-card__value {
        font-size: clamp(1.45rem, 2vw, 2.15rem);
        font-weight: 700;
        color: var(--text-main);
        line-height: 1.05;
    }

    .stat-card__meta {
        margin-top: 0.5rem;
        color: var(--text-soft);
        font-size: 0.92rem;
        line-height: 1.5;
    }

    .pill-row {
        display: flex;
        flex-wrap: wrap;
        gap: 0.55rem;
        margin-top: 0.8rem;
    }

    .pill {
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        padding: 0.38rem 0.7rem;
        border-radius: 999px;
        font-size: 0.74rem;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        border: 1px solid transparent;
    }

    .pill--info {
        background: rgba(37, 99, 235, 0.10);
        color: var(--blue);
        border-color: rgba(37, 99, 235, 0.16);
    }

    .pill--success {
        background: rgba(16, 185, 129, 0.10);
        color: #047857;
        border-color: rgba(16, 185, 129, 0.16);
    }

    .pill--warning {
        background: rgba(245, 158, 11, 0.12);
        color: #b45309;
        border-color: rgba(245, 158, 11, 0.18);
    }

    .pill--danger {
        background: rgba(244, 63, 94, 0.10);
        color: #be123c;
        border-color: rgba(244, 63, 94, 0.16);
    }

    .list-stack {
        display: grid;
        gap: 0.8rem;
        margin-top: 0.85rem;
    }

    .list-row {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 1rem;
        padding: 0.9rem 0.95rem;
        border-radius: 18px;
        background: rgba(13, 24, 43, 0.82);
        border: 1px solid rgba(148, 163, 184, 0.16);
    }

    .list-row__title {
        font-weight: 700;
        color: var(--text-main);
        margin-bottom: 0.18rem;
    }

    .list-row__text {
        color: var(--text-soft);
        line-height: 1.55;
        font-size: 0.93rem;
    }

    .list-row__meta {
        color: var(--text-muted);
        font-size: 0.84rem;
        white-space: nowrap;
    }

    .section-kicker {
        font-size: 0.74rem;
        text-transform: uppercase;
        letter-spacing: 0.16em;
        color: var(--blue);
        margin-bottom: 0.35rem;
    }

    .data-table-wrap {
        overflow-x: auto;
        border-radius: 20px;
        border: 1px solid var(--line-soft);
        background: rgba(9, 18, 34, 0.94);
        box-shadow: var(--shadow-soft);
    }

    .data-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 0.94rem;
    }

    .data-table thead tr {
        background: rgba(5, 12, 24, 0.98);
    }

    .data-table th {
        padding: 0.95rem 1rem;
        color: #dbeafe;
        text-align: left;
        font-size: 0.76rem;
        letter-spacing: 0.14em;
        text-transform: uppercase;
        border-bottom: 1px solid rgba(148, 163, 184, 0.10);
    }

    .data-table td {
        padding: 0.92rem 1rem;
        color: var(--text-main);
        border-bottom: 1px solid rgba(148, 163, 184, 0.16);
    }

    .data-table tbody tr:nth-child(even) {
        background: rgba(11, 20, 36, 0.88);
    }

    .data-table tbody tr:hover {
        background: rgba(37, 99, 235, 0.12);
    }

    [data-testid="stMetric"] {
        padding: 1rem 1.05rem;
        min-height: 128px;
    }

    [data-testid="stMetricLabel"] {
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.15em;
        font-size: 0.72rem;
    }

    [data-testid="stMetricValue"] {
        color: var(--text-main);
        font-weight: 700;
        font-family: "Bahnschrift", "Segoe UI Variable Display", "Segoe UI", sans-serif;
    }

    .stButton > button,
    .stDownloadButton > button {
        width: 100%;
        min-height: 3.15rem;
        border-radius: 16px;
        border: 1px solid rgba(96, 165, 250, 0.28);
        background: linear-gradient(135deg, #2563eb, #1d4ed8 55%, #f59e0b 150%);
        color: #eff6ff;
        box-shadow: 0 16px 32px rgba(37, 99, 235, 0.24);
        font-weight: 700;
        transition: transform 160ms ease, box-shadow 160ms ease, border-color 160ms ease;
    }

    .stButton > button[kind="secondary"],
    .stDownloadButton > button[kind="secondary"] {
        background: rgba(14, 26, 48, 0.96);
        color: var(--text-main);
        border-color: rgba(148, 163, 184, 0.22);
        box-shadow: 0 14px 28px rgba(15, 23, 42, 0.10);
    }

    .stButton > button:hover,
    .stDownloadButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 18px 36px rgba(15, 23, 42, 0.16);
    }

    div[role="radiogroup"] {
        gap: 0.5rem;
    }

    div[role="radiogroup"] > label,
    div[role="radiogroup"] [data-baseweb="radio"] {
        border-radius: 16px;
        border: 1px solid rgba(148, 163, 184, 0.18);
        background: rgba(14, 26, 48, 0.88);
        padding: 0.7rem 0.9rem;
        transition: transform 150ms ease, border-color 150ms ease, background 150ms ease;
    }

    div[role="radiogroup"] > label *,
    div[role="radiogroup"] [data-baseweb="radio"] * {
        color: var(--text-soft) !important;
    }

    [data-testid="stSidebar"] div[role="radiogroup"] > label,
    [data-testid="stSidebar"] div[role="radiogroup"] [data-baseweb="radio"] {
        background: rgba(15, 23, 42, 0.70);
        border-color: rgba(148, 163, 184, 0.14);
    }

    div[role="radiogroup"] > label:hover,
    div[role="radiogroup"] [data-baseweb="radio"]:hover {
        transform: translateY(-1px);
        border-color: rgba(59, 130, 246, 0.28);
    }

    div[role="radiogroup"] > label:has(input:checked),
    div[role="radiogroup"] [data-baseweb="radio"]:has(input:checked) {
        background: linear-gradient(135deg, rgba(37, 99, 235, 0.26), rgba(245, 158, 11, 0.16));
        border-color: rgba(96, 165, 250, 0.38);
        box-shadow: 0 10px 24px rgba(37, 99, 235, 0.16);
    }

    div[role="radiogroup"] > label:has(input:checked) *,
    div[role="radiogroup"] [data-baseweb="radio"]:has(input:checked) * {
        color: var(--text-main) !important;
    }

    [data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked),
    [data-testid="stSidebar"] div[role="radiogroup"] [data-baseweb="radio"]:has(input:checked) {
        background: linear-gradient(135deg, rgba(37, 99, 235, 0.26), rgba(245, 158, 11, 0.18));
        border-color: rgba(96, 165, 250, 0.34);
    }

    [data-baseweb="input"] > div,
    [data-baseweb="select"] > div,
    .stTextArea textarea {
        border-radius: 16px;
        border: 1px solid rgba(148, 163, 184, 0.22);
        background: rgba(14, 26, 48, 0.96);
        color: var(--text-main);
    }

    [data-baseweb="input"] input,
    [data-baseweb="select"] input,
    [data-baseweb="select"] span,
    textarea {
        color: var(--text-main) !important;
    }

    input::placeholder,
    textarea::placeholder {
        color: var(--text-muted) !important;
    }

    [data-testid="stFileUploaderDropzone"] {
        border-radius: 22px;
        border: 1.6px dashed rgba(59, 130, 246, 0.26);
        background: linear-gradient(180deg, rgba(14, 26, 48, 0.96), rgba(9, 18, 34, 0.94));
    }

    [data-testid="stFileUploaderDropzone"] * {
        color: var(--text-main);
    }

    [data-testid="stFileUploaderDropzone"] button {
        background: linear-gradient(135deg, rgba(37, 99, 235, 0.24), rgba(15, 23, 42, 0.94));
        color: var(--text-main);
        border: 1px solid rgba(96, 165, 250, 0.24);
    }

    .stTabs [data-baseweb="tab-list"] {
        gap: 0.45rem;
        padding: 0.36rem;
        margin-bottom: 1rem;
        border-radius: 999px;
        background: rgba(15, 23, 42, 0.92);
        border: 1px solid rgba(148, 163, 184, 0.14);
    }

    .stTabs [data-baseweb="tab"] {
        height: auto;
        padding: 0.72rem 1rem;
        border-radius: 999px;
        color: #dbeafe;
        font-weight: 600;
    }

    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, rgba(37, 99, 235, 0.24), rgba(245, 158, 11, 0.18));
        color: #f8fafc;
    }

    .stAlert p {
        color: var(--text-main);
        line-height: 1.55;
    }

    details[data-testid="stExpander"] summary {
        padding: 0.85rem 1rem;
        font-weight: 700;
        color: var(--text-main);
    }

    details[data-testid="stExpander"] > div {
        padding: 0 1rem 1rem;
    }

    .stDataFrame,
    [data-testid="stMetricDelta"],
    .stCodeBlock {
        color: var(--text-main);
    }

    .stDeployButton {
        display: none;
    }

    [data-testid="stProgressBar"] > div > div {
        background: linear-gradient(90deg, #2563eb, #60a5fa 55%, #f59e0b);
    }

    @media (max-width: 900px) {
        .main .block-container {
            padding-top: 1rem;
            padding-bottom: 3rem;
        }

        .page-hero {
            padding: 1.15rem 1.1rem;
        }

        .page-hero__title-row h1 {
            font-size: 2rem;
        }
    }

    @media (prefers-reduced-motion: reduce) {
        .stButton > button,
        .stDownloadButton > button,
        div[role="radiogroup"] > label,
        div[role="radiogroup"] [data-baseweb="radio"] {
            transition: none !important;
        }
    }
</style>
"""


def apply_custom_css():
    """Global CSS uygula."""
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def format_surface_label(surface: Optional[str]) -> str:
    """Internal surface value'yu arayuz etiketi olarak dondur."""
    if surface is None:
        return "-"
    return SURFACE_LABELS.get(str(surface).lower(), str(surface))


def format_confidence_label(level: Optional[str]) -> str:
    """Guven seviyesini Turkce etikete cevir."""
    if level is None:
        return "-"
    return CONFIDENCE_LABELS.get(str(level).upper(), str(level))


def format_compare_status_label(status: Optional[str]) -> str:
    """Prediction compare durumunu Turkcelestir."""
    if status is None:
        return "-"
    return COMPARE_STATUS_LABELS.get(str(status), str(status))


def format_boolean_label(value: Optional[str]) -> str:
    """yes/no etiketlerini Turkcelestir."""
    if value is None:
        return "-"
    return BOOLEAN_LABELS.get(str(value).lower(), str(value))


def _html(block: str) -> str:
    """HTML bloklarini markdown code block'a dusmeden temizle."""
    return dedent(block).strip()


def render_page_header(title: str, description: str, badge: Optional[str] = None, eyebrow: str = "Rally Result Prediction"):
    """Tum sayfalarda kullanilan hero baslik."""
    badge_html = f'<div class="page-hero__badge">{escape(badge)}</div>' if badge else ""
    st.markdown(
        _html(f"""
        <section class="page-hero">
            <div class="page-hero__eyebrow">{escape(eyebrow)}</div>
            <div class="page-hero__title-row">
                <h1>{escape(title)}</h1>
                {badge_html}
            </div>
            <p class="page-hero__body">{escape(description)}</p>
        </section>
        """),
        unsafe_allow_html=True,
    )


def render_stat_cards(cards):
    """HTML KPI kartlari goster."""
    html_cards = []
    for card in cards:
        html_cards.append(
            _html(f"""
            <article class="stat-card">
                <div class="stat-card__label">{escape(str(card.get("label", "")))}</div>
                <div class="stat-card__value">{escape(str(card.get("value", "")))}</div>
                <div class="stat-card__meta">{escape(str(card.get("meta", "")))}</div>
            </article>
            """)
        )
    st.markdown(_html(f"""
    <section class="stat-grid">{"".join(html_cards)}</section>
    """), unsafe_allow_html=True)


def show_html_table(df: pd.DataFrame, max_rows: Optional[int] = None):
    """DataFrame'i HTML tablo olarak goster."""
    if df is None or len(df) == 0:
        st.info("Veri yok")
        return

    max_rows = max_rows or MAX_TABLE_ROWS
    df_display = df.head(max_rows)
    html = df_display.to_html(classes="data-table", index=False, escape=False)
    st.markdown(f'<div class="data-table-wrap">{html}</div>', unsafe_allow_html=True)

    if len(df) > max_rows:
        st.caption(f"Ilk {max_rows} kayit gosteriliyor (toplam: {len(df)})")


def show_db_status_sidebar(db_info: dict, kml_count: int = 0):
    """Sidebar icin kisa sistem ozeti goster."""
    db_value = "Hazir" if db_info.get("exists") else "Eksik"
    result_value = f"{db_info.get('result_count', 0):,}" if db_info.get("exists") else "0"
    geometry_value = f"{db_info.get('geometry_count', 0):,}" if db_info.get("exists") else "0"

    st.sidebar.markdown(
        _html(f"""
        <section class="sidebar-status-card">
            <div class="sidebar-section-label">Calisma Durumu</div>
            <p>Sonuc toplama, geometri kapsami ve yerel dosyalar tek bakista gorunsun.</p>
            <div class="sidebar-status-grid">
                <div class="sidebar-status-tile">
                    <div class="sidebar-status-tile__label">Veritabani</div>
                    <div class="sidebar-status-tile__value">{escape(db_value)}</div>
                </div>
                <div class="sidebar-status-tile">
                    <div class="sidebar-status-tile__label">Sonuclar</div>
                    <div class="sidebar-status-tile__value">{escape(result_value)}</div>
                </div>
                <div class="sidebar-status-tile">
                    <div class="sidebar-status-tile__label">Geometri</div>
                    <div class="sidebar-status-tile__value">{escape(geometry_value)}</div>
                </div>
                <div class="sidebar-status-tile">
                    <div class="sidebar-status-tile__label">KML Arsivi</div>
                    <div class="sidebar-status-tile__value">{escape(str(kml_count))}</div>
                </div>
            </div>
        </section>
        """),
        unsafe_allow_html=True,
    )


def show_metric_row(metrics: list):
    """Metrik satiri goster."""
    cols = st.columns(len(metrics))
    for col, (label, value) in zip(cols, metrics):
        col.metric(label, value)


def show_error(message: str):
    """Hata mesaji goster."""
    st.error(f"Hata: {message}")


def show_success(message: str):
    """Basari mesaji goster."""
    st.success(message)


def format_time(seconds: float) -> str:
    """Saniyeyi MM:SS.ms formatina cevir."""
    if seconds <= 0:
        return "--:--"

    minutes = int(seconds // 60)
    remaining = seconds % 60
    return f"{minutes}:{remaining:05.2f}"


def create_driver_selector(drivers: list, key: str = "driver_select") -> dict:
    """Pilot secici olustur ve secilen pilotu dondur."""
    if not drivers:
        st.warning("Pilot bulunamadi!")
        return None

    driver_options = {
        f"{d['driver_name']} ({d.get('normalized_class', d['car_class'])})": d
        for d in drivers
    }

    selected_label = st.selectbox("Pilot Sec", list(driver_options.keys()), key=key)
    return driver_options[selected_label]


def create_rally_selector(rallies: list, key: str = "rally_select", include_all: bool = False) -> Optional[str]:
    """Ralli secici olustur ve secilen rally_id'yi dondur."""
    if not rallies:
        st.warning("Ralli bulunamadi!")
        return None

    if include_all:
        options = ["Tum Ralliler"] + [f"{r['rally_name']} ({r['rally_id']})" for r in rallies]
    else:
        options = [f"{r['rally_name']} ({r['rally_id']})" for r in rallies]

    selected = st.selectbox("Rally Sec", options, key=key)

    if include_all and selected == "Tum Ralliler":
        return None

    return selected.split("(")[-1].replace(")", "").strip()


def create_stage_inputs(prefix: str = "") -> dict:
    """Etap bilgisi input'larini olustur."""
    col1, col2, col3 = st.columns(3)

    with col1:
        stage_length = st.number_input(
            "Etap Uzunlugu (km)",
            min_value=1.0,
            max_value=50.0,
            value=15.0,
            step=0.5,
            key=f"{prefix}stage_length",
        )

    with col2:
        surface = st.selectbox(
            "Zemin",
            ["gravel", "asphalt"],
            format_func=format_surface_label,
            key=f"{prefix}surface",
        )

    with col3:
        stage_number = st.number_input(
            "Etap No",
            min_value=1,
            max_value=20,
            value=3,
            key=f"{prefix}stage_number",
        )

    return {
        "stage_length_km": stage_length,
        "surface": surface,
        "stage_number": stage_number,
    }
