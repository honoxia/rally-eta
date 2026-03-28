from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.data.master_schema import (
    apply_master_schema,
    build_stage_id,
    compute_geometry_hash,
    enrich_stage_geometry,
    ensure_stage_geometry_table,
    populate_master_dimensions,
    table_exists,
)
from src.data.results_merge import create_merge_backups, export_stage_geometry_db


GEOMETRY_FIELDS = [
    "stage_id",
    "rally_id",
    "rally_name",
    "stage_name",
    "stage_number",
    "surface",
    "distance_km",
    "curvature_sum",
    "curvature_density",
    "p95_curvature",
    "max_curvature",
    "avg_curvature",
    "hairpin_count",
    "hairpin_density",
    "turn_count",
    "turn_density",
    "straight_ratio",
    "sign_changes_per_km",
    "total_ascent",
    "total_descent",
    "max_grade",
    "avg_grade",
    "avg_abs_grade",
    "max_elevation",
    "min_elevation",
    "min_altitude",
    "max_altitude",
    "elevation_gain",
    "geometry_points",
    "elevation_api_calls",
    "cache_hit_rate",
    "straight_percentage",
    "curvy_percentage",
    "geometry_json",
    "analyzer_version",
    "analysis_version",
    "kml_file",
    "source_kml",
    "processed_at",
    "analyzed_at",
    "elevation_status",
    "geometry_status",
    "geometry_hash",
    "validated_at",
    "is_active",
]


@dataclass
class GeometryMergeSummary:
    merge_run_id: str
    master_db_path: str
    source_label: str
    incoming_rows: int
    inserted_rows: int
    metadata_updated_rows: int
    duplicate_rows: int
    conflict_rows: int
    skipped_rows: int
    backups: Dict[str, str]
    merge_log_path: str
    conflict_stage_ids: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _normalize_number(value: Any) -> Optional[float]:
    if value in (None, "", "unknown"):
        return None
    try:
        return float(value)
    except Exception:
        return None


def _normalize_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _resolve_effective_surface(conn: sqlite3.Connection, stage_id: Optional[str], rally_id: Optional[str], incoming_surface: Optional[str]) -> Optional[str]:
    normalized_surface = _normalize_text(incoming_surface)
    if normalized_surface:
        normalized_surface = normalized_surface.lower()

    if stage_id and table_exists(conn, "stages"):
        row = conn.execute(
            """
            SELECT CASE
                WHEN surface_override = 1 AND surface IS NOT NULL THEN surface
                ELSE NULL
            END
            FROM stages
            WHERE stage_id = ?
            """,
            [stage_id],
        ).fetchone()
        if row and row[0]:
            return row[0]

    if rally_id and table_exists(conn, "rallies"):
        row = conn.execute(
            "SELECT surface FROM rallies WHERE rally_id = ?",
            [rally_id],
        ).fetchone()
        if row and row[0]:
            return row[0]

    return normalized_surface


def _derive_quality_flags(row: Dict[str, Any]) -> tuple[str, str, Optional[str]]:
    distance_km = _normalize_number(row.get("distance_km")) or 0.0
    total_ascent = _normalize_number(row.get("total_ascent")) or 0.0
    total_descent = _normalize_number(row.get("total_descent")) or 0.0
    max_grade = _normalize_number(row.get("max_grade")) or 0.0
    max_elevation = _normalize_number(row.get("max_elevation")) or _normalize_number(row.get("max_altitude")) or 0.0
    min_elevation = _normalize_number(row.get("min_elevation")) or _normalize_number(row.get("min_altitude")) or 0.0

    has_elevation = any([
        total_ascent != 0.0,
        total_descent != 0.0,
        max_grade != 0.0,
        max_elevation != 0.0,
        min_elevation != 0.0,
    ])
    elevation_status = "available" if has_elevation else "missing"
    geometry_status = "validated"
    validated_at = row.get("validated_at")

    if distance_km > 3 and total_ascent == 0 and total_descent == 0 and max_grade == 0:
        elevation_status = "missing"
        geometry_status = "red_flag_missing_elevation"
        validated_at = None
    elif not validated_at:
        validated_at = row.get("analyzed_at") or row.get("processed_at") or datetime.now().isoformat()

    return elevation_status, geometry_status, validated_at


