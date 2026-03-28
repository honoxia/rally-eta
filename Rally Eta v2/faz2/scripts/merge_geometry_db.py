"""
Merge an incoming geometry database into the master database.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.geometry_merge import merge_geometry_database


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge stage geometry into the master DB")
    parser.add_argument(
        "--master-db",
        default=str(PROJECT_ROOT / "data" / "raw" / "rally_results.db"),
        help="Path to the master results database",
    )
    parser.add_argument(
        "--incoming-db",
        required=True,
        help="Path to the incoming geometry database",
    )
    parser.add_argument(
        "--backup-dir",
        default=str(PROJECT_ROOT / "backups"),
        help="Directory for automatic pre/post merge backups",
    )
    parser.add_argument(
        "--report-dir",
        default=str(PROJECT_ROOT / "reports"),
        help="Directory for merge reports",
    )
    parser.add_argument(
        "--replace-existing",
        action="store_true",
        help="Clear current geometry before importing incoming rows",
    )
    args = parser.parse_args()

    summary = merge_geometry_database(
        master_db_path=args.master_db,
        incoming_db_path=args.incoming_db,
        backup_dir=args.backup_dir,
        report_dir=args.report_dir,
        replace_existing=args.replace_existing,
    )
    print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
