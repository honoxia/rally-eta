"""
Rally ETA v2.0 - Veri Cekme Sayfasi
TOSFED scraper ve database yonetimi.
Gelismis hata gosterimi ve Excel export.
"""

import streamlit as st
import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime
import tempfile
import sys
import io
import re

# Shared modülleri import et
sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.config import get_db_path, PROJECT_ROOT, FINISHED_STATUSES
from shared.db_helpers import get_database_info, ensure_stage_results_table, migrate_add_normalized_columns
from shared.ui_components import render_page_header, show_html_table

_src_path = str(PROJECT_ROOT)
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)

from src.data.geometry_merge import export_master_geometry_db, merge_geometry_database
from src.data.results_merge import merge_results_database


def render():
    """Veri cekme sayfasini render et."""
    render_page_header(
        "Veri Alim Merkezi",
        "TOSFED sonuc taramasi, veritabani birlestirme ve geometri disari-iceri aktarim akislarini buradan yonetin.",
        badge="Veri Alimi",
        eyebrow="Sonuc Operasyonlari",
    )

    section_options = ["TOSFED Scraper", "Database Yukle"]
    section_override = st.session_state.pop("scraper_section_override", None)
    if section_override in section_options:
        st.session_state["scraper_section"] = section_override

    section = st.radio(
        "Scraper Bolumu",
        section_options,
        horizontal=True,
        key="scraper_section",
        format_func=lambda option: {
            "TOSFED Scraper": "TOSFED Tarama",
            "Database Yukle": "Veritabani Yukle",
        }.get(option, option),
        label_visibility="collapsed",
    )

    _render_workflow_context_banner()

    if section == "TOSFED Scraper":
        _render_tosfed_scraper()
    elif section == "Database Yukle":
        _render_db_upload()


def _render_workflow_context_banner():
    context = st.session_state.get("workflow_context")
    if not isinstance(context, dict):
        return
    if context.get("action_target_page") != "Veri Cek":
        return

    parts = [
        context.get("issue_title") or context.get("issue_type"),
        f"Rally {context['rally_id']}" if context.get("rally_id") else None,
        context.get("stage_id"),
        context.get("driver_name"),
    ]
    st.info(" | ".join(part for part in parts if part))
    if context.get("recommended_action"):
        st.caption(f"Onerilen aksiyon: {context['recommended_action']}")
    if st.button("Aksiyon Baglamini Temizle", key="scraper_workflow_context_dismiss"):
        st.session_state.pop("workflow_context", None)
        st.rerun()


