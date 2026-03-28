from __future__ import annotations

import json
import shutil
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from src.data.car_class_normalizer import CarClassNormalizer
from src.data.master_schema import (
    apply_master_schema,
    build_driver_id,
    build_stage_id,
    ensure_results_master_tables,
    ensure_stage_results_columns,
    populate_master_dimensions,
    table_exists,
)


RESULT_INSERT_FIELDS = [
    "result_id",
    "rally_id",
    "rally_name",
    "stage_number",
    "stage_name",
    "stage_length_km",
    "stage_id",
    "car_number",
    "driver_name",
    "raw_driver_name",
    "driver_id",
    "co_driver_name",
    "car_class",
    "normalized_class",
    "vehicle",
    "time_str",
    "time_seconds",
    "diff_str",
    "diff_seconds",
    "surface",
    "source_run_id",
    "status",
]

COMPARE_FIELDS = [
    "rally_id",
    "rally_name",
    "stage_number",
    "stage_name",
    "stage_length_km",
    "car_number",
    "raw_driver_name",
    "co_driver_name",
    "car_class",
    "vehicle",
    "time_str",
    "time_seconds",
    "diff_str",
    "diff_seconds",
    "surface",
    "status",
]

TEMP_TABLE_SQL = """
    CREATE TEMP TABLE incoming_stage_results_tmp (
        temp_id INTEGER PRIMARY KEY AUTOINCREMENT,
        result_id TEXT NOT NULL,
        rally_id TEXT,
        rally_name TEXT,
        stage_number INTEGER,
        stage_name TEXT,
        stage_length_km REAL,
        stage_id TEXT,
        car_number TEXT,
        driver_name TEXT,
        raw_driver_name TEXT,
        driver_id TEXT,
        co_driver_name TEXT,
        car_class TEXT,
        normalized_class TEXT,
        vehicle TEXT,
        time_str TEXT,
        time_seconds REAL,
        diff_str TEXT,
        diff_seconds REAL,
        surface TEXT,
        source_run_id TEXT,
        status TEXT
    )
"""


@dataclass
class MergeSummary:
    merge_run_id: str
    master_db_path: str
    source_db_path: str
    incoming_rows: int
    inserted_rows: int
    skipped_rows: int
    conflict_rows: int
    incoming_duplicate_rows: int
    backups: Dict[str, str]
    merge_log_path: str
    alias_report_path: Optional[str]
    conflict_result_ids: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _table_columns(conn: sqlite3.Connection, table_name: str) -> List[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()]


def _row_to_dict(columns: Iterable[str], row: Iterable[Any]) -> Dict[str, Any]:
    return dict(zip(columns, row))


def _canonicalize_stage_result(
    row: Dict[str, Any],
    normalizer: CarClassNormalizer,
    source_run_id: str,
) -> Dict[str, Any]:
    rally_id = str(row.get("rally_id") or "").strip()
    rally_name = (row.get("rally_name") or rally_id).strip()
    stage_number = row.get("stage_number")
    try:
        stage_number = int(stage_number) if stage_number is not None else None
    except Exception:
        stage_number = None

    stage_id = row.get("stage_id") or build_stage_id(rally_id, stage_number)
    raw_driver_name = (row.get("raw_driver_name") or row.get("driver_name") or "").strip()
    driver_name = (row.get("driver_name") or raw_driver_name).strip()
    driver_id = row.get("driver_id") or build_driver_id(raw_driver_name or driver_name)
    car_class = (row.get("car_class") or "").strip()
    normalized_class = row.get("normalized_class") or (normalizer.normalize(car_class) if car_class else "Unknown")
    surface = (row.get("surface") or "").strip().lower() or None
    result_id = row.get("result_id")
    if not result_id:
        result_id = f"{rally_id}_ss{stage_number}_{row.get('car_number') or driver_id}"

    status = row.get("status")
    if not status:
        status = "FINISHED" if row.get("time_seconds") else "UNKNOWN"

    return {
        "result_id": str(result_id),
        "rally_id": rally_id or None,
        "rally_name": rally_name or None,
        "stage_number": stage_number,
        "stage_name": (row.get("stage_name") or stage_id or "").strip() or None,
        "stage_length_km": row.get("stage_length_km"),
        "stage_id": stage_id,
        "car_number": (row.get("car_number") or "").strip() or None,
        "driver_name": driver_name or None,
        "raw_driver_name": raw_driver_name or driver_name or None,
        "driver_id": driver_id,
        "co_driver_name": (row.get("co_driver_name") or "").strip() or None,
        "car_class": car_class or None,
        "normalized_class": normalized_class,
        "vehicle": (row.get("vehicle") or "").strip() or None,
        "time_str": (row.get("time_str") or "").strip() or None,
        "time_seconds": row.get("time_seconds"),
        "diff_str": (row.get("diff_str") or "").strip() or None,
        "diff_seconds": row.get("diff_seconds"),
        "surface": surface,
        "source_run_id": source_run_id,
        "status": status,
    }


