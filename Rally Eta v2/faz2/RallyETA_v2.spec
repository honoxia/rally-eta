# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = [
    ('D:\\claude\\Rally Eta v2\\faz2\\app.py', '.'),
    ('D:\\claude\\Rally Eta v2\\faz2\\src', 'src'),
    ('D:\\claude\\Rally Eta v2\\faz2\\segment', 'segment'),
    ('D:\\claude\\Rally Eta v2\\faz2\\.streamlit', '.streamlit'),
]
binaries = []

# Temel hidden imports
hiddenimports = [
    'streamlit', 'streamlit.web.cli', 'streamlit.web.bootstrap',
    'streamlit.runtime', 'streamlit.runtime.scriptrunner',
    'streamlit.runtime.scriptrunner.script_runner',
    'streamlit.runtime.caching', 'streamlit.runtime.legacy_caching',
    'streamlit.elements', 'streamlit.components',
    'pandas', 'numpy',
    'sklearn', 'sklearn.ensemble', 'sklearn.tree', 'sklearn.neighbors',
    'sklearn.inspection', 'sklearn.metrics', 'sklearn.model_selection',
    'sklearn.experimental', 'sklearn.experimental.enable_hist_gradient_boosting',
    'sklearn.ensemble._hist_gradient_boosting',
    'sklearn.ensemble._hist_gradient_boosting.gradient_boosting',
    'sklearn.preprocessing', 'sklearn.utils._cython_blas', 'sklearn.utils._weight_vector',
    'scipy', 'scipy.stats', 'scipy.sparse', 'scipy._lib', 'scipy._lib.messagestream',
    'scipy.special', 'scipy.linalg', 'scipy.integrate', 'scipy.interpolate',
    'scipy.spatial', 'scipy.spatial.transform',
    'lightgbm',
    'requests', 'bs4', 'selenium', 'selenium.webdriver', 'openpyxl',
    'altair', 'plotly', 'pyarrow', 'packaging', 'toml',
    'watchdog', 'click', 'gitpython', 'pydeck', 'pillow',
    'tornado', 'protobuf', 'blinker', 'cachetools', 'tenacity',
    'jinja2', 'jsonschema', 'narwhals', 'markupsafe',
]

# Streamlit ve bağımlılıklarını tam olarak topla
for pkg in ['streamlit', 'scipy', 'sklearn', 'altair', 'plotly', 'pyarrow', 'pydeck', 'lightgbm']:
    try:
        tmp_ret = collect_all(pkg)
        datas += tmp_ret[0]
        binaries += tmp_ret[1]
        hiddenimports += tmp_ret[2]
    except:
        pass

# Streamlit submodüllerini ekle
hiddenimports += collect_submodules('streamlit')
try:
    hiddenimports += collect_submodules('sklearn.ensemble._hist_gradient_boosting')
except:
    pass


a = Analysis(
    ['D:\\claude\\Rally Eta v2\\faz2\\launcher.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib.tests', 'IPython', 'jupyter'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='RallyETA_v2',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
