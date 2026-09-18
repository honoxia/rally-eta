"""Cached application services shared by Streamlit pages."""

from pathlib import Path
from typing import Optional

import streamlit as st

from .config import get_db_path, get_model_path


@st.cache_resource(show_spinner=False)
def _build_prediction_service(
    db_path: str,
    model_path: Optional[str],
    model_modified_ns: int,
):
    # model_modified_ns is intentionally part of the cache key.
    del model_modified_ns
    from src.prediction.prediction_service import PredictionService

    return PredictionService(db_path=db_path, model_path=model_path)


def get_prediction_service():
    """Return one predictor service until the DB path or model file changes."""
    model = get_model_path()
    model_path = str(model) if model.exists() else None
    model_modified_ns = model.stat().st_mtime_ns if model.exists() else 0
    return _build_prediction_service(get_db_path(), model_path, model_modified_ns)


def clear_prediction_service_cache() -> None:
    """Invalidate cached services after model or workspace changes."""
    _build_prediction_service.clear()