def _resolve_results_workflow_issue_after_merge():
    context = st.session_state.get("workflow_context")
    if not isinstance(context, dict):
        return None
    if context.get("action_target_page") != "Veri Cek":
        return None
    if context.get("issue_type") != "actual_missing":
        return None
    if not context.get("prediction_id") or not context.get("rally_id") or not context.get("stage_id"):
        return None

    stage_match = re.search(r"_ss(\d+)$", str(context["stage_id"]))
    if not stage_match:
        return None
    stage_number = int(stage_match.group(1))

    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    try:
        placeholders = ",".join("?" for _ in FINISHED_STATUSES)
        rows = [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT driver_name, car_class, time_str, time_seconds
                FROM stage_results
                WHERE rally_id = ? AND stage_id = ? AND time_seconds > 0
                  AND COALESCE(status, 'FINISHED') IN ({placeholders})
                """,
                [str(context["rally_id"]), str(context["stage_id"]), *FINISHED_STATUSES],
            ).fetchall()
        ]
    finally:
        conn.close()

    if not rows:
        return {
            "compared": False,
            "matched_count": 0,
            "message": "Merge tamamlandi ama ilgili etap icin gercek sonuc hala bulunamadi.",
        }

    from src.prediction.prediction_service import PredictionService

    service = PredictionService(db_path=get_db_path(), model_path=None)
    compare_summary = service.compare_predictions_with_live_stage(
        rally_id=str(context["rally_id"]),
        stage_number=stage_number,
        stage_results=rows,
        driver_id=context.get("driver_id"),
        driver_name=context.get("driver_name"),
    )

    if compare_summary.get("matched_count", 0) > 0:
        service.mark_prediction_issue_resolved(
            prediction_id=int(context["prediction_id"]),
            issue_types=["actual_missing"],
            resolution_source="results_merge_auto_compare",
            resolution_note=f"Gercek sonuc merge edildi ve compare calisti: {context['stage_id']}",
        )
        st.session_state.pop("workflow_context", None)
        return {
            "compared": True,
            "matched_count": compare_summary.get("matched_count", 0),
            "message": "Gercek sonuc bulundu ve prediction_log kaydi compare ile kapatildi.",
        }

    return {
        "compared": bool(compare_summary.get("compared_count", 0)),
        "matched_count": compare_summary.get("matched_count", 0),
        "message": "Merge tamamlandi ancak hedef tahmin kaydi henuz matched durumuna gecmedi.",
    }


def _render_tosfed_scraper():
    """TOSFED scraper bölümü - 2 aşamalı akış."""
    st.subheader("TOSFED'den Veri Cek")

    # Session state initialization
    if 'found_rallies' not in st.session_state:
        st.session_state.found_rallies = None
    if 'rally_surfaces' not in st.session_state:
        st.session_state.rally_surfaces = {}
    if 'scrape_results' not in st.session_state:
        st.session_state.scrape_results = None
    if 'scrape_errors' not in st.session_state:
        st.session_state.scrape_errors = []
    if 'scrape_log' not in st.session_state:
        st.session_state.scrape_log = []

    # Surface seçenekleri
    SURFACE_OPTIONS = ["Toprak (Gravel)", "Asfalt (Asphalt)", "Kar (Snow)", "Karışık (Mixed)"]
    SURFACE_MAP = {"Toprak": "gravel", "Asfalt": "asphalt", "Kar": "snow", "Karışık": "mixed"}

    # ===== ADIM 1: Rally ID aralığı ve tarama =====
    st.markdown("### Adım 1: Rallileri Tara")
    col1, col2 = st.columns(2)
    with col1:
        start_id = st.number_input("Baslangic Rally ID", min_value=1, value=1)
    with col2:
        end_id = st.number_input("Bitis Rally ID", min_value=1, value=180)

    if st.button("Rallileri Tara", type="secondary"):
        if end_id < start_id:
            st.error("Bitis ID >= Baslangic ID olmali!")
            return
        _scan_rallies(start_id, end_id)

    # ===== ADIM 2: Bulunan ralliler ve surface seçimi =====
    if st.session_state.found_rallies:
        st.markdown("### Adım 2: Zemin Tipi Sec")
        st.info(f"{len(st.session_state.found_rallies)} ralli bulundu. Her biri icin zemin tipini secin.")

        # Tüm ralliler için toplu seçim
        col_bulk1, col_bulk2 = st.columns([3, 1])
        with col_bulk1:
            bulk_surface = st.selectbox("Tumu icin zemin sec:", SURFACE_OPTIONS, key="bulk_surface")
        with col_bulk2:
            if st.button("Tumune Uygula"):
                bulk_value = next((v for k, v in SURFACE_MAP.items() if k in bulk_surface), "gravel")
                for rally in st.session_state.found_rallies:
                    st.session_state.rally_surfaces[rally['rally_id']] = bulk_value
                st.rerun()

        st.markdown("---")

        # Her ralli için ayrı seçim
        for i, rally in enumerate(st.session_state.found_rallies):
            rally_id = rally['rally_id']
            rally_name = rally['rally_name']

            col_id, col_name, col_surface = st.columns([1, 3, 2])
            with col_id:
                st.write(f"**{rally_id}**")
            with col_name:
                st.write(rally_name)
            with col_surface:
                # Mevcut seçimi bul
                current_surface = st.session_state.rally_surfaces.get(rally_id, "gravel")
                current_idx = 0
                for idx, opt in enumerate(SURFACE_OPTIONS):
                    if current_surface in opt.lower():
                        current_idx = idx
                        break

                selected = st.selectbox(
                    "Zemin",
                    SURFACE_OPTIONS,
                    index=current_idx,
                    key=f"surface_{rally_id}",
                    label_visibility="collapsed"
                )
                # Seçimi kaydet
                surface_value = next((v for k, v in SURFACE_MAP.items() if k in selected), "gravel")
                st.session_state.rally_surfaces[rally_id] = surface_value

        st.markdown("---")

        # ===== ADIM 3: Veri çekme =====
        st.markdown("### Adım 3: Verileri Cek")
        if st.button("Verileri Cek", type="primary"):
            st.session_state.scrape_results = []
            st.session_state.scrape_errors = []
            st.session_state.scrape_log = []
            _run_scraper_with_surfaces(st.session_state.found_rallies, st.session_state.rally_surfaces)

    # Sonuçları göster
    if st.session_state.scrape_results:
        _display_scrape_results()


def _scan_rallies(start_id: int, end_id: int):
    """Rally ID aralığını tara ve bulunan rallileri listele (sonuçları çekme)."""
    try:
        src_path = str(PROJECT_ROOT)
        if src_path not in sys.path:
            sys.path.insert(0, src_path)

        from src.scraper.tosfed_sonuc_scraper import TOSFEDSonucScraper

        scraper = TOSFEDSonucScraper()
        rally_ids = list(range(int(start_id), int(end_id) + 1))

        progress = st.progress(0)
        status_text = st.empty()

        found_rallies = []

        for i, rally_id in enumerate(rally_ids):
            status_text.text(f"Rally {rally_id} kontrol ediliyor... ({i+1}/{len(rally_ids)})")
            progress.progress((i + 1) / len(rally_ids))

            try:
                rally_data = scraper.fetch_rally_stages(rally_id)
                if rally_data and rally_data.get('stages'):
                    found_rallies.append({
                        'rally_id': rally_id,
                        'rally_name': rally_data.get('rally_name', f'Rally {rally_id}'),
                        'stage_count': len(rally_data.get('stages', []))
                    })
            except:
                pass

        progress.empty()
        status_text.empty()

        st.session_state.found_rallies = found_rallies
        st.session_state.rally_surfaces = {r['rally_id']: 'gravel' for r in found_rallies}

        if found_rallies:
            st.success(f"{len(found_rallies)} ralli bulundu!")
        else:
            st.warning("Hic ralli bulunamadi.")

    except Exception as e:
        st.error(f"Tarama hatasi: {e}")


def _run_scraper_with_surfaces(rallies: list, surfaces: dict):
    """Her ralli için belirlenen surface ile veri çek."""
    try:
        src_path = str(PROJECT_ROOT)
        if src_path not in sys.path:
            sys.path.insert(0, src_path)

        from src.scraper.tosfed_sonuc_scraper import TOSFEDSonucScraper

        scraper = TOSFEDSonucScraper()

        progress = st.progress(0)
        status_text = st.empty()

        all_results = []
        errors = []
        logs = []

        for i, rally in enumerate(rallies):
            rally_id = rally['rally_id']
            rally_name = rally['rally_name']
            surface = surfaces.get(rally_id, 'gravel')

            status_text.text(f"Rally {rally_id} ({rally_name}) verileri cekiliyor... ({i+1}/{len(rallies)})")
            progress.progress((i + 1) / len(rallies))

            logs.append(f"[INFO] Rally {rally_id}: {rally_name} - Zemin: {surface}")

            try:
                rally_data = scraper.fetch_rally_stages(rally_id)

                if rally_data:
                    stages = rally_data.get('stages', [])
                    logs.append(f"[OK] Rally {rally_id}: {len(stages)} etap bulundu")

                    for stage in stages:
                        stage_name = stage.get('stage_name', 'Bilinmeyen')
                        stage_number = stage.get('stage_number', 0)
                        results = stage.get('results', [])

                        logs.append(f"    SS{stage_number}: {stage_name} - {len(results)} sonuc")

                        # stage_length_km'i stage'den al
                        stage_length_km = stage.get('stage_length_km', 0)

                        for result in results:
                            try:
                                time_str = result.get('time_str', '')
                                time_seconds = _parse_time(time_str)
                                driver_name = result.get('driver_name', '')
                                car_number = result.get('car_number', '')
                                diff_str = result.get('time_diff', '')

                                result_id = f"{rally_id}_ss{stage_number}_{car_number}"

                                row = {
                                    'result_id': result_id,
                                    'rally_id': str(rally_id),
                                    'rally_name': rally_name,
                                    'stage_number': stage_number,
                                    'stage_name': stage_name,
                                    'stage_length_km': stage_length_km,
                                    'car_number': car_number,
                                    'driver_name': driver_name,
                                    'co_driver_name': result.get('co_driver_name', ''),
                                    'car_class': result.get('car_class', ''),
                                    'vehicle': result.get('car_model', ''),
                                    'time_str': time_str,
                                    'time_seconds': time_seconds,
                                    'diff_str': diff_str,
                                    'diff_seconds': _parse_time(diff_str) if diff_str else 0,
                                    'surface': surface
                                }
                                all_results.append(row)

                            except Exception as e:
                                errors.append({
                                    'rally_id': rally_id,
                                    'stage': stage_name,
                                    'driver': result.get('driver_name', 'Bilinmeyen'),
                                    'error': str(e)
                                })

            except Exception as e:
                logs.append(f"[ERROR] Rally {rally_id}: {str(e)}")
                errors.append({
                    'rally_id': rally_id,
                    'stage': '-',
                    'driver': '-',
                    'error': str(e)
                })

        progress.empty()
        status_text.empty()

        st.session_state.scrape_results = all_results
        st.session_state.scrape_errors = errors
        st.session_state.scrape_log = logs

        if all_results:
            st.success(f"Tamamlandi! {len(all_results)} sonuc bulundu.")
        else:
            st.warning("Hic sonuc bulunamadi.")

    except Exception as e:
        st.error(f"Scraper hatasi: {e}")


def _run_scraper(start_id: int, end_id: int, surface: str = "gravel"):
    """Scraper'ı çalıştır ve sonuçları session state'e kaydet (eski fonksiyon - geriye uyumluluk).

    Args:
        start_id: Başlangıç rally ID
        end_id: Bitiş rally ID
        surface: Zemin tipi (gravel/asphalt) - kullanıcı tarafından seçilir
    """
    try:
        # src klasörünü path'e ekle
        src_path = str(PROJECT_ROOT)
        if src_path not in sys.path:
            sys.path.insert(0, src_path)

        from src.scraper.tosfed_sonuc_scraper import TOSFEDSonucScraper

        scraper = TOSFEDSonucScraper()
        rally_ids = list(range(int(start_id), int(end_id) + 1))

        progress = st.progress(0)
        status_text = st.empty()
        log_container = st.container()

        all_results = []
        errors = []
        logs = []

        logs.append(f"[INFO] Secilen zemin: {surface}")

        for i, rally_id in enumerate(rally_ids):
            status_text.text(f"Rally {rally_id} kontrol ediliyor... ({i+1}/{len(rally_ids)})")
            progress.progress((i + 1) / len(rally_ids))

            try:
                rally_data = scraper.fetch_rally_stages(rally_id)

                if rally_data:
                    rally_name = rally_data.get('rally_name', 'Bilinmeyen')
                    stages = rally_data.get('stages', [])

                    logs.append(f"[OK] Rally {rally_id}: {rally_name} - {len(stages)} etap bulundu (zemin: {surface})")

                    for stage in stages:
                        stage_name = stage.get('stage_name', 'Bilinmeyen')
                        stage_number = stage.get('stage_number', 0)
                        stage_length_km = stage.get('stage_length_km', 0)
                        results = stage.get('results', [])

                        logs.append(f"    SS{stage_number}: {stage_name} ({stage_length_km}km) - {len(results)} sonuc")

                        for result in results:
                            try:
                                time_str = result.get('time_str', '')
                                time_seconds = _parse_time(time_str)
                                driver_name = result.get('driver_name', '')
                                car_number = result.get('car_number', '')
                                diff_str = result.get('time_diff', '')

                                # result_id: eski format - rally_id_ss{stage}_{car_number}
                                result_id = f"{rally_id}_ss{stage_number}_{car_number}"

                                # Tablo yapısına uygun row
                                row = {
                                    'result_id': result_id,
                                    'rally_id': str(rally_id),
                                    'rally_name': rally_name,
                                    'stage_number': stage_number,
                                    'stage_name': stage_name,
                                    'stage_length_km': stage_length_km,
                                    'car_number': car_number,
                                    'driver_name': driver_name,
                                    'co_driver_name': result.get('co_driver_name', ''),
                                    'car_class': result.get('car_class', ''),
                                    'vehicle': result.get('car_model', ''),
                                    'time_str': time_str,
                                    'time_seconds': time_seconds,
                                    'diff_str': diff_str,
                                    'diff_seconds': _parse_time(diff_str) if diff_str else 0,
                                    'surface': surface  # Kullanıcının seçtiği zemin
                                }
                                all_results.append(row)

                            except Exception as e:
                                errors.append({
                                    'rally_id': rally_id,
                                    'stage': stage_name,
                                    'driver': result.get('driver_name', 'Bilinmeyen'),
                                    'error': str(e)
                                })
                else:
                    logs.append(f"[SKIP] Rally {rally_id}: Veri bulunamadi veya ralli degil")

            except Exception as e:
                logs.append(f"[ERROR] Rally {rally_id}: {str(e)}")
                errors.append({
                    'rally_id': rally_id,
                    'stage': '-',
                    'driver': '-',
                    'error': str(e)
                })

        # Session state'e kaydet
        st.session_state.scrape_results = all_results
        st.session_state.scrape_errors = errors
        st.session_state.scrape_log = logs

        # Özet
        status_text.empty()
        progress.empty()

        if all_results:
            st.success(f"Scrape tamamlandi! {len(all_results)} sonuc bulundu.")
        else:
            st.warning("Hic sonuc bulunamadi. Log'lari kontrol edin.")

    except Exception as e:
        st.error(f"Scraper hatasi: {e}")
        import traceback
        st.code(traceback.format_exc())


def _display_scrape_results():
    """Scrape sonuçlarını göster."""
    results = st.session_state.scrape_results
    errors = st.session_state.scrape_errors
    logs = st.session_state.scrape_log

    # Tabs for different views
    tab_preview, tab_log, tab_errors = st.tabs([
        f"Onizleme ({len(results)} sonuc)",
        f"Log ({len(logs)} satir)",
        f"Hatalar ({len(errors)})"
    ])

    with tab_preview:
        if results:
            df = pd.DataFrame(results)
            st.markdown(f"**Toplam: {len(df)} satir**")

            # Özet istatistikler
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Ralli Sayisi", df['rally_id'].nunique())
            col2.metric("Etap Sayisi", df[['rally_id', 'stage_number']].drop_duplicates().shape[0])
            col3.metric("Pilot Sayisi", df['driver_name'].nunique())
            col4.metric("Sonuc Sayisi", len(df))

            # Tablo önizleme
            st.markdown("**Ilk 50 satir:**")
            show_html_table(df.head(50))

            st.markdown("---")

            # Export ve Save butonları
            col_excel, col_db, col_both = st.columns(3)

            with col_excel:
                if st.button("Excel'e Kaydet", type="secondary", use_container_width=True):
                    _export_to_excel(df)

            with col_db:
                if st.button("Veritabanina Kaydet", type="secondary", use_container_width=True):
                    _save_to_database(df)

            with col_both:
                if st.button("Ikisine de Kaydet", type="primary", use_container_width=True):
                    _export_to_excel(df)
                    _save_to_database(df)

        else:
            st.info("Sonuc yok. Scraper calistirin.")

    with tab_log:
        if logs:
            log_text = "\n".join(logs)
            st.code(log_text, language=None)
        else:
            st.info("Log yok.")

    with tab_errors:
        if errors:
            error_df = pd.DataFrame(errors)
            st.warning(f"{len(errors)} hata bulundu:")
            show_html_table(error_df)
        else:
            st.success("Hata yok!")


def _export_to_excel(df: pd.DataFrame):
    """DataFrame'i Excel'e kaydet."""
    try:
        exports_dir = PROJECT_ROOT / "exports"
        exports_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"scrape_results_{timestamp}.xlsx"
        file_path = exports_dir / filename

        # Excel'e yaz
        df.to_excel(file_path, index=False, sheet_name="results")

        st.success(f"Excel kaydedildi: {file_path}")

        # Download butonu
        with open(file_path, 'rb') as f:
            st.download_button(
                "Excel'i Indir",
                data=f.read(),
                file_name=filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

    except ImportError:
        st.error("Excel export icin openpyxl gerekiyor: pip install openpyxl")
    except Exception as e:
        st.error(f"Excel export hatasi: {e}")


def _save_to_database(df: pd.DataFrame):
    """DataFrame'i database'e kaydet.

    NOT: Eski çalışan yapı kullanılıyor:
    - result_id TEXT PRIMARY KEY
    - INSERT OR IGNORE (duplicate'leri atla)
    """
    try:
        db_path = get_db_path()
        ensure_stage_results_table(db_path)

        # Normalizer yukle
        try:
            src_path = str(PROJECT_ROOT)
            if src_path not in sys.path:
                sys.path.insert(0, src_path)
            from src.data.car_class_normalizer import CarClassNormalizer
            normalizer = CarClassNormalizer()
        except Exception:
            normalizer = None

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        saved = 0
        skipped = 0
        errors = 0
        error_msgs = []

        for _, row in df.iterrows():
            try:
                # normalized_class hesapla
                raw_class = row.get('car_class', '')
                normalized_class = normalizer.normalize(raw_class) if normalizer and raw_class else raw_class

                # INSERT OR IGNORE - duplicate result_id varsa atla
                cursor.execute("""
                    INSERT OR IGNORE INTO stage_results
                    (result_id, rally_id, rally_name, stage_number, stage_name, stage_length_km,
                     car_number, driver_name, co_driver_name, car_class, normalized_class, vehicle,
                     time_str, time_seconds, diff_str, diff_seconds, surface)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    row['result_id'],
                    row['rally_id'],
                    row['rally_name'],
                    row['stage_number'],
                    row['stage_name'],
                    row.get('stage_length_km', 0),
                    row['car_number'],
                    row['driver_name'],
                    row.get('co_driver_name', ''),
                    raw_class,
                    normalized_class,
                    row.get('vehicle', ''),
                    row['time_str'],
                    row['time_seconds'],
                    row.get('diff_str', ''),
                    row.get('diff_seconds', 0),
                    row['surface']
                ])

                if cursor.rowcount > 0:
                    saved += 1
                else:
                    skipped += 1  # Zaten var, atlandı

            except Exception as e:
                errors += 1
                if len(error_msgs) < 5:  # İlk 5 hatayı göster
                    error_msgs.append(f"{row.get('result_id', '?')}: {str(e)}")

        conn.commit()
        conn.close()

        # Yeni eklenen kayitlar icin ratio ve class_position hesapla
        if saved > 0:
            migrate_add_normalized_columns(db_path)

        # Sonuç mesajı
        msg = f"Veritabanina kaydedildi: {saved} yeni"
        if skipped > 0:
            msg += f", {skipped} zaten vardi (atlandi)"
        if errors > 0:
            msg += f", {errors} hata"

        if errors > 0:
            st.warning(msg)
            if error_msgs:
                st.code("\n".join(error_msgs))
        else:
            st.success(msg)

    except Exception as e:
        st.error(f"Veritabani kayit hatasi: {e}")
        import traceback
        st.code(traceback.format_exc())


