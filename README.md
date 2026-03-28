# Rally ETA v2

Rally ETA is a desktop-oriented rally stage ETA and notional time support system for red-flag scenarios.

The current `main` branch represents the v2 application line. The legacy v1.2 line is preserved as tag `v1.2.0`.

## What Is Included in v2

- Streamlit-based segmented application flow
- ML-based prediction workflow
- Live rally prediction screen
- In-app `Manuel Hesap` module for fast steward-side manual calculation
- TOSFED scraping and database tools
- KML and stage geometry management
- Training, settings, reports, and portable Windows build workflow

## Main Application Location

The actively maintained v2 application source lives in:

- `Rally Eta v2/faz2`

If you want the app workspace README directly, see:

- `Rally Eta v2/faz2/README.md`

## Quick Start

### Run the App Locally

```bash
cd "Rally Eta v2/faz2"
python -m venv .venv
.venv\Scripts\activate
pip install -r ..\requirements.txt
streamlit run streamlit_app.py
```

Then open `http://localhost:8501`.

### Build Portable EXE

```bash
cd "Rally Eta v2/faz2"
python build_portable.py
```

Expected build output:

- `Rally Eta v2/faz2/dist/RallyETA_v2.exe`
- `Rally Eta v2/faz2/dist/README.txt`
- `Rally Eta v2/faz2/dist/data/`
- `Rally Eta v2/faz2/dist/models/`
- `Rally Eta v2/faz2/dist/reports/`
- `Rally Eta v2/faz2/dist/logs/`

Important: for distribution, ship the whole `dist/` folder, not only the `.exe`.

## Manual Calculator

The new `Manuel Hesap` module is built for quick in-app calculations when a steward wants a manual estimate without opening Excel.

- Uses raw class input entered by the user
- Does not auto-normalize classes inside the manual module
- Does not create general-best fallback conversions
- Produces two results side by side:
  - `Km Bazli`
  - `Yuzde Bazli`
- Can show detailed calculation steps on demand

## Repository Layout

```text
.
|-- Rally Eta v2/faz2/        Active v2 application workspace
|-- Rally Eta v2/             Supporting v2 documentation and scripts
|-- README_v1_2.md            Legacy v1.2 README snapshot
|-- src/                      Legacy v1.x source tree kept for history
|-- tests/                    Legacy v1.x tests kept for history
`-- data/                     Legacy root-level data area
```

## Testing

```bash
cd "Rally Eta v2/faz2"
python -m unittest discover -s tests -v
```

Useful targeted checks:

```bash
python -m unittest tests.test_manual_calculator -v
python -m unittest tests.test_build_runtime -v
```

## Versioning

- Current app line: v2
- Legacy tag: `v1.2.0`
- Portable build output is not the source of truth; the repository stores source code and build tooling

## License

MIT
