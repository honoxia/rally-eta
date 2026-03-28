"""
Rally ETA v2.0 - KML Yonetimi Sayfasi
KML yukleme, eslestirme, analiz ve export/import.
"""

import streamlit as st
import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime
import io
import json
import tempfile
import sys
import re

# Shared modülleri import et
sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.config import get_db_path, get_kml_folder, PROJECT_ROOT
from shared.data_loaders import get_kml_files, get_rally_list, get_stages_for_rally, get_stage_metadata_df
from shared.ui_components import render_page_header, show_html_table

_src_path = str(PROJECT_ROOT)
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)

from src.data.geometry_merge import export_master_geometry_db, merge_geometry_database, merge_geometry_rows


def render():
    """KML yonetimi sayfasini render et."""
    render_page_header(
        "Geometrik Veriler",
        "KML yukleme, etap eslestirme, manuel analiz ve geometri verisini kalici hale getirme akislarini buradan yonetin.",
        badge="Geometri Calisma Alani",
        eyebrow="Etap Zekasi",
    )

    section_options = ["Yukle", "Manuel Analiz", "Geometrik Veri"]
    section_override = st.session_state.pop("kml_manager_section_override", None)
    if section_override in section_options:
        st.session_state["kml_manager_section"] = section_override

    section = st.radio(
        "KML Bolumu",
        section_options,
        horizontal=True,
        key="kml_manager_section",
        label_visibility="collapsed",
    )

    _render_workflow_context_banner()

    if section == "Yukle":
        _render_upload_tab()
    elif section == "Manuel Analiz":
        _render_match_tab()
    elif section == "Geometrik Veri":
        _render_analysis_tab()


def _get_workflow_context():
    context = st.session_state.get("workflow_context")
    if not isinstance(context, dict):
        return None
    if context.get("action_target_page") != "KML Yonetimi":
        return None
    return context


def _render_workflow_context_banner():
    context = _get_workflow_context()
    if not context:
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
    if st.button("Aksiyon Baglamini Temizle", key="kml_workflow_context_dismiss"):
        st.session_state.pop("workflow_context", None)
        st.rerun()


def _resolve_geometry_workflow_issue(stage_id, merge_summary):
    context = _get_workflow_context()
    if not context:
        return None
    if str(context.get("stage_id") or "") != str(stage_id):
        return None
    if not context.get("prediction_id") or not context.get("issue_type"):
        return None
    if getattr(merge_summary, "conflict_rows", 0):
        return None
    if getattr(merge_summary, "inserted_rows", 0) + getattr(merge_summary, "metadata_updated_rows", 0) <= 0:
        return None

    from src.prediction.prediction_service import PredictionService

    service = PredictionService(db_path=get_db_path(), model_path=None)
    resolution = service.mark_prediction_issue_resolved(
        prediction_id=int(context["prediction_id"]),
        issue_types=[str(context["issue_type"])],
        resolution_source="kml_manual_analysis",
        resolution_note=f"stage_geometry guncellendi: {stage_id}",
    )
    st.session_state.pop("workflow_context", None)
    return resolution


def _render_upload_tab():
    """KML yükleme sekmesi."""
    st.subheader("KML/KMZ Yukle")

    uploaded_files = st.file_uploader(
        "KML/KMZ dosyalari secin",
        type=['kml', 'kmz'],
        accept_multiple_files=True
    )

    if uploaded_files:
        if st.button("Kaydet", type="primary"):
            kml_folder = Path(get_kml_folder())
            kml_folder.mkdir(parents=True, exist_ok=True)

            saved = 0
            for f in uploaded_files:
                try:
                    with open(kml_folder / f.name, 'wb') as out:
                        out.write(f.getbuffer())
                    saved += 1
                except:
                    pass

            st.success(f"{saved} dosya kaydedildi")

    st.markdown("---")
    st.subheader("Mevcut KML Dosyalari")

    kml_files = get_kml_files()
    if kml_files:
        df = pd.DataFrame(kml_files)
        show_html_table(df)
    else:
        st.info("KML dosyasi yok")