def _render_db_upload():
    """Database yükleme bölümü."""
    st.subheader("Veritabani Dosyasi Yukle")
    context = st.session_state.get("workflow_context")
    if isinstance(context, dict) and context.get("action_target_page") == "Veri Cek" and context.get("stage_id"):
        st.caption(f"Ipucu: Bu merge akisi icin {context['stage_id']} sonucunu iceren DB'yi secin.")

    uploaded_db = st.file_uploader("rally_results.db dosyasi secin", type=['db'])

    if uploaded_db:
        # Kaydetme yolu seçimi
        st.markdown("**Kaydetme Yolu**")
        save_option = st.radio(
            "Nereye kaydedilsin?",
            ["Mevcut konum", "Yeni konum belirt"],
            horizontal=True,
            key="db_save_option"
        )

        if save_option == "Yeni konum belirt":
            new_path = st.text_input(
                "Tam dosya yolu girin (orn: C:/RallyData/rally_results.db)",
                value=str(get_db_path()),
                key="new_db_save_path"
            )
            target_path = Path(new_path) if new_path else Path(get_db_path())
        else:
            target_path = Path(get_db_path())

        st.info(f"Kaydedilecek: {target_path}")
        if target_path.exists():
            st.caption("Hedef DB mevcut. Yuklenen dosya overwrite edilmeyecek; merge/backups/conflict log akisi calisacak.")

        action_label = "Veritabanini Birlestir" if target_path.exists() else "Veritabanini Kaydet"
        if st.button(action_label, type="primary"):
            try:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
                    tmp.write(uploaded_db.getbuffer())
                    tmp_path = tmp.name

                if target_path.exists():
                    summary = merge_results_database(
                        master_db_path=str(target_path),
                        incoming_db_path=tmp_path,
                        backup_dir=str(PROJECT_ROOT / "backups"),
                        report_dir=str(PROJECT_ROOT / "reports"),
                    )
                    st.session_state.db_path = str(target_path)
                    st.success(
                        f"Merge tamamlandi: +{summary.inserted_rows} yeni, "
                        f"{summary.skipped_rows} duplicate atlandi, "
                        f"{summary.conflict_rows} conflict loglandi"
                    )
                    st.caption(f"Birlestirme logu: {summary.merge_log_path}")
                    resolution_result = _resolve_results_workflow_issue_after_merge()
                    if resolution_result:
                        if resolution_result.get("matched_count", 0) > 0:
                            st.success(resolution_result["message"])
                        else:
                            st.info(resolution_result["message"])
                else:
                    with open(target_path, 'wb') as f:
                        f.write(uploaded_db.getbuffer())
                    st.session_state.db_path = str(target_path)
                    st.success(f"Veritabani kaydedildi: {target_path}")

                Path(tmp_path).unlink(missing_ok=True)
                st.rerun()
            except Exception as e:
                st.error(f"Hata: {e}")

    st.markdown("---")
    st.subheader("Mevcut Veritabani")
    st.text(f"Konum: {get_db_path()}")

    db_info = get_database_info()
    if db_info['exists']:
        st.success(f"Sonuc: {db_info['result_count']:,} | Pilot: {db_info['driver_count']} | Ralli: {db_info['rally_count']}")

        # Database indirme butonu
        db_path = get_db_path()
        try:
            with open(db_path, 'rb') as f:
                db_data = f.read()
            st.download_button(
                "Veritabanini Indir (.db)",
                data=db_data,
                file_name="rally_results.db",
                mime="application/octet-stream",
                type="primary"
            )
        except Exception as e:
            st.error(f"Veritabani okunamadi: {e}")

        # Database içeriğini göster
        with st.expander("Veritabani Icerigini Gor"):
            try:
                conn = sqlite3.connect(get_db_path())
                df = pd.read_sql_query(
                    "SELECT rally_id, rally_name, COUNT(*) as sonuc_sayisi "
                    "FROM stage_results GROUP BY rally_id ORDER BY rally_id DESC LIMIT 20",
                    conn
                )
                conn.close()
                show_html_table(df)
            except Exception as e:
                st.error(f"Veri okunamadi: {e}")
    else:
        st.warning("Veritabani bulunamadi")

    st.markdown("---")
    _render_geometry_export_import()


