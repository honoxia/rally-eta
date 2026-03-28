"""Workspace-local Python startup customizations for sandboxed test runs."""

import os
import tempfile
from pathlib import Path


_workspace_temp = Path(__file__).resolve().parent / ".tmp_runtime"
_workspace_temp.mkdir(parents=True, exist_ok=True)

# Keep tempfile within the writable workspace so sqlite/tempfile calls work in sandbox.
os.environ["TEMP"] = str(_workspace_temp)
os.environ["TMP"] = str(_workspace_temp)
tempfile.tempdir = str(_workspace_temp)