def _render_match_tab():
    """Tek etap manuel analiz sekmesi."""
    st.subheader("Tek Etap Manuel Analiz")

    kml_files = get_kml_files()
    rallies = get_rally_list()
    context = _get_workflow_context()

    if not kml_files:
        st.warning("Once KML yukleyin")
        return

    # KML seçimi
    kml_options = {f['name']: f for f in kml_files}
    selected_kml = st.selectbox("KML Dosyasi", list(kml_options.keys()), key="kml_manager_selected_kml")

    # Rally seçimi (opsiyonel - ralliler varsa göster)
    if rallies:
        rally_options = {f"{r['rally_name']} ({r['rally_id']})": r for r in rallies}
        rally_key = "kml_manager_selected_rally"
        rally_override = st.session_state.pop("kml_manager_rally_override", None) or (context or {}).get("rally_id")
        if rally_override is not None:
            for label, rally in rally_options.items():
                if str(rally.get("rally_id")) == str(rally_override):
                    st.session_state[rally_key] = label
                    break
        selected_rally = st.selectbox("Ralli (opsiyonel)", list(rally_options.keys()), key=rally_key)
    else:
        rally_options = {"Manuel Giris": {'rally_id': '', 'rally_name': ''}}
        selected_rally = "Manuel Giris"
        st.info("Veritabaninda ralli yok - Rally ID manuel girilecek")

    # Tek etap manuel analiz
    _render_single_stage_analysis(kml_options, rally_options, selected_kml, selected_rally)


def _render_manual_matching(kml_path: str, rally_id: str) -> dict:
    """Manuel eşleştirme UI'ı."""
    try:
        src_path = str(PROJECT_ROOT)
        if src_path not in sys.path:
            sys.path.insert(0, src_path)

        from src.stage_analyzer.kml_parser import parse_kml_file

        kml_stages = parse_kml_file(kml_path)
        if not kml_stages:
            st.warning("KML icinde etap bulunamadi")
            return None

        db_stages = get_stages_for_rally(rally_id)
        if db_stages.empty:
            st.warning("Secilen rally icin etap bulunamadi")
            return None

        stage_mappings = {}
        st.markdown("**Etap eslestirme**")

        for idx, stage in enumerate(kml_stages):
            label = f"{idx+1}. {stage.name}"
            options = ["-- Eslesme Yok --"] + [
                f"SS{int(row['stage_number']) if pd.notna(row['stage_number']) else '?'} - "
                f"{row['stage_name']} ({row['stage_id']})"
                for _, row in db_stages.iterrows()
            ]
            choice = st.selectbox(label, options, key=f"kml_map_{idx}")
            if choice != "-- Eslesme Yok --":
                stage_id = choice.split("(")[-1].replace(")", "").strip()
                stage_mappings[idx] = stage_id

        return stage_mappings

    except Exception as e:
        st.error(f"Manuel eslestirme yukleme hatasi: {e}")
        return None


def _process_kml_matching(kml_path: str, rally_id: str, stage_mappings: dict = None):
    """KML eşleştirme işlemini çalıştır."""
    try:
        src_path = str(PROJECT_ROOT)
        if src_path not in sys.path:
            sys.path.insert(0, src_path)

        from src.data.batch_kml_processor import BatchKMLProcessor

        processor = BatchKMLProcessor(get_db_path())
        result = processor.process_single_kml(
            kml_path=kml_path,
            rally_id=rally_id,
            stage_mappings=stage_mappings
        )

        if result.success:
            st.success(f"Basarili! {result.stages_processed} etap islendi")
        else:
            st.error(f"Hata: {result.error_message}")
    except Exception as e:
        st.error(f"Hata: {e}")