def _render_geometry_export_import():
    """Geometrik veri export/import bölümü."""
    st.subheader("Geometrik Veri (stage_geometry) Disari / Icari Aktar")

    col_exp, col_imp = st.columns(2)

    with col_exp:
        if st.button("Geometrik Veriyi Disari Aktar"):
            try:
                conn = sqlite3.connect(get_db_path())
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM stage_geometry WHERE COALESCE(is_active, 1) = 1")
                count = cursor.fetchone()[0]
                conn.close()

                if count == 0:
                    st.warning("Export edilecek geometrik veri yok")
                else:
                    export_path = PROJECT_ROOT / "exports" / f"stage_geometry_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
                    export_path.parent.mkdir(parents=True, exist_ok=True)
                    export_master_geometry_db(get_db_path(), str(export_path))

                    with open(export_path, 'rb') as f:
                        st.download_button(
                            "Indir (.db)",
                            data=f.read(),
                            file_name=export_path.name,
                            mime="application/octet-stream"
                        )
                    st.success(f"{count} kayit export edildi")
            except Exception as e:
                st.error(f"Export hatasi: {e}")

    with col_imp:
        uploaded_meta = st.file_uploader("stage_geometry.db yukle", type=['db'], key="meta_upload")
        if uploaded_meta:
            if st.button("Geometrik Veriyi Import Et"):
                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.db') as tmp:
                        tmp.write(uploaded_meta.getbuffer())
                        tmp_path = tmp.name

                    summary = merge_geometry_database(
                        master_db_path=get_db_path(),
                        incoming_db_path=tmp_path,
                        backup_dir=str(PROJECT_ROOT / "backups"),
                        report_dir=str(PROJECT_ROOT / "reports"),
                    )
                    Path(tmp_path).unlink(missing_ok=True)

                    st.success(
                        "Import tamamlandi: "
                        f"eklenen {summary.inserted_rows}, "
                        f"metadata guncellenen {summary.metadata_updated_rows}, "
                        f"duplicate {summary.duplicate_rows}, "
                        f"atlanan {summary.skipped_rows}"
                    )
                    if summary.conflict_rows:
                        st.warning(f"Conflict: {summary.conflict_rows} | Etaplar: {', '.join(summary.conflict_stage_ids)}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Import hatasi: {e}")


