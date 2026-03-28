from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


RESULTS_SOURCE_RUN_ID = "legacy_results_import_v1"
GEOMETRY_SOURCE_RUN_ID = "legacy_geometry_import_v1"


def normalize_name_key(name: Optional[str]) -> str:
    value = (name or "").strip()
    if not value:
        return ""
    value = value.replace("ı", "i").replace("İ", "i")
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower()
    value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    value = re.sub(r"_+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def slugify(value: Optional[str], fallback: str = "unknown") -> str:
    text = normalize_name_key(value).replace(" ", "-")
    text = re.sub(r"[^a-z0-9-]+", "", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text or fallback


def build_driver_id(name: Optional[str]) -> str:
    key = normalize_name_key(name)
    return f"drv_{slugify(key)}" if key else "drv_unknown"


def build_stage_id(rally_id: Any, stage_number: Any) -> Optional[str]:
    if rally_id is None or stage_number is None:
        return None
    rally_text = str(rally_id).strip()
    if not rally_text:
        return None
    try:
        stage_value = int(stage_number)
    except Exception:
        match = re.search(r"(\d+)", str(stage_number))
        if not match:
            return None
        stage_value = int(match.group(1))
    return f"{rally_text}_ss{stage_value}"


def choose_display_name(names_with_counts: Iterable[tuple[str, int]]) -> str:
    ranked = sorted(
        names_with_counts,
        key=lambda item: (
            -(item[1] or 0),
            sum(1 for ch in item[0] if ch.isupper()),
            len(item[0]),
            item[0],
        ),
    )
    return ranked[0][0] if ranked else "Unknown Driver"


def detect_manual_review(names: List[str]) -> bool:
    if len(names) <= 1:
        return False
    lengths = [len(name.strip()) for name in names if name and name.strip()]
    if not lengths:
        return False
    if max(lengths) >= max(12, min(lengths) * 1.7):
        return True
    token_counts = {len(normalize_name_key(name).split()) for name in names}
    return len(token_counts) > 1


def compute_geometry_hash(row: Dict[str, Any]) -> str:
    geometry_json = row.get("geometry_json") or ""
    if geometry_json:
        base = geometry_json
    else:
        metrics = {
            "stage_id": row.get("stage_id"),
            "distance_km": round(float(row.get("distance_km") or 0.0), 4),
            "total_ascent": round(float(row.get("total_ascent") or 0.0), 2),
            "total_descent": round(float(row.get("total_descent") or 0.0), 2),
            "hairpin_count": int(row.get("hairpin_count") or 0),
            "p95_curvature": round(float(row.get("p95_curvature") or 0.0), 6),
            "source_kml": row.get("source_kml") or row.get("kml_file") or "",
        }
        base = json.dumps(metrics, ensure_ascii=True, sort_keys=True)
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        [table_name],
    ).fetchone()
    return row is not None


def get_table_type(conn: sqlite3.Connection, table_name: str) -> Optional[str]:
    row = conn.execute(
        "SELECT type FROM sqlite_master WHERE name = ?",
        [table_name],
    ).fetchone()
    return row[0] if row else None


def get_table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    if not table_exists(conn, table_name):
        return set()
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, definition: str) -> None:
    if column_name not in get_table_columns(conn, table_name):
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def ensure_results_master_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            migration_name TEXT PRIMARY KEY,
            applied_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS rallies (
            rally_id TEXT PRIMARY KEY,
            rally_name TEXT,
            surface TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS drivers (
            driver_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            normalized_name_key TEXT NOT NULL,
            merge_review_status TEXT DEFAULT 'auto',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_drivers_normalized_name_key
            ON drivers(normalized_name_key);

        CREATE TABLE IF NOT EXISTS driver_aliases (
            alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
            driver_id TEXT NOT NULL,
            alias_name TEXT NOT NULL,
            normalized_name_key TEXT NOT NULL,
            is_primary INTEGER DEFAULT 0,
            merge_status TEXT DEFAULT 'auto',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(alias_name),
            FOREIGN KEY(driver_id) REFERENCES drivers(driver_id)
        );

        CREATE TABLE IF NOT EXISTS stages (
            stage_id TEXT PRIMARY KEY,
            rally_id TEXT NOT NULL,
            stage_number INTEGER NOT NULL,
            stage_name TEXT NOT NULL,
            surface TEXT,
            surface_override INTEGER DEFAULT 0,
            length_km REAL,
            match_status TEXT DEFAULT 'results_only',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(rally_id, stage_number)
        );

        CREATE TABLE IF NOT EXISTS prediction_log (
            prediction_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            rally_id TEXT NOT NULL,
            stage_id TEXT NOT NULL,
            driver_id TEXT NOT NULL,
            predicted_time REAL,
            confidence REAL,
            used_geometry INTEGER DEFAULT 0,
            data_quality_flags TEXT,
            model_version TEXT,
            predicted_at TEXT DEFAULT CURRENT_TIMESTAMP,
            actual_time REAL,
            error_pct REAL,
            accepted INTEGER,
            compared_at TEXT,
            comparison_status TEXT DEFAULT 'pending'
        );

        CREATE TABLE IF NOT EXISTS merge_conflicts (
            conflict_id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL,
            entity_key TEXT NOT NULL,
            conflict_type TEXT NOT NULL,
            master_payload TEXT,
            incoming_payload TEXT,
            detected_at TEXT DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'open'
        );

        CREATE TABLE IF NOT EXISTS merge_log (
            merge_id INTEGER PRIMARY KEY AUTOINCREMENT,
            merge_scope TEXT NOT NULL,
            source_path TEXT,
            inserted_count INTEGER DEFAULT 0,
            skipped_count INTEGER DEFAULT 0,
            conflict_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            notes TEXT
        );
        """
    )

    for name, definition in {
        "resolved_issue_types": "TEXT DEFAULT '[]'",
        "resolution_note": "TEXT",
        "resolved_at": "TEXT",
        "resolution_source": "TEXT",
    }.items():
        ensure_column(conn, "prediction_log", name, definition)


def ensure_stage_results_columns(conn: sqlite3.Connection) -> None:
    if not table_exists(conn, "stage_results"):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stage_results (
                result_id TEXT PRIMARY KEY,
                rally_id TEXT,
                rally_name TEXT,
                stage_number INTEGER,
                stage_name TEXT,
                stage_length_km REAL,
                car_number TEXT,
                driver_name TEXT,
                co_driver_name TEXT,
                car_class TEXT,
                vehicle TEXT,
                time_str TEXT,
                time_seconds REAL,
                diff_str TEXT,
                diff_seconds REAL,
                surface TEXT,
                normalized_class TEXT,
                ratio_to_class_best REAL,
                class_position INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    for name, definition in {
        "stage_length_km": "REAL",
        "co_driver_name": "TEXT",
        "normalized_class": "TEXT",
        "ratio_to_class_best": "REAL",
        "class_position": "INTEGER",
        "stage_id": "TEXT",
        "driver_id": "TEXT",
        "raw_driver_name": "TEXT",
        "source_run_id": "TEXT",
        "status": "TEXT DEFAULT 'FINISHED'",
    }.items():
        ensure_column(conn, "stage_results", name, definition)

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_stage_results_stage_id ON stage_results(stage_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_stage_results_driver_id ON stage_results(driver_id)"
    )


def ensure_stage_geometry_table(conn: sqlite3.Connection) -> None:
    stages_metadata_type = get_table_type(conn, "stages_metadata")
    stage_geometry_exists = table_exists(conn, "stage_geometry")

    if stage_geometry_exists and get_table_type(conn, "stage_geometry") == "view":
        conn.execute("DROP VIEW stage_geometry")
        stage_geometry_exists = False

    if not stage_geometry_exists and stages_metadata_type == "table":
        conn.execute("ALTER TABLE stages_metadata RENAME TO stage_geometry")
        stage_geometry_exists = True

    if not stage_geometry_exists:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stage_geometry (
                stage_id TEXT PRIMARY KEY,
                rally_id TEXT,
                stage_name TEXT,
                stage_number INTEGER,
                surface TEXT,
                distance_km REAL,
                curvature_sum REAL,
                curvature_density REAL,
                p95_curvature REAL,
                max_curvature REAL,
                avg_curvature REAL,
                hairpin_count INTEGER,
                hairpin_density REAL,
                turn_count INTEGER,
                turn_density REAL,
                straight_ratio REAL,
                sign_changes_per_km REAL,
                total_ascent REAL,
                total_descent REAL,
                max_grade REAL,
                avg_abs_grade REAL,
                max_elevation REAL,
                min_elevation REAL,
                geometry_points INTEGER,
                elevation_api_calls INTEGER,
                cache_hit_rate REAL,
                straight_percentage REAL,
                curvy_percentage REAL,
                analysis_version TEXT,
                source_kml TEXT,
                analyzed_at TEXT,
                geometry_json TEXT,
                elevation_status TEXT DEFAULT 'unknown',
                geometry_status TEXT DEFAULT 'pending',
                geometry_hash TEXT,
                validated_at TEXT,
                is_active INTEGER DEFAULT 1
            )
            """
        )

    columns = get_table_columns(conn, "stage_geometry")
    for legacy_name, new_name in {
        "analyzer_version": "analysis_version",
        "kml_file": "source_kml",
        "processed_at": "analyzed_at",
    }.items():
        if legacy_name in columns and new_name not in columns:
            ensure_column(conn, "stage_geometry", new_name, "TEXT")
            conn.execute(
                f"""
                UPDATE stage_geometry
                SET {new_name} = COALESCE({new_name}, {legacy_name})
                WHERE {legacy_name} IS NOT NULL
                """
            )

    for name, definition in {
        "rally_name": "TEXT",
        "stage_name": "TEXT",
        "distance_km": "REAL",
        "total_ascent": "REAL",
        "total_descent": "REAL",
        "min_altitude": "REAL",
        "max_altitude": "REAL",
        "elevation_gain": "REAL",
        "max_elevation": "REAL",
        "min_elevation": "REAL",
        "hairpin_count": "INTEGER",
        "hairpin_density": "REAL",
        "turn_count": "INTEGER",
        "turn_density": "REAL",
        "avg_curvature": "REAL",
        "max_curvature": "REAL",
        "p95_curvature": "REAL",
        "curvature_density": "REAL",
        "curvature_sum": "REAL",
        "straight_ratio": "REAL",
        "sign_changes_per_km": "REAL",
        "geometry_points": "INTEGER",
        "elevation_api_calls": "INTEGER",
        "cache_hit_rate": "REAL",
        "avg_grade": "REAL",
        "max_grade": "REAL",
        "avg_abs_grade": "REAL",
        "straight_percentage": "REAL",
        "curvy_percentage": "REAL",
        "stage_number": "INTEGER",
        "surface": "TEXT",
        "geometry_json": "TEXT",
        "analyzer_version": "TEXT",
        "kml_file": "TEXT",
        "processed_at": "TEXT",
        "analysis_version": "TEXT",
        "source_kml": "TEXT",
        "analyzed_at": "TEXT",
        "elevation_status": "TEXT DEFAULT 'unknown'",
        "geometry_status": "TEXT DEFAULT 'pending'",
        "geometry_hash": "TEXT",
        "validated_at": "TEXT",
        "is_active": "INTEGER DEFAULT 1",
    }.items():
        ensure_column(conn, "stage_geometry", name, definition)

    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_stage_geometry_active_stage
            ON stage_geometry(stage_id)
            WHERE is_active = 1
        """
    )

    if get_table_type(conn, "stages_metadata") == "view":
        conn.execute("DROP VIEW stages_metadata")

    conn.executescript(
        """
        CREATE VIEW IF NOT EXISTS stages_metadata AS
        SELECT
            stage_id,
            rally_id,
            stage_name,
            source_kml AS kml_file,
            surface,
            distance_km,
            curvature_sum,
            curvature_density,
            p95_curvature,
            max_curvature,
            avg_curvature,
            hairpin_count,
            hairpin_density,
            turn_count,
            turn_density,
            straight_ratio,
            sign_changes_per_km,
            total_ascent,
            total_descent,
            elevation_gain,
            max_grade,
            avg_abs_grade,
            max_elevation,
            min_elevation,
            geometry_points,
            elevation_api_calls,
            cache_hit_rate,
            straight_percentage,
            curvy_percentage,
            analysis_version AS analyzer_version,
            analyzed_at AS processed_at,
            geometry_json
        FROM stage_geometry
        WHERE is_active = 1;

        CREATE TRIGGER IF NOT EXISTS trg_stages_metadata_insert
        INSTEAD OF INSERT ON stages_metadata
        BEGIN
            INSERT OR REPLACE INTO stage_geometry (
                stage_id, rally_id, stage_name, source_kml, surface,
                distance_km, curvature_sum, curvature_density, p95_curvature,
                max_curvature, avg_curvature, hairpin_count, hairpin_density,
                turn_count, turn_density, straight_ratio, sign_changes_per_km,
                total_ascent, total_descent, elevation_gain, max_grade, avg_abs_grade,
                max_elevation, min_elevation, geometry_points,
                elevation_api_calls, cache_hit_rate, straight_percentage,
                curvy_percentage, analysis_version, analyzed_at, geometry_json,
                is_active
            ) VALUES (
                NEW.stage_id, NEW.rally_id, NEW.stage_name, NEW.kml_file, NEW.surface,
                NEW.distance_km, NEW.curvature_sum, NEW.curvature_density, NEW.p95_curvature,
                NEW.max_curvature, NEW.avg_curvature, NEW.hairpin_count, NEW.hairpin_density,
                NEW.turn_count, NEW.turn_density, NEW.straight_ratio, NEW.sign_changes_per_km,
                NEW.total_ascent, NEW.total_descent, NEW.elevation_gain, NEW.max_grade, NEW.avg_abs_grade,
                NEW.max_elevation, NEW.min_elevation, NEW.geometry_points,
                NEW.elevation_api_calls, NEW.cache_hit_rate, NEW.straight_percentage,
                NEW.curvy_percentage, NEW.analyzer_version, NEW.processed_at, NEW.geometry_json,
                1
            );
        END;

        CREATE TRIGGER IF NOT EXISTS trg_stages_metadata_update
        INSTEAD OF UPDATE ON stages_metadata
        BEGIN
            UPDATE stage_geometry
            SET
                rally_id = NEW.rally_id,
                stage_name = NEW.stage_name,
                source_kml = NEW.kml_file,
                surface = NEW.surface,
                distance_km = NEW.distance_km,
                curvature_sum = NEW.curvature_sum,
                curvature_density = NEW.curvature_density,
                p95_curvature = NEW.p95_curvature,
                max_curvature = NEW.max_curvature,
                avg_curvature = NEW.avg_curvature,
                hairpin_count = NEW.hairpin_count,
                hairpin_density = NEW.hairpin_density,
                turn_count = NEW.turn_count,
                turn_density = NEW.turn_density,
                straight_ratio = NEW.straight_ratio,
                sign_changes_per_km = NEW.sign_changes_per_km,
                total_ascent = NEW.total_ascent,
                total_descent = NEW.total_descent,
                elevation_gain = NEW.elevation_gain,
                max_grade = NEW.max_grade,
                avg_abs_grade = NEW.avg_abs_grade,
                max_elevation = NEW.max_elevation,
                min_elevation = NEW.min_elevation,
                geometry_points = NEW.geometry_points,
                elevation_api_calls = NEW.elevation_api_calls,
                cache_hit_rate = NEW.cache_hit_rate,
                straight_percentage = NEW.straight_percentage,
                curvy_percentage = NEW.curvy_percentage,
                analysis_version = NEW.analyzer_version,
                analyzed_at = NEW.processed_at,
                geometry_json = NEW.geometry_json
            WHERE stage_id = OLD.stage_id;
        END;

        CREATE TRIGGER IF NOT EXISTS trg_stages_metadata_delete
        INSTEAD OF DELETE ON stages_metadata
        BEGIN
            DELETE FROM stage_geometry WHERE stage_id = OLD.stage_id;
        END;
        """
    )


def _majority_value(values: Iterable[Any]) -> Optional[Any]:
    filtered = [value for value in values if value not in (None, "", "unknown")]
    return Counter(filtered).most_common(1)[0][0] if filtered else None


def _fetch_legacy_stage_results(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute("SELECT * FROM stage_results").fetchall()]


def populate_master_dimensions(conn: sqlite3.Connection) -> Dict[str, Any]:
    legacy_rows = _fetch_legacy_stage_results(conn)
    cursor = conn.cursor()
    driver_counts = Counter()
    grouped_names: Dict[str, List[str]] = defaultdict(list)
    rally_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    stage_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    alias_conflicts: List[Dict[str, Any]] = []

    for row in legacy_rows:
        raw_name = (row.get("driver_name") or "").strip()
        if raw_name:
            driver_counts[raw_name] += 1
        if row.get("rally_id"):
            rally_groups[str(row["rally_id"])].append(row)

        stage_id = row.get("stage_id") or build_stage_id(row.get("rally_id"), row.get("stage_number"))
        if stage_id:
            stage_groups[stage_id].append(row)

    for driver_name in driver_counts:
        key = normalize_name_key(driver_name)
        if key:
            grouped_names[key].append(driver_name)

    for normalized_key, aliases in grouped_names.items():
        names_with_counts = [(name, driver_counts[name]) for name in aliases]
        display_name = choose_display_name(names_with_counts)
        driver_id = build_driver_id(display_name)
        review_required = detect_manual_review(aliases)

        cursor.execute(
            """
            INSERT INTO drivers (driver_id, display_name, normalized_name_key, merge_review_status)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(driver_id) DO UPDATE SET
                display_name = excluded.display_name,
                normalized_name_key = excluded.normalized_name_key,
                merge_review_status = excluded.merge_review_status,
                updated_at = CURRENT_TIMESTAMP
            """,
            [driver_id, display_name, normalized_key, "review" if review_required else "auto"],
        )

        for alias_name, _count in names_with_counts:
            cursor.execute(
                """
                INSERT INTO driver_aliases (
                    driver_id, alias_name, normalized_name_key, is_primary, merge_status
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(alias_name) DO UPDATE SET
                    driver_id = excluded.driver_id,
                    normalized_name_key = excluded.normalized_name_key,
                    is_primary = excluded.is_primary,
                    merge_status = excluded.merge_status
                """,
                [
                    driver_id,
                    alias_name,
                    normalized_key,
                    1 if alias_name == display_name else 0,
                    "review" if review_required else "auto",
                ],
            )

        if len(aliases) > 1:
            alias_conflicts.append(
                {
                    "normalized_name_key": normalized_key,
                    "driver_id": driver_id,
                    "display_name": display_name,
                    "requires_manual_review": review_required,
                    "aliases": [
                        {"alias_name": alias_name, "count": driver_counts[alias_name]}
                        for alias_name in sorted(aliases)
                    ],
                }
            )

    for row in legacy_rows:
        stage_id = row.get("stage_id") or build_stage_id(row.get("rally_id"), row.get("stage_number"))
        raw_name = (row.get("driver_name") or "").strip()
        driver_id = build_driver_id(raw_name)
        cursor.execute(
            """
            UPDATE stage_results
            SET
                stage_id = COALESCE(stage_id, ?),
                raw_driver_name = COALESCE(raw_driver_name, driver_name),
                driver_id = ?,
                source_run_id = COALESCE(source_run_id, ?),
                status = COALESCE(status, 'FINISHED')
            WHERE result_id = ?
            """,
            [stage_id, driver_id, RESULTS_SOURCE_RUN_ID, row["result_id"]],
        )

    for rally_id, rows in rally_groups.items():
        rally_name = _majority_value([row.get("rally_name") for row in rows]) or rally_id
        surface = _majority_value([(row.get("surface") or "").strip().lower() for row in rows])
        cursor.execute(
            """
            INSERT INTO rallies (rally_id, rally_name, surface)
            VALUES (?, ?, ?)
            ON CONFLICT(rally_id) DO UPDATE SET
                rally_name = excluded.rally_name,
                surface = excluded.surface,
                updated_at = CURRENT_TIMESTAMP
            """,
            [rally_id, rally_name, surface],
        )

    geometry_rows = []
    if table_exists(conn, "stage_geometry"):
        geometry_rows = conn.execute(
            "SELECT stage_id, rally_id, stage_name, stage_number, surface, distance_km FROM stage_geometry"
        ).fetchall()

    geometry_stage_ids = set()
    for stage_id, rally_id, stage_name, stage_number, surface, distance_km in geometry_rows:
        geometry_stage_ids.add(stage_id)
        if stage_id not in stage_groups:
            stage_groups[stage_id] = [{
                "stage_id": stage_id,
                "rally_id": rally_id,
                "stage_name": stage_name,
                "stage_number": stage_number,
                "surface": surface,
                "stage_length_km": distance_km,
            }]

    for stage_id, rows in stage_groups.items():
        sample = rows[0]
        rally_id = str(sample.get("rally_id") or "").strip()
        stage_number = sample.get("stage_number")
        if stage_number is None:
            match = re.search(r"_ss(\d+)$", stage_id)
            stage_number = int(match.group(1)) if match else None
        stage_name = _majority_value([row.get("stage_name") for row in rows]) or stage_id
        length_km = _majority_value([row.get("stage_length_km") for row in rows])
        stage_surface = _majority_value([(row.get("surface") or "").strip().lower() for row in rows])
        rally_surface_row = cursor.execute(
            "SELECT surface FROM rallies WHERE rally_id = ?",
            [rally_id],
        ).fetchone()
        rally_surface = rally_surface_row[0] if rally_surface_row else None
        surface_override = int(bool(stage_surface and rally_surface and stage_surface != rally_surface))
        cursor.execute(
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
                length_km = excluded.length_km,
                match_status = excluded.match_status,
                updated_at = CURRENT_TIMESTAMP
            """,
            [
                stage_id,
                rally_id,
                stage_number,
                stage_name,
                stage_surface if surface_override else None,
                surface_override,
                length_km,
                "matched" if stage_id in geometry_stage_ids else "results_only",
            ],
        )

    conn.commit()
    return {
        "legacy_result_rows": len(legacy_rows),
        "drivers": len(grouped_names),
        "stages": len(stage_groups),
        "rallies": len(rally_groups),
        "alias_conflicts": alias_conflicts,
    }


def enrich_stage_geometry(conn: sqlite3.Connection) -> Dict[str, int]:
    cursor = conn.cursor()
    rows = cursor.execute("SELECT rowid, * FROM stage_geometry").fetchall()
    columns = [desc[0] for desc in cursor.description]
    updated = 0
    red_flagged = 0

    for row in rows:
        data = dict(zip(columns, row))
        stage_id = data.get("stage_id") or build_stage_id(data.get("rally_id"), data.get("stage_number"))
        stage_number = data.get("stage_number")
        if stage_number is None and stage_id:
            match = re.search(r"_ss(\d+)$", stage_id)
            stage_number = int(match.group(1)) if match else None

        stage_row = cursor.execute(
            "SELECT surface FROM stages WHERE stage_id = ?",
            [stage_id],
        ).fetchone() if stage_id else None
        effective_surface = data.get("surface") or (stage_row[0] if stage_row else None)

        distance_km = float(data.get("distance_km") or 0.0)
        total_ascent = float(data.get("total_ascent") or 0.0)
        total_descent = float(data.get("total_descent") or 0.0)
        max_grade = float(data.get("max_grade") or 0.0)
        has_elevation = any(
            float(data.get(field) or 0.0) != 0.0
            for field in ("total_ascent", "total_descent", "max_grade", "max_elevation", "min_elevation")
        )
        elevation_status = "available" if has_elevation else "missing"
        geometry_status = "validated"
        if distance_km > 3 and total_ascent == 0 and total_descent == 0 and max_grade == 0:
            elevation_status = "missing"
            geometry_status = "red_flag_missing_elevation"
            red_flagged += 1

        cursor.execute(
            """
            UPDATE stage_geometry
            SET
                stage_id = COALESCE(stage_id, ?),
                stage_number = COALESCE(stage_number, ?),
                surface = COALESCE(surface, ?),
                min_altitude = COALESCE(min_altitude, min_elevation),
                max_altitude = COALESCE(max_altitude, max_elevation),
                elevation_gain = COALESCE(
                    elevation_gain,
                    ABS(COALESCE(max_elevation, max_altitude, 0) - COALESCE(min_elevation, min_altitude, 0))
                ),
                analysis_version = COALESCE(analysis_version, ?, ?),
                source_kml = COALESCE(source_kml, kml_file),
                analyzed_at = COALESCE(analyzed_at, processed_at),
                elevation_status = ?,
                geometry_status = ?,
                geometry_hash = COALESCE(geometry_hash, ?),
                validated_at = CASE
                    WHEN ? = 'validated' THEN COALESCE(validated_at, analyzed_at, processed_at)
                    ELSE validated_at
                END
            WHERE rowid = ?
            """,
            [
                stage_id,
                stage_number,
                effective_surface,
                data.get("analysis_version"),
                GEOMETRY_SOURCE_RUN_ID,
                elevation_status,
                geometry_status,
                compute_geometry_hash(data),
                geometry_status,
                data["rowid"],
            ],
        )
        updated += 1

    conn.commit()
    return {"updated_rows": updated, "red_flagged_rows": red_flagged}


def write_alias_report(conflicts: List[Dict[str, Any]], report_path: Path) -> Path:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(":memory:") as conn:
        generated_at = conn.execute("SELECT CURRENT_TIMESTAMP").fetchone()[0]
    payload = {
        "generated_at": generated_at,
        "conflicts": conflicts,
    }
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path


def apply_master_schema(db_path: str, report_path: Optional[str] = None) -> Dict[str, Any]:
    db_file = Path(db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_file)
    try:
        ensure_results_master_tables(conn)
        ensure_stage_results_columns(conn)
        ensure_stage_geometry_table(conn)
        populate_stats = populate_master_dimensions(conn)
        geometry_stats = enrich_stage_geometry(conn)
        conn.execute(
            """
            INSERT OR REPLACE INTO schema_migrations (migration_name, applied_at)
            VALUES (?, CURRENT_TIMESTAMP)
            """,
            ["master_schema_v1"],
        )
        conn.commit()
    finally:
        conn.close()

    alias_report_path = None
    if report_path:
        alias_report_path = str(write_alias_report(populate_stats["alias_conflicts"], Path(report_path)))

    return {
        **populate_stats,
        **geometry_stats,
        "db_path": str(db_file),
        "alias_report_path": alias_report_path,
    }
