# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for PLN Billing Analyzer.

Build mode : --onedir (folder distribution)
Run        : pyarmor gen -O build_obf ... && pyinstaller pln_billing.spec --clean

PENTING - sumber yang di-build adalah build_obf/, BUKAN folder proyek.
build_obf/ berisi salinan teracak PyArmor; isinya cuma satu panggilan
__pyarmor__() berisi blob biner, sehingga PyInstaller TIDAK BISA melihat satu
pun import di dalamnya. Konsekuensinya seluruh dependensi - modul kita sendiri
maupun paket pihak ketiga - wajib didaftarkan manual di hiddenimports.
Menghapus satu nama dari daftar itu tidak membuat build gagal; aplikasinya yang
mati saat dijalankan.

Notes:
- ultralytics & torch butuh collect_all karena banyak dynamic import + data file.
- pyxlsb, openpyxl, ttkbootstrap, tkinterdnd2 perlu data file collection.
- model/best.pt di-bundle sebagai datas; database TIDAK (per unit,
  diunduh sendiri oleh tiap unit).
- Excludes: matplotlib, scipy, jupyter, dst untuk hemat ukuran.
"""

import glob as _glob
import os as _os

from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

# Folder hasil PyArmor. Wajib ada - build.bat menjalankan `pyarmor gen` sebelum
# PyInstaller. Kalau tidak ada, gagalkan di sini dengan pesan yang jelas
# daripada diam-diam mem-build sumber polos yang tidak teracak.
OBF_DIR = "build_obf"
if not _os.path.exists(_os.path.join(OBF_DIR, "main.py")):
    raise SystemExit(
        "build_obf/main.py tidak ada. Jalankan dulu:\n"
        "  pyarmor gen -O build_obf --recursive "
        "main.py ui.py ui_dialogs.py config.py core"
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

# Database TIDAK di-bundle. Isinya data pelanggan satu unit, dan menyertakannya
# berarti mengirim data itu ke setiap unit yang dikirimi installer - sekaligus
# menanam "seed" yang membuat unit lain dilaporkan sudah lengkap padahal
# databasenya milik orang lain. Tiap unit mengunduh datanya sendiri lewat
# tombol Cek Database.
datas += [
    ("model/best.pt", "model"),
    ("model/digit_detector.pt", "model"),
    ("model/display_detector.pt", "model"),
    ("assets/icon.ico", "assets"),
]

# =========================
# HIDDEN IMPORTS (defensive)
# =========================

hiddenimports += [
    # Pandas dependencies yang sering di-miss
    "pandas._libs.tslibs.timedeltas",
    "pandas._libs.tslibs.np_datetime",
    "pandas._libs.tslibs.nattype",
    # pandas._libs.skiplist sengaja dibuang: sudah tidak ada sejak pandas 2.x,
    # dan menyisakannya cuma memunculkan baris ERROR palsu di log build.
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
# IMPORT YANG TERSEMBUNYI DI BALIK OBFUSCATION
# =========================

# Modul kita sendiri. Tanpa ini PyInstaller tidak membundelnya sama sekali,
# karena satu-satunya yang terlihat di build_obf/main.py adalah blob PyArmor.
hiddenimports += ["config", "ui", "ui_dialogs", "core"]
hiddenimports += [
    "core." + _os.path.splitext(_os.path.basename(_f))[0]
    for _f in _glob.glob(_os.path.join(OBF_DIR, "core", "*.py"))
    if not _f.endswith("__init__.py")
]

# Paket pihak ketiga yang diimpor DARI DALAM kode teracak.
hiddenimports += [
    "pandas",
    "numpy",
    "requests",
    "requests.adapters",
    "urllib3.util.retry",
    "cv2",
    "PIL",
    "PIL.Image",
    "dateutil.relativedelta",
    "concurrent.futures",
    "queue",
    "tkinter",
    "tkinter.filedialog",
    "tkinter.messagebox",
    "tkinterdnd2",
    "ttkbootstrap",
    "ttkbootstrap.constants",
    "ttkbootstrap.scrolled",
    "ultralytics",
    "openpyxl.drawing.image",
    "openpyxl.formatting.rule",
    "openpyxl.styles",
    "openpyxl.utils",
    "openpyxl.worksheet.datavalidation",
    # Engine Excel dipanggil pandas lewat NAMA STRING (engine="xlsxwriter",
    # engine="pyxlsb"), jadi tidak akan pernah terlihat sebagai import -
    # bahkan tanpa obfuscation sekalipun.
    "xlsxwriter",
    "pyxlsb",
]

# Runtime PyArmor: paket ber-.pyd yang namanya mengandung angka acak, jadi
# dicari lewat glob supaya tidak perlu diperbarui tiap kali diacak ulang.
for _rt in _glob.glob(_os.path.join(OBF_DIR, "pyarmor_runtime_*")):
    _nama = _os.path.basename(_rt)
    hiddenimports.append(_nama)
    for _pyd in _glob.glob(_os.path.join(_rt, "*.pyd")):
        binaries += [(_pyd, _nama)]

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
    [_os.path.join(OBF_DIR, "main.py")],
    pathex=[OBF_DIR],
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