def _compare_result_rows(master_row: Dict[str, Any], incoming_row: Dict[str, Any]) -> tuple[bool, Dict[str, Dict[str, Any]]]:
    diff: Dict[str, Dict[str, Any]] = {}
    for field in COMPARE_FIELDS:
        master_value = _normalize_compare_value(master_row.get(field))
        incoming_value = _normalize_compare_value(incoming_row.get(field))
        if master_value != incoming_value:
            diff[field] = {
                "master": master_row.get(field),
                "incoming": incoming_row.get(field),
            }
    return len(diff) == 0, diff


def _normalize_compare_value(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return value


def _ensure_backup_dirs(backup_dir: Path, report_dir: Path) -> None:
    backup_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)


def export_stage_geometry_db(master_db_path: str, output_path: str) -> str:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    if output.exists():
        output.unlink()

    src = sqlite3.connect(master_db_path)
    src.row_factory = sqlite3.Row
    try:
        create_sql = src.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='stage_geometry'"
        ).fetchone()
        if not create_sql:
            temp = sqlite3.connect(output)
            temp.close()
            return str(output)

        create_statement = create_sql[0]
        rows = src.execute("SELECT * FROM stage_geometry").fetchall()
        columns = _table_columns(src, "stage_geometry")
    finally:
        src.close()

    dst = sqlite3.connect(output)
    try:
        dst.execute(create_statement)
        placeholders = ",".join(["?"] * len(columns))
        for row in rows:
            dst.execute(
                f"INSERT INTO stage_geometry ({','.join(columns)}) VALUES ({placeholders})",
                [row[column] for column in columns],
            )
        dst.commit()
    finally:
        dst.close()

    return str(output)


def create_merge_backups(master_db_path: str, backup_dir: str, merge_run_id: str, phase: str) -> Dict[str, str]:
    backup_root = Path(backup_dir)
    backup_root.mkdir(parents=True, exist_ok=True)

    stamp = merge_run_id.replace("results_merge_", "")
    results_backup = backup_root / f"results_backup_{stamp}_{phase}.db"
    geometry_backup = backup_root / f"geometry_backup_{stamp}_{phase}.db"

    shutil.copy2(master_db_path, results_backup)
    export_stage_geometry_db(master_db_path, str(geometry_backup))

    return {
        "results": str(results_backup),
        "geometry": str(geometry_backup),
    }


def _load_incoming_temp_table(
    master_conn: sqlite3.Connection,
    incoming_db_path: str,
    source_run_id: str,
) -> tuple[int, int]:
    incoming_conn = sqlite3.connect(incoming_db_path)
    incoming_conn.row_factory = sqlite3.Row
    normalizer = CarClassNormalizer()

    try:
        if not table_exists(incoming_conn, "stage_results"):
            raise ValueError("Incoming database does not contain stage_results")

        columns = _table_columns(incoming_conn, "stage_results")
        rows = incoming_conn.execute("SELECT * FROM stage_results").fetchall()
    finally:
        incoming_conn.close()

    placeholders = ",".join(["?"] * len(RESULT_INSERT_FIELDS))
    seen: Dict[str, Dict[str, Any]] = {}
    duplicate_rows = 0

    for row in rows:
        canonical = _canonicalize_stage_result(dict(row), normalizer, source_run_id)
        existing = seen.get(canonical["result_id"])
        if existing:
            same, _ = _compare_result_rows(existing, canonical)
            if same:
                duplicate_rows += 1
                continue
            duplicate_rows += 1
        else:
            seen[canonical["result_id"]] = canonical

        master_conn.execute(
            f"""
            INSERT INTO incoming_stage_results_tmp ({','.join(RESULT_INSERT_FIELDS)})
            VALUES ({placeholders})
            """,
            [canonical.get(field) for field in RESULT_INSERT_FIELDS],
        )

    return len(rows), duplicate_rows


