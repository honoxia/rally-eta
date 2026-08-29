"""Persistence helpers for race-day commissioner decisions."""

from __future__ import annotations

import sqlite3
from typing import Any, Mapping


def save_operation_decision(db_path: str, decision: Mapping[str, Any]) -> int:
    """Validate and persist the selected race-day notional time."""
    selected_seconds = float(decision.get("selected_time_seconds") or 0.0)
    if selected_seconds <= 0:
        raise ValueError("Seçilen karar süresi 0'dan büyük olmalı.")

    rationale = str(decision.get("rationale") or "").strip()
    if len(rationale) < 5:
        raise ValueError("Karar gerekçesi en az 5 karakter olmalı.")

    required_text = {
        "rally_id": "Yarış kimliği",
        "stage_id": "Etap kimliği",
        "driver_name": "Pilot",
        "selected_method": "Seçilen yöntem",
        "selected_time_str": "Seçilen süre",
    }
    values = {}
    for key, label in required_text.items():
        value = str(decision.get(key) or "").strip()
        if not value:
            raise ValueError(f"{label} zorunlu.")
        values[key] = value

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            """
            INSERT INTO operation_decisions (
                rally_id, rally_name, stage_id, stage_number, stage_name,
                driver_name, raw_class, selected_method, selected_time_seconds,
                selected_time_str, km_based_seconds, percentage_seconds,
                ml_seconds, reference_stage_count, rationale, source_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                values["rally_id"],
                str(decision.get("rally_name") or "").strip(),
                values["stage_id"],
                int(decision.get("stage_number") or 0),
                str(decision.get("stage_name") or "").strip(),
                values["driver_name"],
                str(decision.get("raw_class") or "").strip(),
                values["selected_method"],
                selected_seconds,
                values["selected_time_str"],
                _optional_float(decision.get("km_based_seconds")),
                _optional_float(decision.get("percentage_seconds")),
                _optional_float(decision.get("ml_seconds")),
                int(decision.get("reference_stage_count") or 0),
                rationale,
                str(decision.get("source_url") or "").strip(),
            ],
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)
