"""Race-day single-screen operational decision workflow."""

from __future__ import annotations

import re

import pandas as pd
import streamlit as st

from shared.config import SURFACE_TYPES, get_db_path
from shared.services import get_prediction_service
from shared.ui_components import (
    format_confidence_label,
    format_surface_label,
    render_page_header,
    show_html_table,
)
from src.prediction.manual_calculator import (
    build_manual_payload_from_rally,
    calculate_manual_stage_estimate,
    format_manual_time,
)
from src.prediction.operation_decision import save_operation_decision
from src.scraper.tosfed_sonuc_scraper import ResultsNotPublishedError


MAX_REFERENCE_STAGES = 6


def render():
    view = st.radio('Görünüm', ['Canlı Yarış', 'Tek Pilot / Karar'], horizontal=True, key='operation_view')
    if view == 'Canlı Yarış':
        from pages import live_rally

        live_rally.render()
    else:
        render_decision()


def render_decision():
    """Render URL-to-decision race-day workflow."""
    render_page_header(
        "Operasyon Modu",
        "Yarış verisini çekin, hedef etap ve pilotu seçin, yöntemleri karşılaştırıp resmi kararı kaydedin.",
        badge="Yarış Günü",
        eyebrow="Komiser Karar Akışı",
    )

    rally_data = st.session_state.get("operation_rally_data")
    calculation = st.session_state.get("operation_calculation")
    _render_steps(bool(rally_data), bool(rally_data), bool(calculation), False)

    st.markdown("### 1. Yarış Verisi")
    source_url = st.text_input(
        "TOSFED Sonuç URL'si",
        placeholder="https://sonuc.tosfed.org.tr/yaris/171/ralli_etap_sonuclari/?etp=7",
        key="operation_url",
    )
    if st.button("Yarış Verisini Çek", type="primary", key="operation_fetch", use_container_width=True):
        _fetch_rally(source_url)
        rally_data = st.session_state.get("operation_rally_data")
        calculation = None

    if not rally_data:
        st.info("Başlamak için yarış sonuç URL'sini girin.")
        return

    loaded_url = st.session_state.get("operation_loaded_url", "")
    if source_url and loaded_url and source_url != loaded_url:
        st.warning("URL alanı değişti. Yeni URL'yi kullanmak için yarış verisini tekrar çekin.")

    stages = sorted(
        rally_data.get("stages") or [],
        key=lambda stage: int(stage.get("stage_number") or 0),
    )
    drivers = sorted(
        {
            str(result.get("driver_name") or "").strip()
            for stage in stages
            for result in stage.get("results") or []
            if str(result.get("driver_name") or "").strip()
        }
    )
    if not stages or not drivers:
        st.error("Yarış verisinde kullanılabilir etap veya pilot bulunamadı.")
        return

    summary_cols = st.columns(4)
    summary_cols[0].metric("Yarış", rally_data.get("rally_name") or rally_data.get("rally_id"))
    summary_cols[1].metric("Etap", len(stages))
    summary_cols[2].metric("Pilot", len(drivers))
    summary_cols[3].metric("Zemin", format_surface_label(rally_data.get("surface") or "gravel"))

    st.markdown("### 2. Hedef ve Pilot")
    stage_numbers = [int(stage.get("stage_number") or 0) for stage in stages]
    suggested = int(rally_data.get("suggested_stage") or stage_numbers[-1])
    suggested_index = stage_numbers.index(suggested) if suggested in stage_numbers else len(stage_numbers) - 1
    selector_cols = st.columns(3)
    target_stage_number = selector_cols[0].selectbox(
        "Hedef Etap",
        stage_numbers,
        index=suggested_index,
        format_func=lambda number: _stage_label(_find_stage(stages, number)),
        key="operation_target_stage",
    )
    driver_name = selector_cols[1].selectbox(
        "Hesaplanacak Pilot",
        drivers,
        key="operation_driver",
    )
    default_surface = rally_data.get("surface") or "gravel"
    surface_index = SURFACE_TYPES.index(default_surface) if default_surface in SURFACE_TYPES else 0
    surface = selector_cols[2].selectbox(
        "Zemin",
        SURFACE_TYPES,
        index=surface_index,
        format_func=format_surface_label,
        key="operation_surface",
    )

    target_stage = _find_stage(stages, target_stage_number)
    raw_class = _find_driver_class(stages, driver_name, target_stage_number)
    context_cols = st.columns(3)
    context_cols[0].metric("Ham Sınıf", raw_class or "Bulunamadı")
    context_cols[1].metric("Hedef Mesafe", f"{float(target_stage.get('stage_length_km') or 0):.2f} km")
    context_cols[2].metric("Hedefte Sonuç", len(target_stage.get("results") or []))

    current_signature = (
        str(rally_data.get("rally_id")),
        loaded_url,
        int(target_stage_number),
        driver_name,
        surface,
    )
    if st.button(
        "Yöntemleri Hesapla",
        type="primary",
        key="operation_calculate",
        use_container_width=True,
    ):
        _calculate_methods(
            rally_data=rally_data,
            source_url=loaded_url,
            driver_name=driver_name,
            raw_class=raw_class,
            target_stage_number=target_stage_number,
            surface=surface,
            signature=current_signature,
        )
        calculation = st.session_state.get("operation_calculation")

    calculation = st.session_state.get("operation_calculation")
    if not calculation:
        st.info("Km bazlı, yüzde bazlı ve model/baz tahmin sonuçları için hesaplamayı başlatın.")
        return
    if calculation.get("signature") != current_signature:
        st.warning("Hedef etap, pilot veya zemin değişti. Sonuçları yeniden hesaplayın.")
        return

    st.markdown("### 3. Yöntem Karşılaştırması")
    methods = _render_method_results(calculation)
    if not methods:
        return

    st.markdown("### 4. Komiser Kararı")
    selected_method = st.radio(
        "Resmi karar için kullanılacak yöntem",
        list(methods),
        horizontal=True,
        key="operation_selected_method",
    )
    selected = methods[selected_method]
    decision_cols = st.columns([1, 2])
    decision_cols[0].metric("Seçilen Süre", selected["time_str"])
    rationale = decision_cols[1].text_area(
        "Karar Gerekçesi",
        placeholder="Referans etapların benzerliği, veri kalitesi ve seçilen yöntemin nedeni...",
        key="operation_rationale",
        height=96,
    )

    if st.button("Kararı Kaydet", type="primary", key="operation_save", use_container_width=True):
        try:
            decision_id = save_operation_decision(
                get_db_path(),
                {
                    "rally_id": str(rally_data.get("rally_id")),
                    "rally_name": rally_data.get("rally_name"),
                    "stage_id": f"{rally_data.get('rally_id')}_ss{target_stage_number}",
                    "stage_number": target_stage_number,
                    "stage_name": target_stage.get("stage_name"),
                    "driver_name": driver_name,
                    "raw_class": calculation.get("raw_class"),
                    "selected_method": selected_method,
                    "selected_time_seconds": selected["seconds"],
                    "selected_time_str": selected["time_str"],
                    "km_based_seconds": calculation.get("km_based_seconds"),
                    "percentage_seconds": calculation.get("percentage_seconds"),
                    "ml_seconds": calculation.get("ml_seconds"),
                    "reference_stage_count": calculation.get("reference_stage_count"),
                    "rationale": rationale,
                    "source_url": calculation.get("source_url"),
                },
            )
            st.session_state["operation_last_decision_id"] = decision_id
            st.success(f"Karar kaydedildi. Kayıt numarası: {decision_id}")
            _render_steps(True, True, True, True)
        except (ValueError, OSError) as exc:
            st.error(str(exc))