def canonicalize_geometry_row(
    conn: sqlite3.Connection,
    row: Dict[str, Any],
    source_label: str,
) -> Dict[str, Any]:
    rally_id = _normalize_text(row.get("rally_id"))
    stage_number = row.get("stage_number")
    try:
        stage_number = int(stage_number) if stage_number not in (None, "") else None
    except Exception:
        stage_number = None

    stage_id = _normalize_text(row.get("stage_id")) or build_stage_id(rally_id, stage_number)
    if stage_number is None and stage_id:
        import re

        match = re.search(r"_ss(\d+)$", stage_id)
        if match:
            stage_number = int(match.group(1))

    if not stage_id:
        raise ValueError("Geometry row is missing stage_id and cannot derive one")

    analyzed_at = _normalize_text(row.get("analyzed_at")) or _normalize_text(row.get("processed_at")) or datetime.now().isoformat()
    source_kml = _normalize_text(row.get("source_kml")) or _normalize_text(row.get("kml_file"))
    analysis_version = _normalize_text(row.get("analysis_version")) or _normalize_text(row.get("analyzer_version")) or source_label

    canonical = {
        "stage_id": stage_id,
        "rally_id": rally_id,
        "rally_name": _normalize_text(row.get("rally_name")),
        "stage_name": _normalize_text(row.get("stage_name")) or stage_id,
        "stage_number": stage_number,
        "surface": _resolve_effective_surface(conn, stage_id, rally_id, row.get("surface")),
        "distance_km": _normalize_number(row.get("distance_km")),
        "curvature_sum": _normalize_number(row.get("curvature_sum")),
        "curvature_density": _normalize_number(row.get("curvature_density")),
        "p95_curvature": _normalize_number(row.get("p95_curvature")),
        "max_curvature": _normalize_number(row.get("max_curvature")),
        "avg_curvature": _normalize_number(row.get("avg_curvature")),
        "hairpin_count": int(row.get("hairpin_count") or 0) if row.get("hairpin_count") not in (None, "") else None,
        "hairpin_density": _normalize_number(row.get("hairpin_density")),
        "turn_count": int(row.get("turn_count") or 0) if row.get("turn_count") not in (None, "") else None,
        "turn_density": _normalize_number(row.get("turn_density")),
        "straight_ratio": _normalize_number(row.get("straight_ratio")),
        "sign_changes_per_km": _normalize_number(row.get("sign_changes_per_km")),
        "total_ascent": _normalize_number(row.get("total_ascent")),
        "total_descent": _normalize_number(row.get("total_descent")),
        "max_grade": _normalize_number(row.get("max_grade")),
        "avg_grade": _normalize_number(row.get("avg_grade")),
        "avg_abs_grade": _normalize_number(row.get("avg_abs_grade")),
        "max_elevation": _normalize_number(row.get("max_elevation")) or _normalize_number(row.get("max_altitude")),
        "min_elevation": _normalize_number(row.get("min_elevation")) or _normalize_number(row.get("min_altitude")),
        "min_altitude": _normalize_number(row.get("min_altitude")) or _normalize_number(row.get("min_elevation")),
        "max_altitude": _normalize_number(row.get("max_altitude")) or _normalize_number(row.get("max_elevation")),
        "elevation_gain": _normalize_number(row.get("elevation_gain")),
        "geometry_points": int(row.get("geometry_points") or 0) if row.get("geometry_points") not in (None, "") else None,
        "elevation_api_calls": int(row.get("elevation_api_calls") or 0) if row.get("elevation_api_calls") not in (None, "") else None,
        "cache_hit_rate": _normalize_number(row.get("cache_hit_rate")),
        "straight_percentage": _normalize_number(row.get("straight_percentage")),
        "curvy_percentage": _normalize_number(row.get("curvy_percentage")),
        "geometry_json": row.get("geometry_json"),
        "analyzer_version": _normalize_text(row.get("analyzer_version")) or analysis_version,
        "analysis_version": analysis_version,
        "kml_file": _normalize_text(row.get("kml_file")) or source_kml,
        "source_kml": source_kml,
        "processed_at": _normalize_text(row.get("processed_at")) or analyzed_at,
        "analyzed_at": analyzed_at,
        "elevation_status": _normalize_text(row.get("elevation_status")),
        "geometry_status": _normalize_text(row.get("geometry_status")),
        "geometry_hash": _normalize_text(row.get("geometry_hash")),
        "validated_at": _normalize_text(row.get("validated_at")),
        "is_active": 1,
    }

    if canonical["straight_percentage"] is None and canonical["straight_ratio"] is not None:
        canonical["straight_percentage"] = canonical["straight_ratio"] * 100
    if canonical["curvy_percentage"] is None and canonical["straight_percentage"] is not None:
        canonical["curvy_percentage"] = max(0.0, 100.0 - canonical["straight_percentage"])
    if canonical["elevation_gain"] is None and canonical["max_elevation"] is not None and canonical["min_elevation"] is not None:
        canonical["elevation_gain"] = abs(canonical["max_elevation"] - canonical["min_elevation"])

    canonical["geometry_hash"] = canonical["geometry_hash"] or compute_geometry_hash(canonical)
    elevation_status, geometry_status, validated_at = _derive_quality_flags(canonical)
    canonical["elevation_status"] = elevation_status
    canonical["geometry_status"] = geometry_status
    canonical["validated_at"] = validated_at
    return canonical