def _render_single_stage_analysis(kml_options, rally_options, selected_kml, selected_rally):
    """Tek etap manuel analiz bölümü."""
    try:
        from src.stage_analyzer.kml_parser import parse_kml_file

        kml_path = kml_options[selected_kml]['path']
        kml_stages = parse_kml_file(kml_path)
        rally_info = rally_options[selected_rally]
        rally_id = rally_info['rally_id']

        if not kml_stages:
            st.warning("KML icinde etap bulunamadi")
            return

        stage_labels = [f"{i+1}. {s.name}" for i, s in enumerate(kml_stages)]
        selected_idx = st.selectbox(
            "KML Etap Sec",
            range(len(kml_stages)),
            format_func=lambda i: stage_labels[i],
            key="kml_manager_selected_kml_stage",
        )
        selected_stage = kml_stages[selected_idx]

        official_stages = get_stages_for_rally(rally_id) if rally_id else pd.DataFrame()
        col_a, col_b = st.columns(2)
        if not official_stages.empty:
            stage_options = {
                f"SS{int(row['stage_number'])} - {row['stage_name']}": row
                for _, row in official_stages.iterrows()
            }
            stage_key = "kml_manager_selected_official_stage"
            stage_override = st.session_state.pop("kml_manager_stage_override", None)
            if stage_override:
                for label, row in stage_options.items():
                    stage_number_match = re.search(r"_ss(\d+)$", str(stage_override))
                    if str(row.get("stage_id")) == str(stage_override):
                        st.session_state[stage_key] = label
                        break
                    if stage_number_match and int(row.get("stage_number")) == int(stage_number_match.group(1)):
                        st.session_state[stage_key] = label
                        break
            selected_catalog_stage = st.selectbox("Resmi Etap", list(stage_options.keys()), key=stage_key)
            selected_catalog_row = stage_options[selected_catalog_stage]
            stage_id_value = str(selected_catalog_row['stage_id'])
            surface_value = selected_catalog_row.get('surface') or "bilinmiyor"
            with col_a:
                st.text_input("stage_id", value=stage_id_value, disabled=True)
            with col_b:
                st.text_input("Yuzey", value=surface_value, disabled=True)
        else:
            stage_id_value = st.session_state.pop("kml_manager_stage_override", None) or (f"{rally_id}_ss{selected_idx+1}" if rally_id else "")
            surface_value = "bilinmiyor"
            with col_a:
                stage_id_value = st.text_input("stage_id", value=stage_id_value)
            with col_b:
                st.text_input("Yuzey", value=surface_value, disabled=True)

        # Analiz parametreleri
        col_cfg1, col_cfg2 = st.columns(2)
        with col_cfg1:
            geom_step = st.number_input(
                "Geometri Ornekleme (m)",
                min_value=5.0, max_value=50.0, value=10.0, step=5.0,
                key="manual_geom"
            )
            elev_step = st.number_input(
                "Yukselti Ornekleme (m)",
                min_value=50.0, max_value=500.0, value=200.0, step=50.0,
                key="manual_elev"
            )
        with col_cfg2:
            smoothing_window = st.number_input(
                "Smoothing Pencere",
                min_value=3, max_value=15, value=7, step=2,
                key="manual_smooth"
            )
            hairpin_threshold = st.number_input(
                "Hairpin Esik (m)",
                min_value=10.0, max_value=50.0, value=20.0, step=1.0,
                key="manual_hairpin"
            )

        # Analiz butonu
        if st.button("Tek Etap Analiz Et ve Kaydet", type="primary"):
            if not stage_id_value:
                st.error("stage_id zorunlu")
                return

            _analyze_single_stage(
                selected_stage,
                stage_id_value,
                rally_id,
                kml_path,
                surface_value if surface_value != "bilinmiyor" else None,
                geom_step,
                elev_step,
                smoothing_window,
                hairpin_threshold
            )

    except Exception as e:
        st.error(f"Tek etap analiz yukleme hatasi: {e}")