def _fetch_rally(url: str) -> None:
    if not re.search(r"/yaris/\d+", url or ""):
        st.error("Geçerli bir TOSFED yarış sonuç URL'si girin.")
        return

    with st.spinner("Yarış ve etap sonuçları çekiliyor..."):
        try:
            from src.scraper.tosfed_sonuc_scraper import TOSFEDSonucScraper

            rally_data = TOSFEDSonucScraper().fetch_rally_from_url(url)
            if not rally_data:
                st.error("Yarış verisi alınamadı. URL'yi ve internet bağlantısını kontrol edin.")
                return
            st.session_state["operation_rally_data"] = rally_data
            st.session_state["operation_loaded_url"] = url
            st.session_state.pop("operation_calculation", None)
            st.success(f"{rally_data.get('rally_name', 'Yarış')} başarıyla yüklendi.")
        except ResultsNotPublishedError as exc:
            st.info(str(exc))
        except Exception as exc:
            st.error(f"Yarış verisi çekilemedi: {exc}")


def _calculate_methods(
    rally_data,
    source_url,
    driver_name,
    raw_class,
    target_stage_number,
    surface,
    signature,
) -> None:
    calculation = {
        "signature": signature,
        "source_url": source_url or st.session_state.get("operation_loaded_url", ""),
        "raw_class": raw_class,
        "errors": [],
    }

    try:
        manual_payload = build_manual_payload_from_rally(
            rally_data,
            driver_name,
            target_stage_number,
            max_reference_stages=MAX_REFERENCE_STAGES,
        )
        manual_result = calculate_manual_stage_estimate(
            reference_rows=manual_payload["references"],
            target_row=manual_payload["target"],
            class_name=manual_payload["class_name"],
        )
        calculation.update(
            {
                "manual_payload": manual_payload,
                "manual_result": manual_result,
                "km_based_seconds": manual_result.km_based_prediction_seconds,
                "percentage_seconds": manual_result.percentage_prediction_seconds,
                "reference_stage_count": manual_result.used_stage_count,
                "raw_class": manual_payload["class_name"],
            }
        )
    except ValueError as exc:
        calculation["errors"].append(f"Manuel yöntemler: {exc}")

    try:
        if not raw_class:
            raise ValueError("Pilotun ham sınıfı bulunamadı.")
        ml_result = get_prediction_service().compare_previous_and_predict_next(
            rally_data=rally_data,
            driver_name=driver_name,
            driver_class=raw_class,
            predict_stage_num=target_stage_number,
            surface=surface,
            geo_features=None,
        )
        calculation["ml_result"] = ml_result
        calculation["ml_seconds"] = (
            float(ml_result["predicted_time_seconds"])
            if ml_result.get("geometric_mode") == "geometric"
            else None
        )
    except Exception as exc:
        calculation["errors"].append(f"Model/baz tahmin: {exc}")

    if not calculation.get("manual_result") and not calculation.get("ml_result"):
        st.error("Hiçbir yöntem sonuç üretemedi.")
        for error in calculation["errors"]:
            st.caption(error)
        return

    st.session_state["operation_calculation"] = calculation
    st.success("Kullanılabilir yöntemler hesaplandı.")


