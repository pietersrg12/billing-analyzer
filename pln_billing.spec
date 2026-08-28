# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for PLN Billing Analyzer.

Build mode : --onedir (folder distribution)
Run        : pyinstaller pln_billing.spec --clean --noconfirm

Notes:
- ultralytics & torch butuh collect_all karena banyak dynamic import + data file.
- pyxlsb, openpyxl, ttkbootstrap, tkinterdnd2 perlu data file collection.
- database.xlsb & model/best.pt di-bundle sebagai datas.
- Excludes: matplotlib, scipy, jupyter, dst untuk hemat ukuran.
"""

from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)


# =========================
# COLLECT HEAVY PACKAGES
# =========================

datas = []
binaries = []
hiddenimports = []

for pkg in ("ultralytics", "torch", "torchvision"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

# tkinterdnd2 ships TCL files yang harus ikut
datas += collect_data_files("tkinterdnd2")

# ttkbootstrap punya theme JSON
datas += collect_data_files("ttkbootstrap")

# openpyxl punya constants/schema XML
datas += collect_data_files("openpyxl")

# pyxlsb data files (jika ada)
datas += collect_data_files("pyxlsb")

# Pandas dynamic libs (numpy MKL/OpenBLAS dll)
binaries += collect_dynamic_libs("numpy")

# =========================
# APP RESOURCES
# =========================

datas += [
    ("database.xlsb", "."),
    ("model/best.pt", "model"),
    ("model/digit_detector.pt", "model"),
    ("model/display_detector.pt", "model"),
    ("assets/icon.ico", "assets"),
]

# database_stand_baca.xlsb bersifat opsional (ENABLE_STAN_BACA di config.py
# di-skip gracefully kalau file tidak ada saat runtime) - bundle hanya kalau
# sudah disediakan di root project supaya build tidak gagal saat file belum ada.
import os as _os
if _os.path.exists("database_stand_baca.xlsb"):
    datas += [("database_stand_baca.xlsb", ".")]

# =========================
# HIDDEN IMPORTS (defensive)
# =========================

hiddenimports += [
    # Pandas dependencies yang sering di-miss
    "pandas._libs.tslibs.timedeltas",
    "pandas._libs.tslibs.np_datetime",
    "pandas._libs.tslibs.nattype",
    "pandas._libs.skiplist",
    # Excel engines
    "pyxlsb",
    "openpyxl",
    "openpyxl.cell._writer",
    # PIL plugins yang kadang di-miss saat freeze
    "PIL._tkinter_finder",
    # ultralytics task modules (lazy import)
    "ultralytics.models.yolo.classify",
    "ultralytics.models.yolo.detect",
    "ultralytics.nn.tasks",
    "ultralytics.utils",
    # tkinterdnd2 internal
    "tkinterdnd2",
]

hiddenimports += collect_submodules("ultralytics")

# =========================
# EXCLUDES (hemat ukuran)
# =========================

excludes = [
    "matplotlib",
    "scipy",
    "IPython",
    "jupyter",
    "notebook",
    "ipykernel",
    "pytest",
    "tornado",
    "sphinx",
    "pydoc_data",
    "tensorboard",
    "onnx",
    "onnxruntime",
    "torchaudio",
    "pandas.tests",
    "numpy.tests",
    "PIL.ImageQt",
]


# =========================
# BUILD
# =========================

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PLN-Billing",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon="assets/icon.ico",
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PLN-Billing",
)
