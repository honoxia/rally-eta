import os
from pathlib import Path

from src.data.master_schema import apply_master_schema


BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = os.path.join(BASE_DIR, "data", "raw", "rally_results.db")


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    result = apply_master_schema(DB_PATH)
    print(f"Database ready: {result['db_path']}")


if __name__ == "__main__":
    init_db()