def _render_method_results(calculation) -> dict:
    methods = {}
    cards = st.columns(3)
    manual_result = calculation.get("manual_result")
    if manual_result:
        methods["Km Bazlı"] = {
            "seconds": manual_result.km_based_prediction_seconds,
            "time_str": format_manual_time(manual_result.km_based_prediction_seconds),
        }
        methods["Yüzde Bazlı"] = {
            "seconds": manual_result.percentage_prediction_seconds,
            "time_str": format_manual_time(manual_result.percentage_prediction_seconds),
        }
        cards[0].metric("Km Bazlı", methods["Km Bazlı"]["time_str"])
        cards[0].caption(f"{manual_result.used_stage_count} referans, {manual_result.average_diff_per_km:.3f} sn/km")
        cards[1].metric("Yüzde Bazlı", methods["Yüzde Bazlı"]["time_str"])
        cards[1].caption(f"Ortalama oran {manual_result.average_ratio:.4f}")
    else:
        cards[0].metric("Km Bazlı", "Kullanılamadı")
        cards[1].metric("Yüzde Bazlı", "Kullanılamadı")

    ml_result = calculation.get("ml_result")
    if ml_result:
        uses_ml = ml_result.get("geometric_mode") == "geometric"
        method_label = "ML Tahmini" if uses_ml else "Baz Tahmin"
        methods[method_label] = {
            "seconds": float(ml_result["predicted_time_seconds"]),
            "time_str": ml_result["predicted_time_str"],
        }
        cards[2].metric(method_label, ml_result["predicted_time_str"])
        cards[2].caption(
            f"Güven {format_confidence_label(ml_result.get('confidence_level', 'MEDIUM'))} · "
            f"oran {float(ml_result.get('predicted_ratio') or 0):.3f}"
        )
        if not uses_ml:
            st.warning(
                "ML modeli kullanılmadı. Baz Tahmin, pilot geçmişi, yarış içi performans "
                "ve zemin verisine dayanır; karar kaydına bu adla yazılır."
            )
    else:
        cards[2].metric("Model/Baz Tahmin", "Kullanılamadı")

    for error in calculation.get("errors") or []:
        st.warning(error)

    if manual_result:
        for warning in manual_result.warnings:
            st.warning(warning)

    payload = calculation.get("manual_payload")
    if payload:
        with st.expander("Kullanılan Referans Etaplar", expanded=False):
            used_labels = (
                {item.label for item in manual_result.reference_details} if manual_result else None
            )
            show_html_table(
                pd.DataFrame(
                    [
                        {
                            "Etap": row["label"],
                            "Km": row["km"],
                            "Sınıf Best": row["best_time"],
                            "Pilot Süresi": row["driver_time"],
                            "Durum": "Kullanıldı"
                            if used_labels is None or row["label"] in used_labels
                            else "Elendi",
                        }
                        for row in payload["references"]
                    ]
                )
            )
            if manual_result and manual_result.ignored_references:
                st.caption("Hesaba katılmayanlar: " + " | ".join(manual_result.ignored_references))
            if payload.get("skipped_stages"):
                st.caption("Eksik veri nedeniyle atlananlar: " + ", ".join(payload["skipped_stages"]))

    return methods


