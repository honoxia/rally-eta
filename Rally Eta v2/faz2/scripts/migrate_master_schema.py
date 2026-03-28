"""
Apply the canonical master schema to the active rally results database.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.master_schema import apply_master_schema


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate DB to canonical master schema")
    parser.add_argument(
        "--db-path",
        default=str(PROJECT_ROOT / "data" / "raw" / "rally_results.db"),
        help="Path to the SQLite results database",
    )
    parser.add_argument(
        "--report-path",
        default=str(PROJECT_ROOT / "reports" / "driver_alias_conflicts_20260327.json"),
        help="Path for the driver alias conflict report",
    )
    args = parser.parse_args()

    result = apply_master_schema(args.db_path, args.report_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