def _fetch_master_row(conn: sqlite3.Connection, result_id: str) -> Optional[Dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        f"""
        SELECT {','.join(COMPARE_FIELDS)}
        FROM stage_results
        WHERE result_id = ?
        """,
        [result_id],
    ).fetchone()
    return dict(row) if row else None


def _insert_conflict(
    conn: sqlite3.Connection,
    result_id: str,
    master_row: Dict[str, Any],
    incoming_row: Dict[str, Any],
    diff: Dict[str, Dict[str, Any]],
) -> None:
    conn.execute(
        """
        INSERT INTO merge_conflicts (
            entity_type, entity_key, conflict_type, master_payload, incoming_payload
        ) VALUES (?, ?, ?, ?, ?)
        """,
        [
            "stage_results",
            result_id,
            "result_id_payload_mismatch",
            json.dumps({"row": master_row, "diff": diff}, ensure_ascii=False),
            json.dumps({"row": incoming_row, "diff": diff}, ensure_ascii=False),
        ],
    )


def recompute_stage_results_derived(conn: sqlite3.Connection) -> None:
    normalizer = CarClassNormalizer()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT result_id, rally_id, stage_number, driver_name, raw_driver_name, car_class
        FROM stage_results
        """
    ).fetchall()

    for row in rows:
        row_dict = dict(row)
        normalized_class = normalizer.normalize(row_dict["car_class"]) if row_dict.get("car_class") else "Unknown"
        raw_driver_name = row_dict.get("raw_driver_name") or row_dict.get("driver_name")
        driver_id = build_driver_id(raw_driver_name or row_dict.get("driver_name"))
        stage_id = build_stage_id(row_dict.get("rally_id"), row_dict.get("stage_number"))

        conn.execute(
            """
            UPDATE stage_results
            SET
                normalized_class = ?,
                raw_driver_name = COALESCE(raw_driver_name, driver_name),
                driver_id = ?,
                stage_id = ?,
                status = COALESCE(status, 'FINISHED')
            WHERE result_id = ?
            """,
            [normalized_class, driver_id, stage_id, row_dict["result_id"]],
        )

    conn.execute("UPDATE stage_results SET ratio_to_class_best = NULL, class_position = NULL")

    groups = conn.execute(
        """
        SELECT stage_id, COALESCE(normalized_class, car_class) AS nclass
        FROM stage_results
        WHERE time_seconds > 0
          AND stage_id IS NOT NULL
          AND COALESCE(normalized_class, car_class) IS NOT NULL
        GROUP BY stage_id, COALESCE(normalized_class, car_class)
        """
    ).fetchall()

    for stage_id, normalized_class in groups:
        class_best_row = conn.execute(
            """
            SELECT MIN(time_seconds)
            FROM stage_results
            WHERE stage_id = ?
              AND COALESCE(normalized_class, car_class) = ?
              AND time_seconds > 0
            """,
            [stage_id, normalized_class],
        ).fetchone()
        class_best = class_best_row[0] if class_best_row else None
        if not class_best:
            continue

        conn.execute(
            """
            UPDATE stage_results
            SET ratio_to_class_best = time_seconds / ?
            WHERE stage_id = ?
              AND COALESCE(normalized_class, car_class) = ?
              AND time_seconds > 0
            """,
            [class_best, stage_id, normalized_class],
        )

        ranked_rows = conn.execute(
            """
            SELECT result_id
            FROM stage_results
            WHERE stage_id = ?
              AND COALESCE(normalized_class, car_class) = ?
              AND time_seconds > 0
            ORDER BY time_seconds ASC, result_id ASC
            """,
            [stage_id, normalized_class],
        ).fetchall()

        for position, ranked_row in enumerate(ranked_rows, 1):
            conn.execute(
                "UPDATE stage_results SET class_position = ? WHERE result_id = ?",
                [position, ranked_row[0]],
            )

    populate_master_dimensions(conn)
    conn.commit()


def merge_results_database(
    master_db_path: str,
    incoming_db_path: str,
    backup_dir: str = "backups",
    report_dir: str = "reports",
) -> MergeSummary:
    master_path = Path(master_db_path)
    incoming_path = Path(incoming_db_path)
    if not master_path.exists():
        raise FileNotFoundError(f"Master database not found: {master_path}")
    if not incoming_path.exists():
        raise FileNotFoundError(f"Incoming database not found: {incoming_path}")

    merge_run_id = f"results_merge_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    backup_root = Path(backup_dir)
    report_root = Path(report_dir)
    _ensure_backup_dirs(backup_root, report_root)

    pre_backups = create_merge_backups(str(master_path), str(backup_root), merge_run_id, "pre")
    alias_report_path = report_root / f"driver_alias_conflicts_{merge_run_id}.json"
    apply_master_schema(str(master_path), str(alias_report_path))

    conn = sqlite3.connect(master_path)
    conn.row_factory = sqlite3.Row

    try:
        ensure_results_master_tables(conn)
        ensure_stage_results_columns(conn)
        conn.execute("DROP TABLE IF EXISTS temp.incoming_stage_results_tmp")
        conn.execute(TEMP_TABLE_SQL)

        incoming_rows, incoming_duplicate_rows = _load_incoming_temp_table(
            conn,
            str(incoming_path),
            merge_run_id,
        )

        inserted_rows = 0
        skipped_rows = 0
        conflict_rows = 0
        conflict_result_ids: List[str] = []

        incoming_rows_data = conn.execute(
            f"SELECT {','.join(RESULT_INSERT_FIELDS)} FROM incoming_stage_results_tmp ORDER BY temp_id"
        ).fetchall()

        placeholders = ",".join(["?"] * len(RESULT_INSERT_FIELDS))
        for incoming_row in incoming_rows_data:
            incoming_dict = dict(incoming_row)
            result_id = incoming_dict["result_id"]
            master_row = _fetch_master_row(conn, result_id)
            if master_row is None:
                conn.execute(
                    f"""
                    INSERT INTO stage_results ({','.join(RESULT_INSERT_FIELDS)})
                    VALUES ({placeholders})
                    """,
                    [incoming_dict.get(field) for field in RESULT_INSERT_FIELDS],
                )
                inserted_rows += 1
                continue

            same, diff = _compare_result_rows(master_row, incoming_dict)
            if same:
                skipped_rows += 1
                continue

            _insert_conflict(conn, result_id, master_row, incoming_dict, diff)
            conflict_rows += 1
            conflict_result_ids.append(result_id)

        recompute_stage_results_derived(conn)

        notes = {
            "incoming_rows": incoming_rows,
            "incoming_duplicate_rows": incoming_duplicate_rows,
            "conflict_result_ids": conflict_result_ids,
            "source_db_path": str(incoming_path),
            "temp_table": "incoming_stage_results_tmp",
        }
        conn.execute(
            """
            INSERT INTO merge_log (
                merge_scope, source_path, inserted_count, skipped_count, conflict_count, notes
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                "results_merge",
                str(incoming_path),
                inserted_rows,
                skipped_rows,
                conflict_rows,
                json.dumps(notes, ensure_ascii=False),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    post_backups = create_merge_backups(str(master_path), str(backup_root), merge_run_id, "post")
    merge_log_path = report_root / f"results_merge_{merge_run_id}.json"
    summary = MergeSummary(
        merge_run_id=merge_run_id,
        master_db_path=str(master_path),
        source_db_path=str(incoming_path),
        incoming_rows=incoming_rows,
        inserted_rows=inserted_rows,
        skipped_rows=skipped_rows,
        conflict_rows=conflict_rows,
        incoming_duplicate_rows=incoming_duplicate_rows,
        backups={
            "pre_results": pre_backups["results"],
            "pre_geometry": pre_backups["geometry"],
            "post_results": post_backups["results"],
            "post_geometry": post_backups["geometry"],
        },
        merge_log_path=str(merge_log_path),
        alias_report_path=str(alias_report_path),
        conflict_result_ids=conflict_result_ids,
    )
    merge_log_path.write_text(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