def _analyze_single_stage(stage, stage_id, rally_id, kml_path, surface,
                          geom_step, elev_step, smoothing_window, hairpin_threshold):
    """Tek etap analizi çalıştır."""
    try:
        from src.stage_analyzer.kml_analyzer import KMLAnalyzer

        # Geçici KML oluştur
        temp_kml = Path(f"temp_stage_{stage_id}.kml")
        kml_content = '<?xml version="1.0" encoding="UTF-8"?>\n'
        kml_content += '<kml xmlns="http://www.opengis.net/kml/2.2">\n'
        kml_content += '<Document>\n'
        kml_content += f'<Placemark><name>{stage.name}</name>\n'
        kml_content += '<LineString><coordinates>\n'
        for lat, lon in stage.coordinates:
            kml_content += f'{lon},{lat},0 '
        kml_content += '\n</coordinates></LineString></Placemark>\n'
        kml_content += '</Document>\n</kml>'

        with open(temp_kml, 'w', encoding='utf-8') as f:
            f.write(kml_content)

        # Analiz
        analyzer = KMLAnalyzer(
            geom_step=float(geom_step),
            smoothing_window=int(smoothing_window),
            elev_step=float(elev_step)
        )
        results = analyzer.analyze_kml(str(temp_kml), hairpin_threshold=float(hairpin_threshold))
        temp_kml.unlink()

        # Kaydet
        summary = _save_stage_metadata(stage_id, rally_id, stage.name, kml_path, results, surface)
        resolution = _resolve_geometry_workflow_issue(stage_id, summary)
        if summary.conflict_rows:
            st.warning(f"Conflict: {', '.join(summary.conflict_stage_ids)}")
        if resolution:
            st.success("Ilgili prediction issue kaydi cozuldu olarak isaretlendi.")
        st.success(f"Kaydedildi: {stage_id}")

    except Exception as e:
        st.error(f"Analiz hatasi: {e}")


def _save_stage_metadata(stage_id, rally_id, stage_name, kml_file, results, surface=None):
    """Stage metadata kaydını veritabanına yaz."""
    analyzed_at = datetime.now().isoformat()
    payload = {
        'stage_id': stage_id,
        'rally_id': str(rally_id),
        'stage_name': stage_name,
        'kml_file': kml_file,
        'source_kml': kml_file,
        'surface': surface,
        'distance_km': results.get('distance_km', 0),
        'curvature_sum': results.get('curvature_sum', 0),
        'curvature_density': results.get('curvature_density', 0),
        'p95_curvature': results.get('p95_curvature', 0),
        'max_curvature': results.get('max_curvature', 0),
        'avg_curvature': results.get('avg_curvature', 0),
        'hairpin_count': results.get('hairpin_count', 0),
        'hairpin_density': results.get('hairpin_density', 0),
        'straight_ratio': results.get('straight_ratio', 0),
        'sign_changes_per_km': results.get('sign_changes_per_km', 0),
        'total_ascent': results.get('total_ascent', 0),
        'total_descent': results.get('total_descent', 0),
        'max_grade': results.get('max_grade', 0),
        'avg_abs_grade': results.get('avg_abs_grade', 0),
        'geometry_points': results.get('geometry_samples', 0),
        'elevation_api_calls': results.get('elevation_samples', 0),
        'cache_hit_rate': 0,
        'straight_percentage': results.get('straight_ratio', 0) * 100,
        'curvy_percentage': max(0.0, 100.0 - (results.get('straight_ratio', 0) * 100)),
        'analyzer_version': 'kml_analyzer_v2',
        'analysis_version': 'kml_analyzer_v2',
        'processed_at': analyzed_at,
        'analyzed_at': analyzed_at,
        'geometry_json': json.dumps(results, ensure_ascii=False),
    }

    return merge_geometry_rows(
        master_db_path=get_db_path(),
        incoming_rows=[payload],
        source_label=str(kml_file),
        backup_dir=str(PROJECT_ROOT / "backups"),
        report_dir=str(PROJECT_ROOT / "reports"),
    )