def _render_steps(data_ready: bool, selection_ready: bool, calculated: bool, saved: bool) -> None:
    states = [
        ("1", "Veri", data_ready),
        ("2", "Hedef", selection_ready),
        ("3", "Hesap", calculated),
        ("4", "Karar", saved),
    ]
    columns = st.columns(4)
    for column, (number, label, complete) in zip(columns, states):
        color = "#16A34A" if complete else "#64748B"
        status = "Tamamlandı" if complete else "Bekliyor"
        column.markdown(
            f"""
            <div style="border:1px solid #CBD5E1;border-left:4px solid {color};padding:.65rem .8rem;border-radius:.45rem;background:#F8FAFC;">
                <div style="font-size:.72rem;color:#64748B;">ADIM {number}</div>
                <div style="font-weight:700;color:#334155;">{label}</div>
                <div style="font-size:.72rem;color:{color};">{status}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _find_stage(stages, stage_number):
    return next(
        stage for stage in stages if int(stage.get("stage_number") or 0) == int(stage_number)
    )


def _stage_label(stage) -> str:
    number = int(stage.get("stage_number") or 0)
    name = str(stage.get("stage_name") or "").strip()
    return f"SS{number}: {name}" if name else f"SS{number}"


def _find_driver_class(stages, driver_name, target_stage_number) -> str:
    eligible = [
        stage for stage in stages if int(stage.get("stage_number") or 0) <= int(target_stage_number)
    ]
    for stage in reversed(eligible):
        for result in stage.get("results") or []:
            if str(result.get("driver_name") or "").strip() == driver_name:
                raw_class = str(result.get("car_class") or "").strip()
                if raw_class:
                    return raw_class
    return ""
