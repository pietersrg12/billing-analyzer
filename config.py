"""
Konfigurasi aplikasi PLN Billing Analyzer.

Path resolution:
- BUNDLE_DIR  : folder berisi resource read-only (database.xlsb, model/best.pt).
                Saat dev = folder source. Saat di-bundle PyInstaller = sys._MEIPASS.
- APP_DATA_DIR: folder writable per user (%LOCALAPPDATA%\\PLN-Billing).
                Tempat menyimpan token SIMBA, foto cache, hasil Excel, log.
"""

import os
import sys


# =========================
# PATH RESOLUTION
# =========================

def _bundle_dir():
    """Folder resource read-only.

    PyInstaller --onefile  -> sys._MEIPASS (extract temp).
    PyInstaller --onedir   -> folder .exe berada (sys.executable parent).
    Dev mode (python main.py) -> folder source code.
    """
    if getattr(sys, "frozen", False):
        # Running di PyInstaller bundle
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return meipass
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _app_data_dir():
    """Folder writable per user untuk simpan data runtime.

    Windows: %LOCALAPPDATA%\\PLN-Billing
    Fallback: ~/PLN-Billing (jika LOCALAPPDATA tidak ada)
    Dev mode: folder source code (supaya pengembangan tidak kotor di AppData)
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    # Dev mode: pakai folder source agar tidak nyampur antara dev dan prod
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(*parts):
    """Path absolut ke resource read-only di dalam bundle."""
    return os.path.join(_bundle_dir(), *parts)


def user_path(*parts):
    """Path absolut ke file writable di folder data user."""
    return os.path.join(_app_data_dir(), *parts)


BUNDLE_DIR = _bundle_dir()
APP_DATA_DIR = _app_data_dir()


# =========================
# SIMBA API
# =========================
SIMBA_BASE_URL = "http://121.100.23.228:8030"
SIMBA_TOKEN_FILE = user_path("simba_token.json")

# =========================
# DOWNLOAD FOTO
# =========================
ENABLE_PHOTO_DOWNLOAD = True   # Set False untuk skip SIMBA auth + download foto + klasifikasi
                               # Note: hanya pelanggan dengan STATUS != "Normal" yang difoto
FOTO_DIR = user_path("foto")
JUMLAH_BULAN_FOTO = 3       # Jumlah bulan ke belakang yang difoto (termasuk BLTH target)
MAX_WORKERS_INFO = 20       # Paralel POST infopelanggan (server SIMBA bisa kena rate limit di >30)
MAX_WORKERS_DOWNLOAD = 25   # Paralel GET file foto (lebih dari 25 cenderung dapat connection refused)

# =========================
# OUTPUT
# =========================
HASIL_DIR = user_path("hasil")

# =========================
# DATABASE
# =========================
DB_FILE = resource_path("database.xlsb")

# =========================
# STAN BACA (raw meter reading, sebelum potongan jam-nyala)
# =========================
STAN_BACA_DB_FILE = resource_path("database_stand_baca.xlsb")
ENABLE_STAN_BACA = True   # auto-skip kalau file tidak ada di BUNDLE_DIR

# =========================
# RULE SETTINGS (threshold anomali, bisa diubah via UI)
# =========================
RULE_SETTINGS_FILE = user_path("rule_settings.json")

# =========================
# CLASSIFIER (YOLOv8)
# =========================
MODEL_PATH = resource_path("model", "best.pt")
ENABLE_CLASSIFIER = True

# =========================
# DIGIT READER (YOLOv8)
# =========================
# OCR digit dinonaktifkan permanen (keputusan user 2026-07: kolom STAND_OCR
# dihapus dari output). Kode core/reader.py & model tetap ada - set True
# kalau suatu saat mau dihidupkan lagi (kolom Excel-nya perlu ditambah ulang).
ENABLE_DIGIT_READER = False
DIGIT_MODEL_PATH = resource_path("model", "digit_detector.pt")

# =========================
# UI
# =========================
THEME_DARK = "darkly"
THEME_LIGHT = "cosmo"
