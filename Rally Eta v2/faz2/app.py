"""
Compatibility Streamlit entrypoint.

The maintained desktop UI now lives under ``segment/app.py`` so both
source runs and portable builds use the same canonical workflow.

The router is executed with runpy on every rerun rather than star-imported.
``from segment.app import *`` only renders once: Streamlit re-executes this file
on each interaction, but the module stays in sys.modules, so the second import
is a no-op and the page comes back blank.
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
