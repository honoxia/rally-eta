"""
Merge an incoming rally results database into the master database.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.results_merge import merge_results_database


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge stage_results from an incoming DB into the master DB")
    parser.add_argument(
        "--master-db",
        default=str(PROJECT_ROOT / "data" / "raw" / "rally_results.db"),
        help="Path to the master results database",
    )
    parser.add_argument(
        "--incoming-db",
        required=True,
        help="Path to the incoming results database",
    )
    parser.add_argument(
        "--backup-dir",
        default=str(PROJECT_ROOT / "backups"),
        help="Directory for automatic pre/post merge backups",
    )
    parser.add_argument(
        "--report-dir",
        default=str(PROJECT_ROOT / "reports"),
        help="Directory for merge reports and alias reports",
    )
    args = parser.parse_args()

    summary = merge_results_database(
        master_db_path=args.master_db,
        incoming_db_path=args.incoming_db,
        backup_dir=args.backup_dir,
        report_dir=args.report_dir,
    )
    print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
