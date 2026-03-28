"""
RallyETA v2.0 - Portable Build Script
Creates a standalone executable with all dependencies.

Usage:
    python build_portable.py
"""

import subprocess
import shutil
import os
import sys
from pathlib import Path
from datetime import datetime


def main():
    """Build portable RallyETA v2.0 executable."""

    print("=" * 60)
    print("RallyETA v2.0 - Portable Build Script")
    print("=" * 60)

    # Project root (faz2 folder)
    project_root = Path(__file__).parent
    os.chdir(project_root)

    print(f"\nWorking directory: {project_root}")

    # Check if root Streamlit config exists
    streamlit_dir = project_root / ".streamlit"
    if not streamlit_dir.exists():
        print("\nCreating .streamlit directory...")
        streamlit_dir.mkdir(parents=True)

        # Create config.toml
        config_file = streamlit_dir / "config.toml"
        with open(config_file, 'w', encoding='utf-8') as f:
            f.write("""[theme]
primaryColor = "#FF4B4B"
backgroundColor = "#FFFFFF"
secondaryBackgroundColor = "#F0F2F6"
textColor = "#262730"
font = "sans serif"

[server]
headless = true
port = 8501

[browser]
gatherUsageStats = false
""")
        print(f"OK - Created: {config_file}")

    # Check if assets directory exists (for icon)
    assets_dir = project_root / "assets"
    if not assets_dir.exists():
        print("\nCreating assets directory...")
        assets_dir.mkdir()
        print("INFO - Add icon.ico to assets/ for custom icon")

    # Clean previous dist and decide work path for PyInstaller
    print("\nCleaning previous builds...")
    build_dir = project_root / "build"
    dist_dir = project_root / "dist"
    work_path = build_dir

    if dist_dir.exists():
        shutil.rmtree(dist_dir)
        print(f"OK - Removed: {dist_dir}")

    if build_dir.exists():
        try:
            shutil.rmtree(build_dir)
            print(f"OK - Removed: {build_dir}")
        except PermissionError:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            work_path = project_root / f"build_{timestamp}"
            print(f"INFO - Default build folder locked, using alternate work path: {work_path}")

    # Run PyInstaller
    print("\nBuilding executable with PyInstaller...")
    print("   This may take 5-10 minutes...")

    result = subprocess.run(
        [
            sys.executable,
            '-m',
            'PyInstaller',
            'RallyETA_v2.spec',
            '--clean',
            '--workpath',
            str(work_path),
            '--distpath',
            str(dist_dir),
        ],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        print("\nERROR - Build failed!")
        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)
        return False

    print("OK - Executable built successfully!")

    # Portable package = dist/ klasoru (PyInstaller ciktisi zaten burada)
    print("\nSetting up portable package in dist/...")

    portable_dir = project_root / "dist"

    # EXE'nin olusup olusmadigini kontrol et
    exe_path = portable_dir / "RallyETA_v2.exe"
    if not exe_path.exists():
        print("ERROR - No executable found in dist/")
        return False

    print(f"OK - EXE found: {exe_path}")

    # Create data directories
    for subdir in ['data/raw', 'models', 'reports', 'logs']:
        (portable_dir / subdir).mkdir(parents=True, exist_ok=True)

    print(f"OK - Created data directories")

    # Copy database if exists
    local_db = project_root / "data" / "raw" / "rally_results.db"
    parent_db = project_root.parent / "data" / "raw" / "rally_results.db"
    source_db = local_db if local_db.exists() else (parent_db if parent_db.exists() else None)
    if source_db:
        dest_db = portable_dir / "data" / "raw" / "rally_results.db"
        if source_db != dest_db:  # Ayni dosya degilse kopyala
            shutil.copy2(source_db, dest_db)
            print(f"OK - Copied database: {source_db}")
        else:
            print(f"OK - Database already in place: {dest_db}")

    # Create README for portable
    readme_content = f"""# RallyETA v2.0 Portable

## Quick Start

1. **First Run**: Double-click `RallyETA_v2.exe`
   - Web interface will open in your browser (http://localhost:8501)
   - If database doesn't exist, create one or copy from existing installation

2. **Database**:
   - Place your database at: `data/raw/rally_results.db`
   - Or use the Settings page to configure database path

## Folder Structure

```
RallyETA_Portable_v2.0/
├── RallyETA_v2.exe          # Main executable
├── data/
│   └── raw/                 # Database folder
│       └── rally_results.db
├── models/                  # Trained models (optional)
├── reports/                 # Prediction outputs
└── logs/                    # Application logs
```

## Features

- **3-Stage Prediction Pipeline**:
  1. Baseline Calculator (historical performance, momentum, surface)
  2. Geometric Correction (KML-based, optional)
  3. Confidence Scorer (0-100 points)

- **Confidence Levels**:
  - HIGH (75+): Reliable prediction
  - MEDIUM (55-74): Good estimate
  - LOW (<55): Limited data

## Troubleshooting

### Port 8501 already in use
Close the program and reopen. The launcher auto-cleans stuck processes.

### Database not found
Copy your rally_results.db to data/raw/ folder.

---

**Version**: 2.0.0
**Build Date**: {datetime.now().strftime("%Y-%m-%d")}
"""

    with open(portable_dir / "README.txt", 'w', encoding='utf-8') as f:
        f.write(readme_content)

    print(f"OK - Created: README.txt")

    # Calculate size
    total_size = sum(
        f.stat().st_size for f in portable_dir.rglob('*') if f.is_file()
    ) / (1024 * 1024)  # MB

    print(f"\n{'=' * 60}")
    print(f"SUCCESS - Portable package created!")
    print(f"{'=' * 60}")
    print(f"\nLocation: {portable_dir}")
    print(f"Size: {total_size:.1f} MB")
    print(f"\nContents:")
    print(f"   - RallyETA_v2.exe")
    print(f"   - data/ (database)")
    print(f"   - models/ (trained models)")
    print(f"   - reports/ (predictions)")
    print(f"   - README.txt")

    print(f"\nBuild complete! You can now:")
    print(f"   1. Double-click RallyETA_v2.exe to start")
    print(f"   2. Compress folder to ZIP for distribution")
    print(f"   3. Share with users")

    return True


if __name__ == "__main__":
    success = main()
    if not success and sys.stdin.isatty():
        input("\nPress Enter to exit...")
