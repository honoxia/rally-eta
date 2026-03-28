"""
Compatibility Streamlit entrypoint.

The maintained desktop UI now lives under ``segment/app.py`` so both
source runs and portable builds use the same canonical workflow.
"""

from segment.app import *  # noqa: F401,F403