def _parse_time(time_str: str) -> float:
    """Zaman string'ini saniyeye çevir.

    Ralli zaman formatları:
    - MM:SS.d veya MM:SS:d (4:02.1 veya 04:02:1) -> 4 dakika 2.1 saniye
    - HH:MM:SS.d (1:04:02.1) -> 1 saat 4 dakika 2.1 saniye (uzun etaplar)

    Ayırt etme kriteri: İlk değer 60'dan büyükse dakika, değilse saat olabilir.
    Ralli etapları genelde 2-30 dakika arası, 60 dakikayı nadiren geçer.
    """
    if not time_str or ':' not in time_str:
        return 0

    try:
        # Virgülü noktaya çevir
        time_str = time_str.replace(',', '.')
        parts = time_str.split(':')

        if len(parts) == 2:
            # MM:SS.d formatı
            minutes = float(parts[0])
            seconds = float(parts[1])
            return minutes * 60 + seconds

        elif len(parts) == 3:
            # İki olasılık: MM:SS:d veya HH:MM:SS
            first = float(parts[0])
            second = float(parts[1])
            third = float(parts[2])

            # Üçüncü değer 10'dan küçükse muhtemelen onda bir saniye (MM:SS:d)
            # Ralli zamanlarında SS:d formatında d tek haneli olur (0-9)
            if third < 10 and second < 60:
                # MM:SS:d formatı (örn: 04:02:1 = 4 dakika 2.1 saniye)
                minutes = first
                seconds = second + third / 10.0
                return minutes * 60 + seconds
            else:
                # HH:MM:SS formatı (örn: 1:04:02 = 1 saat 4 dakika 2 saniye)
                hours = first
                minutes = second
                seconds = third
                return hours * 3600 + minutes * 60 + seconds
    except:
        pass

    return 0
