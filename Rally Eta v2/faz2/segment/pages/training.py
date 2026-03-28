"""
Rally ETA v2.0 - Model Egitimi Sayfasi
ML model egitimi ve metrik gosterimi.
"""

import streamlit as st
import sys
from pathlib import Path

# Shared modulleri import et
sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.config import get_db_path, get_model_dir, PROJECT_ROOT
from shared.data_loaders import get_model_status
from shared.ui_components import render_page_header


def render():
    """Model egitimi sayfasini render et."""
    render_page_header(
        "Model Egitimi",
        "Model hazirligini, metrikleri ve ozellik etkilerini tek ekranda izleyip buradan guncelleyebilirsiniz.",
        badge="Model Egitimi",
        eyebrow="Makine Ogrenimi Operasyonlari",
    )

    model_status = get_model_status()

    col1, col2, col3 = st.columns(3)

    with col1:
        if model_status.get("model_exists"):
            st.success("Model: Mevcut")
        else:
            st.warning("Model: Yok")

    with col2:
        st.metric("Egitim Verisi", model_status.get("training_data_count", 0))

    with col3:
        if model_status.get("metrics"):
            st.metric("MAPE", f"{model_status['metrics'].get('mape', 0):.2f}%")
        else:
            st.metric("MAPE", "-")

    st.markdown("---")

    if model_status.get("can_train"):
        if st.button("Modeli Egit", type="primary", use_container_width=True):
            _train_model()
    else:
        reason = model_status.get("reason", "Yetersiz veri")
        st.warning(f"Egitim yapilamaz: {reason}")
        st.info("KML dosyalarini yukleyip eslestirin.")

    if model_status.get("model_exists"):
        st.markdown("---")
        st.subheader("Mevcut Model Detaylari")

        metrics = model_status.get("metrics", {})
        if metrics:
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("MAE", f"{metrics.get('mae', 0):.4f}")
            col2.metric("RMSE", f"{metrics.get('rmse', 0):.4f}")
            col3.metric("MAPE", f"{metrics.get('mape', 0):.2f}%")
            col4.metric("R^2", f"{metrics.get('r2', 0):.4f}")

        if "feature_importance" in model_status:
            st.markdown("#### Ozellik Onemi")
            _show_feature_importance(model_status["feature_importance"])


def _train_model():
    """Model egitimini calistir."""
    with st.spinner("Model egitiliyor..."):
        try:
            src_path = str(PROJECT_ROOT)
            if src_path not in sys.path:
                sys.path.insert(0, src_path)

            from src.ml.model_trainer import ModelTrainer

            trainer = ModelTrainer(
                db_path=get_db_path(),
                model_dir=get_model_dir(),
            )
            result = trainer.train()

            if result.success:
                st.success("Model egitildi!")

                col1, col2, col3 = st.columns(3)
                col1.metric("MAE", f"{result.metrics['mae']:.4f}")
                col2.metric("RMSE", f"{result.metrics['rmse']:.4f}")
                col3.metric("MAPE", f"{result.metrics['mape']:.2f}%")

                if hasattr(result, "feature_importance") and result.feature_importance:
                    st.markdown("#### Ozellik Onemi")
                    _show_feature_importance(result.feature_importance)
            else:
                st.error(f"Hata: {result.error_message}")

        except Exception as e:
            st.error(f"Hata: {e}")


def _show_feature_importance(importance: dict):
    """Feature importance tablosu goster."""
    if not importance:
        return

    import pandas as pd
    from shared.ui_components import show_html_table

    df = pd.DataFrame(
        [
            {"Ozellik": key, "Onem": f"{value:.4f}"}
            for key, value in sorted(importance.items(), key=lambda item: -item[1])
        ]
    )
    show_html_table(df, max_rows=20)
