"""
Root Streamlit entry point.

Running from the workspace root avoids Streamlit's automatic multipage discovery
on segment/pages/, so the custom router remains in control.
"""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
SEGMENT_ROOT = ROOT / "segment"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if str(SEGMENT_ROOT) not in sys.path:
    sys.path.insert(0, str(SEGMENT_ROOT))


import segment.app  # noqa: F401
