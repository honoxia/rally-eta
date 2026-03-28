"""Helpers for creating sandbox-safe temporary directories in tests."""

from pathlib import Path
from uuid import uuid4


def make_workspace_temp(prefix: str = "rally_eta_") -> str:
    """Create a temporary directory inside the writable workspace."""
    temp_root = Path(__file__).resolve().parent.parent / ".tmp_testdata"
    temp_root.mkdir(parents=True, exist_ok=True)
    temp_dir = temp_root / f"{prefix}{uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=False)
    return str(temp_dir)
