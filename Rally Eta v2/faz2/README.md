# Rally Result Prediction

Stage result and notional time prediction system.

This folder contains the active Rally Result Prediction application workspace.

Rally Result Prediction is a desktop-oriented Streamlit application for rally stage result and notional time support during red-flag scenarios. It combines the existing ML-based prediction flow with operational tools used on rally day.

## Current Scope

- ML-based stage prediction workflow
- Live prediction screen for red-flag scenarios
- In-app `Manuel Hesap` module for steward-side manual calculation
- TOSFED scraping and database tools
- KML and stage geometry management
- Training, settings, reports, and portable Windows build workflow

## Live Race Dashboard

The default Operation Mode view is `Canlı Yarış`. Enter a TOSFED race URL once
and select `Yarışı Takip Et`. While this page stays open, the app checks every
60 seconds and recalculates all stages and all entrants when results change.
Choose an `Etap` to see its actual times, km-based estimates, percentage-based
estimates and baseline estimates in one table. `Şimdi Yenile` checks immediately;
the toggle pauses automatic updates. CSV export contains the selected stage.

Unstarted stages and waiting entrants remain visible. Missing references or
same-class finishes are shown as waiting for data, never as zero times. Baseline
estimates are not labeled ML. These are rolling estimates using currently known
results, not frozen pre-stage predictions. Updates do not save official decisions
or prediction-log rows. The existing `Tek Pilot / Karar` view remains available
for explicitly recording an official choice. If a refresh fails, the last
successful table stays visible with a warning.

## Manual Calculator

The `Manuel Hesap` module is designed for fast in-app fallback calculations without opening Excel.

- Works with raw class input entered by the user
- Does not auto-normalize classes inside the manual module
- Does not create general-best fallback conversions
- Calculates two methods side by side:
  - `Km Bazli`
  - `Yuzde Bazli`
- Can show detailed calculation steps for steward review

## Folder Layout

```text
faz2/
|-- segment/               Custom Streamlit pages and shared UI
|-- src/                   Prediction, data, and domain logic
|-- tests/                 Unit and integration tests
|-- data/                  Runtime database and generated data
|-- models/                Local model artifacts
|-- reports/               Prediction outputs and exports
|-- kml-kmz/               KML / KMZ files used in stage workflows
|-- build_portable.py      Portable EXE build script
|-- launcher.py            PyInstaller launcher entrypoint
|-- streamlit_app.py       Local Streamlit entrypoint
`-- RallyETA_v2.spec       PyInstaller spec
```

## Run Locally

```bash
cd "Rally Eta v2/faz2"
python -m venv .venv
.venv\Scripts\activate
pip install -r ..\requirements.txt
streamlit run streamlit_app.py
```

Then open `http://localhost:8501`.

## Build Portable EXE

```bash
cd "Rally Eta v2/faz2"
python build_portable.py
```

Build output:

- `dist/RallyETA_v2.exe`
- `dist/README.txt`
- `dist/data/`
- `dist/models/`
- `dist/reports/`
- `dist/logs/`

For distribution, send the entire `dist/` folder, not only the `.exe`.

## Tests

```bash
cd "Rally Eta v2/faz2"
python -m unittest discover -s tests -v
```

Recommended targeted checks:

```bash
python -m unittest tests.test_manual_calculator -v
python -m unittest tests.test_build_runtime -v
```

## Notes

- The portable build is Windows-oriented.
- The app starts a local Streamlit server on port `8501`.
- Legacy v1.2 is preserved separately at the repository tag `v1.2.0`.
