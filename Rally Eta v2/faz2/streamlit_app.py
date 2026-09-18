"""
Root Streamlit entry point.

Running from the workspace root avoids Streamlit's automatic multipage discovery
on segment/pages/, so the custom router remains in control.

The router is executed with runpy on every rerun rather than imported. A plain
`import segment.app` only renders once: Streamlit re-executes this file on each
interaction, but the module stays in sys.modules, so the second import is a
no-op and the page comes back blank. runpy re-runs the file every time, which is
exactly what `streamlit run segment/app.py` does, including __name__.
"""

from pathlib import Path
import runpy
import sys


ROOT = Path(__file__).resolve().parent
SEGMENT_ROOT = ROOT / "segment"
ROUTER_PATH = SEGMENT_ROOT / "app.py"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if str(SEGMENT_ROOT) not in sys.path:
    sys.path.insert(0, str(SEGMENT_ROOT))


runpy.run_path(str(ROUTER_PATH), run_name="__main__")