def _near_duplicate(existing: Dict[str, Any], incoming: Dict[str, Any]) -> bool:
    def close(a: Optional[float], b: Optional[float], abs_tol: float, rel_tol: float = 0.0) -> bool:
        if a is None and b is None:
            return True
        if a is None or b is None:
            return False
        diff = abs(a - b)
        threshold = max(abs_tol, rel_tol * max(abs(a), abs(b), 1.0))
        return diff <= threshold

    checks = [
        close(_normalize_number(existing.get("distance_km")), _normalize_number(incoming.get("distance_km")), 0.05, 0.01),
        close(_normalize_number(existing.get("total_ascent")), _normalize_number(incoming.get("total_ascent")), 20.0, 0.05),
        close(_normalize_number(existing.get("total_descent")), _normalize_number(incoming.get("total_descent")), 20.0, 0.05),
        close(_normalize_number(existing.get("max_grade")), _normalize_number(incoming.get("max_grade")), 1.0, 0.15),
        close(_normalize_number(existing.get("p95_curvature")), _normalize_number(incoming.get("p95_curvature")), 0.0005, 0.2),
    ]

    existing_hairpin = existing.get("hairpin_count")
    incoming_hairpin = incoming.get("hairpin_count")
    if existing_hairpin is not None and incoming_hairpin is not None:
        checks.append(abs(int(existing_hairpin) - int(incoming_hairpin)) <= 1)

    return all(checks)


