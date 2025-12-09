"""Test launcher - debug için"""
import sys
import os
from pathlib import Path

print("="*60)
print("LAUNCHER DEBUG")
print("="*60)

print(f"sys.executable: {sys.executable}")
print(f"sys.frozen: {getattr(sys, 'frozen', False)}")
print(f"__file__: {__file__}")
print(f"Current dir: {os.getcwd()}")

if getattr(sys, 'frozen', False):
    print(f"sys._MEIPASS: {sys._MEIPASS}")

    exe_dir = Path(sys.executable).parent
    print(f"EXE dir: {exe_dir}")

    app_path = Path(sys._MEIPASS) / "app.py"
    print(f"App path: {app_path}")
    print(f"App exists: {app_path.exists()}")

    # List files in MEIPASS
    print("\nFiles in _MEIPASS:")
    for f in Path(sys._MEIPASS).iterdir():
        print(f"  {f.name}")

print("\nPress Enter to exit...")
input()