def _render_analysis_tab():
    """Analiz sekmesi."""
    st.subheader("Geometrik Veri Durumu")

    try:
        src_path = str(PROJECT_ROOT)
        if src_path not in sys.path:
            sys.path.insert(0, src_path)

        from src.data.batch_kml_processor import BatchKMLProcessor

        processor = BatchKMLProcessor(get_db_path())
        stats = processor.get_geometry_stats()

        col1, col2, col3 = st.columns(3)
        col1.metric("Geometrik Veri", stats['stages_with_geometry'])
        col2.metric("Toplam Etap", stats['total_stages'])
        col3.metric("Kapsam", f"{stats['coverage_percent']:.1f}%")

        stages = processor.get_stages_with_geometry()
        if stages:
            df = pd.DataFrame(stages)
            show_html_table(df)
    except Exception as e:
        st.error(f"Veri yuklenemedi: {e}")

    st.markdown("---")
    _render_database_export_import()

    st.markdown("---")
    _render_excel_export_import()


def _render_excel_export_import():
    """Excel export/import bölümü."""
    st.subheader("Excel Disari / Icari Aktar")

    rallies = get_rally_list()
    rally_filter = None

    if rallies:
        rally_options = ["Tum Ralliler"] + [f"{r['rally_name']} ({r['rally_id']})" for r in rallies]
        selected_rally = st.selectbox("Rally Filtre", rally_options)
        if selected_rally != "Tum Ralliler":
            rally_filter = selected_rally.split("(")[-1].replace(")", "").strip()

    # Export
    if st.button("Excel'e Aktar", type="primary"):
        try:
            export_df = get_stage_metadata_df(rally_filter)
            if export_df.empty:
                st.warning("Disari aktarilacak veri yok")
            else:
                exports_dir = PROJECT_ROOT / "exports"
                exports_dir.mkdir(parents=True, exist_ok=True)
                filename = f"stage_metadata_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
                file_path = exports_dir / filename

                output = io.BytesIO()
                with pd.ExcelWriter(output, engine="openpyxl") as writer:
                    export_df.to_excel(writer, index=False, sheet_name="stages")
                output.seek(0)

                with open(file_path, "wb") as f:
                    f.write(output.getbuffer())

                st.success(f"Excel hazir: {file_path}")
                st.download_button(
                    "Excel'i Indir",
                    data=output,
                    file_name=filename,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
        except ImportError:
            st.error("Excel export icin openpyxl gerekiyor.")
        except Exception as e:
            st.error(f"Excel export hatasi: {e}")

    # Import
    uploaded_excel = st.file_uploader("Excel'den Icari Aktar (.xlsx)", type=['xlsx'])
    if uploaded_excel and st.button("Excel'den Icari Aktar"):
        try:
            df = pd.read_excel(uploaded_excel)
            summary, err = _update_metadata_from_df(df)
            if err:
                st.error(err)
            else:
                st.success(f"Guncellendi: {summary['updated']} | Atlandi: {summary['skipped']}")
                if summary['conflicts']:
                    st.warning(f"Conflict: {summary['conflicts']} | Etaplar: {', '.join(summary['conflict_stage_ids'])}")
        except ImportError:
            st.error("Excel import icin openpyxl gerekiyor.")
        except Exception as e:
            st.error(f"Excel import hatasi: {e}")


def _update_metadata_from_df(df: pd.DataFrame) -> tuple:
    """Excel'den metadata güncelle."""
    if df is None or df.empty:
        return None, "Excel bos"

    if 'stage_id' not in df.columns:
        return None, "stage_id kolonunu bulamadim"

    incoming_rows = []
    skipped = 0

    for _, row in df.iterrows():
        stage_id = row.get('stage_id')
        if pd.isna(stage_id):
            skipped += 1
            continue
        stage_id = str(stage_id).strip()
        if not stage_id:
            skipped += 1
            continue

        payload = {'stage_id': stage_id}
        for col in df.columns:
            if col == 'stage_id':
                continue
            value = row.get(col)
            if pd.isna(value):
                continue
            payload[col] = value
        incoming_rows.append(payload)

    if not incoming_rows:
        return None, "Guncellenecek kolon yok"

    merge_summary = merge_geometry_rows(
        master_db_path=get_db_path(),
        incoming_rows=incoming_rows,
        source_label="kml_manager_excel_import",
        backup_dir=str(PROJECT_ROOT / "backups"),
        report_dir=str(PROJECT_ROOT / "reports"),
    )

    return {
        "updated": merge_summary.inserted_rows + merge_summary.metadata_updated_rows + merge_summary.duplicate_rows,
        "skipped": skipped + merge_summary.skipped_rows,
        "conflicts": merge_summary.conflict_rows,
        "conflict_stage_ids": merge_summary.conflict_stage_ids,
    }, None


def _render_database_export_import():
    """Canonical stage_geometry verisini ayrı SQLite dosyası olarak export/import."""
    st.subheader("Geometrik Veri Veritabani Disari / Icari Aktar")
    st.caption("KML analizlerini ayri bir .db dosyasi olarak kaydedin veya yukleyin")

    col_exp, col_imp = st.columns(2)

    with col_exp:
        st.markdown("**Dışarı Aktar**")
        if st.button("Geometrik Veriyi İndir (.db)", type="primary", key="export_geo_db"):
            try:
                conn = sqlite3.connect(get_db_path())
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM stage_geometry WHERE COALESCE(is_active, 1) = 1")
                count = cursor.fetchone()[0]
                conn.close()

                if count == 0:
                    st.warning("Export edilecek geometrik veri yok")
                else:
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.db') as tmp:
                        tmp_path = tmp.name

                    export_master_geometry_db(get_db_path(), tmp_path)

                    with open(tmp_path, 'rb') as f:
                        db_data = f.read()

                    Path(tmp_path).unlink()

                    filename = f"stage_geometry_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
                    st.download_button(
                        f"İndir ({count} kayıt)",
                        data=db_data,
                        file_name=filename,
                        mime="application/octet-stream"
                    )
                    st.success(f"{count} geometrik veri kaydı hazır")
            except Exception as e:
                st.error(f"Export hatası: {e}")

    with col_imp:
        st.markdown("**İçeri Aktar**")
        uploaded_db = st.file_uploader("stage_geometry.db yükle", type=['db'], key="geo_db_upload")

        if uploaded_db:
            merge_mode = st.radio(
                "Yükleme modu",
                ["Birleştir (mevcut + yeni)", "Değiştir (sadece yeni)"],
                key="geo_import_mode"
            )

            if st.button("Geometrik Veriyi Yükle", key="import_geo_db"):
                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.db') as tmp:
                        tmp.write(uploaded_db.getbuffer())
                        tmp_path = tmp.name

                    summary = merge_geometry_database(
                        master_db_path=get_db_path(),
                        incoming_db_path=tmp_path,
                        backup_dir=str(PROJECT_ROOT / "backups"),
                        report_dir=str(PROJECT_ROOT / "reports"),
                        replace_existing="Değiştir" in merge_mode,
                    )
                    Path(tmp_path).unlink(missing_ok=True)

                    st.success(
                        "Yüklendi: "
                        f"eklenen {summary.inserted_rows}, "
                        f"metadata guncellenen {summary.metadata_updated_rows}, "
                        f"duplicate {summary.duplicate_rows}, "
                        f"atlanan {summary.skipped_rows}"
                    )
                    if summary.conflict_rows:
                        st.warning(f"Conflict: {summary.conflict_rows} | Etaplar: {', '.join(summary.conflict_stage_ids)}")
                    st.rerun()

                except Exception as e:
                    st.error(f"Import hatası: {e}")