def _fetch_existing_geometry(conn: sqlite3.Connection, stage_id: str) -> Optional[Dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM stage_geometry WHERE stage_id = ?", [stage_id]).fetchone()
    return dict(row) if row else None


def _has_geometry_fingerprint(row: Dict[str, Any]) -> bool:
    for key in (
        "geometry_json",
        "distance_km",
        "total_ascent",
        "total_descent",
        "hairpin_count",
        "p95_curvature",
        "source_kml",
        "kml_file",
    ):
        value = row.get(key)
        if value not in (None, "", "unknown", 0, 0.0):
            return True
    return False


def _merge_geometry_payload(existing: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(existing)
    merged["stage_id"] = existing.get("stage_id") or incoming.get("stage_id")

    for key in GEOMETRY_FIELDS:
        if key in {"stage_id", "geometry_hash"}:
            continue
        incoming_value = incoming.get(key)
        if incoming_value not in (None, "", "unknown"):
            merged[key] = incoming_value

    if not merged.get("analysis_version") and merged.get("analyzer_version"):
        merged["analysis_version"] = merged["analyzer_version"]
    if not merged.get("source_kml") and merged.get("kml_file"):
        merged["source_kml"] = merged["kml_file"]
    if not merged.get("kml_file") and merged.get("source_kml"):
        merged["kml_file"] = merged["source_kml"]
    if not merged.get("processed_at") and merged.get("analyzed_at"):
        merged["processed_at"] = merged["analyzed_at"]
    if not merged.get("analyzed_at") and merged.get("processed_at"):
        merged["analyzed_at"] = merged["processed_at"]

    incoming_hash = incoming.get("geometry_hash") if _has_geometry_fingerprint(incoming) else None
    merged["geometry_hash"] = incoming_hash or merged.get("geometry_hash") or compute_geometry_hash(merged)
    elevation_status, geometry_status, validated_at = _derive_quality_flags(merged)
    merged["elevation_status"] = elevation_status
    merged["geometry_status"] = geometry_status
    merged["validated_at"] = validated_at
    merged["is_active"] = int(merged.get("is_active") or 1)
    return merged


def _write_geometry_row(conn: sqlite3.Connection, row: Dict[str, Any]) -> None:
    columns = [field for field in GEOMETRY_FIELDS if field in row]
    placeholders = ",".join(["?"] * len(columns))
    conn.execute(
        f"""
        INSERT OR REPLACE INTO stage_geometry ({','.join(columns)})
        VALUES ({placeholders})
        """,
        [row.get(column) for column in columns],
    )


def _update_geometry_metadata(conn: sqlite3.Connection, existing: Dict[str, Any], incoming: Dict[str, Any]) -> None:
    _write_geometry_row(conn, _merge_geometry_payload(existing, incoming))


def _insert_geometry_conflict(
    conn: sqlite3.Connection,
    stage_id: str,
    existing: Dict[str, Any],
    incoming: Dict[str, Any],
    conflict_type: str,
) -> None:
    conn.execute(
        """
        INSERT INTO merge_conflicts (
            entity_type, entity_key, conflict_type, master_payload, incoming_payload
        ) VALUES (?, ?, ?, ?, ?)
        """,
        [
            "stage_geometry",
            stage_id,
            conflict_type,
            json.dumps(existing, ensure_ascii=False),
            json.dumps(incoming, ensure_ascii=False),
        ],
    )


def _sync_stage_catalog_for_geometry(conn: sqlite3.Connection, row: Dict[str, Any]) -> None:
    stage_id = row.get("stage_id")
    rally_id = row.get("rally_id")
    stage_number = row.get("stage_number")
    stage_name = row.get("stage_name") or stage_id
    if not stage_id or not rally_id or stage_number is None:
        return

    rally_name = row.get("rally_name") or rally_id
    if table_exists(conn, "rallies"):
        conn.execute(
            """
            INSERT INTO rallies (rally_id, rally_name, surface)
            VALUES (?, ?, ?)
            ON CONFLICT(rally_id) DO UPDATE SET
                rally_name = COALESCE(excluded.rally_name, rallies.rally_name),
                surface = COALESCE(rallies.surface, excluded.surface),
                updated_at = CURRENT_TIMESTAMP
            """,
            [rally_id, rally_name, row.get("surface")],
        )

    if table_exists(conn, "stages"):
        rally_surface_row = conn.execute(
            "SELECT surface FROM rallies WHERE rally_id = ?",
            [rally_id],
        ).fetchone()
        rally_surface = rally_surface_row[0] if rally_surface_row else None
        stage_surface = row.get("surface")
        surface_override = int(bool(stage_surface and rally_surface and stage_surface != rally_surface))
        conn.execute(
            """
            INSERT INTO stages (
                stage_id, rally_id, stage_number, stage_name, surface,
                surface_override, length_km, match_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(stage_id) DO UPDATE SET
                rally_id = excluded.rally_id,
                stage_number = excluded.stage_number,
                stage_name = excluded.stage_name,
                surface = excluded.surface,
                surface_override = excluded.surface_override,
                length_km = COALESCE(excluded.length_km, stages.length_km),
                match_status = 'matched',
                updated_at = CURRENT_TIMESTAMP
            """,
            [
                stage_id,
                rally_id,
                stage_number,
                stage_name,
                stage_surface if surface_override else None,
                surface_override,
                row.get("distance_km"),
                "matched",
            ],
        )


def merge_geometry_rows(
    master_db_path: str,
    incoming_rows: List[Dict[str, Any]],
    source_label: str,
    backup_dir: str = "backups",
    report_dir: str = "reports",
    replace_existing: bool = False,
) -> GeometryMergeSummary:
    master_path = Path(master_db_path)
    if not master_path.exists():
        raise FileNotFoundError(f"Master database not found: {master_path}")

    merge_run_id = f"geometry_merge_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    Path(backup_dir).mkdir(parents=True, exist_ok=True)
    Path(report_dir).mkdir(parents=True, exist_ok=True)

    pre_backups = create_merge_backups(str(master_path), backup_dir, merge_run_id, "pre")
    apply_master_schema(str(master_path))

    conn = sqlite3.connect(master_path)
    conn.row_factory = sqlite3.Row
    inserted_rows = 0
    metadata_updated_rows = 0
    duplicate_rows = 0
    conflict_rows = 0
    skipped_rows = 0
    conflict_stage_ids: List[str] = []

    try:
        ensure_stage_geometry_table(conn)

        if replace_existing:
            conn.execute("DELETE FROM stage_geometry")

        for raw_row in incoming_rows:
            try:
                canonical = canonicalize_geometry_row(conn, raw_row, source_label)
            except Exception:
                skipped_rows += 1
                continue

            existing = _fetch_existing_geometry(conn, canonical["stage_id"])
            if existing is None:
                _write_geometry_row(conn, canonical)
                _sync_stage_catalog_for_geometry(conn, canonical)
                inserted_rows += 1
                continue

            candidate = _merge_geometry_payload(existing, canonical)

            if existing.get("geometry_hash") == candidate.get("geometry_hash"):
                _write_geometry_row(conn, candidate)
                _sync_stage_catalog_for_geometry(conn, candidate)
                metadata_updated_rows += 1
                continue

            if _near_duplicate(existing, candidate):
                _write_geometry_row(conn, candidate)
                _sync_stage_catalog_for_geometry(conn, candidate)
                duplicate_rows += 1
                continue

            _insert_geometry_conflict(
                conn,
                candidate["stage_id"],
                existing,
                candidate,
                "same_stage_id_different_route",
            )
            conflict_rows += 1
            conflict_stage_ids.append(candidate["stage_id"])

        enrich_stage_geometry(conn)
        populate_master_dimensions(conn)
        conn.execute(
            """
            INSERT INTO merge_log (
                merge_scope, source_path, inserted_count, skipped_count, conflict_count, notes
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                "geometry_merge",
                source_label,
                inserted_rows,
                skipped_rows + duplicate_rows + metadata_updated_rows,
                conflict_rows,
                json.dumps(
                    {
                        "metadata_updated_rows": metadata_updated_rows,
                        "duplicate_rows": duplicate_rows,
                        "replace_existing": replace_existing,
                        "conflict_stage_ids": conflict_stage_ids,
                    },
                    ensure_ascii=False,
                ),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    post_backups = create_merge_backups(str(master_path), backup_dir, merge_run_id, "post")
    merge_log_path = Path(report_dir) / f"{merge_run_id}.json"
    summary = GeometryMergeSummary(
        merge_run_id=merge_run_id,
        master_db_path=str(master_path),
        source_label=source_label,
        incoming_rows=len(incoming_rows),
        inserted_rows=inserted_rows,
        metadata_updated_rows=metadata_updated_rows,
        duplicate_rows=duplicate_rows,
        conflict_rows=conflict_rows,
        skipped_rows=skipped_rows,
        backups={
            "pre_results": pre_backups["results"],
            "pre_geometry": pre_backups["geometry"],
            "post_results": post_backups["results"],
            "post_geometry": post_backups["geometry"],
        },
        merge_log_path=str(merge_log_path),
        conflict_stage_ids=conflict_stage_ids,
    )
    merge_log_path.write_text(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def _load_geometry_rows_from_db(incoming_db_path: str) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(incoming_db_path)
    conn.row_factory = sqlite3.Row
    try:
        table_name = None
        if table_exists(conn, "stage_geometry"):
            table_name = "stage_geometry"
        elif table_exists(conn, "stages_metadata"):
            table_name = "stages_metadata"
        else:
            raise ValueError("Incoming geometry database does not contain stage_geometry or stages_metadata")

        rows = conn.execute(f"SELECT * FROM {table_name}").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def merge_geometry_database(
    master_db_path: str,
    incoming_db_path: str,
    backup_dir: str = "backups",
    report_dir: str = "reports",
    replace_existing: bool = False,
) -> GeometryMergeSummary:
    incoming_rows = _load_geometry_rows_from_db(incoming_db_path)
    return merge_geometry_rows(
        master_db_path=master_db_path,
        incoming_rows=incoming_rows,
        source_label=str(incoming_db_path),
        backup_dir=backup_dir,
        report_dir=report_dir,
        replace_existing=replace_existing,
    )


def export_master_geometry_db(master_db_path: str, output_path: str) -> str:
    return export_stage_geometry_db(master_db_path, output_path)
