# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('app.py', '.'), ('src', 'src'), ('config', 'config'), ('.streamlit', '.streamlit')]
binaries = []
hiddenimports = ['streamlit', 'streamlit.web.cli', 'streamlit.web.bootstrap', 'streamlit.runtime', 'streamlit.runtime.scriptrunner', 'lightgbm', 'sklearn', 'sklearn.utils._weight_vector', 'pandas', 'numpy', 'selenium', 'selenium.webdriver', 'selenium.webdriver.chrome', 'selenium.webdriver.chrome.service', 'selenium.webdriver.chrome.options', 'selenium.webdriver.common.by', 'selenium.webdriver.support.ui', 'selenium.webdriver.support.expected_conditions', 'webdriver_manager', 'webdriver_manager.chrome', 'bs4', 'requests', 'scipy', 'scipy.stats', 'scipy.sparse', 'scipy.sparse.linalg', 'scipy.sparse.csgraph', 'scipy.special', 'scipy._lib', 'scipy._lib.messagestream', 'scipy.spatial', 'scipy.spatial.distance', 'scipy.integrate', 'scipy.interpolate', 'scipy.optimize', 'sklearn', 'sklearn.ensemble', 'sklearn.ensemble._forest', 'sklearn.ensemble._gb_losses', 'sklearn.tree', 'sklearn.tree._tree', 'sklearn.neighbors', 'sklearn.neighbors._partition_nodes', 'sklearn.utils', 'sklearn.utils._cython_blas', 'sklearn.utils._weight_vector', 'sklearn.utils.murmurhash', 'sklearn.utils.lgamma', 'sklearn.utils.sparsefuncs_fast', 'sklearn.utils._logistic_sigmoid', 'sklearn.utils._random', 'sklearn.utils._seq_dataset', 'sklearn.utils._typedefs', 'sklearn.metrics', 'sklearn.metrics.pairwise', 'sklearn.metrics._pairwise_distances_reduction', 'sklearn.metrics._dist_metrics', 'sklearn.preprocessing', 'sklearn.preprocessing._csr_polynomial_expansion', 'sklearn.linear_model', 'sklearn.svm']
tmp_ret = collect_all('streamlit')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('altair')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('plotly')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('scipy')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('sklearn')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pyarrow')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('selenium')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['launcher.py'],
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
    name='RallyETA',
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
    icon=['assets\\icon.ico'],
)
