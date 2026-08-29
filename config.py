"""
Konfigurasi aplikasi PLN Billing Analyzer.

Path resolution:
- BUNDLE_DIR  : folder berisi resource read-only (database.xlsb, model/best.pt).
                Saat dev = folder source. Saat di-bundle PyInstaller = sys._MEIPASS.
- APP_DATA_DIR: folder writable per user (folder .exe kalau writable, kalau
                tidak %LOCALAPPDATA%\\PLN-Billing).
                Tempat menyimpan token SIMBA/billing, foto cache, hasil
                Excel, database hasil update otomatis, dan log.
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


def _is_writable(folder):
    """True kalau folder benar-benar bisa ditulisi (bukan sekadar ada)."""
    try:
        os.makedirs(folder, exist_ok=True)
        probe = os.path.join(folder, ".write_test")
        with open(probe, "w") as f:
            f.write("x")
        os.remove(probe)
        return True
    except OSError:
        return False


def _app_data_dir():
    """Folder writable per user untuk simpan data runtime.

    Dev mode: folder source code (supaya pengembangan tidak kotor di AppData).
    Frozen  : folder .exe kalau masih writable (instalasi portable - perilaku
              lama, supaya token/foto/hasil instalasi yang sudah ada tidak
              tiba-tiba pindah tempat), kalau tidak jatuh ke
              %LOCALAPPDATA%\\PLN-Billing.

    Fallback ke LOCALAPPDATA ini wajib sejak app mulai MENULIS database
    (fitur update database otomatis): build yang terpasang di Program Files
    tidak boleh gagal cuma karena foldernya read-only.
    """
    if not getattr(sys, "frozen", False):
        # Dev mode: pakai folder source agar tidak nyampur antara dev dan prod
        return os.path.dirname(os.path.abspath(__file__))

    exe_dir = os.path.dirname(sys.executable)
    if _is_writable(exe_dir):
        return exe_dir

    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "PLN-Billing")


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
# Dua lokasi per database:
# - BUNDLED (.xlsb) : resource read-only yang ikut di-ship, jadi seed awal.
# - USER (.xlsx)    : hasil update otomatis, ditulis app, dipakai kalau ada.
#
# Sisi user WAJIB .xlsx: pyxlsb read-only, Python tidak bisa menulis .xlsb
# sama sekali. Pembacanya (loader._read_excel_auto) sudah menangani kedua
# ekstensi, jadi peralihan ini transparan buat pipeline.
DB_FILE_BUNDLED = resource_path("database.xlsb")
DB_FILE_USER = user_path("database.xlsx")

STAN_BACA_DB_FILE_BUNDLED = resource_path("database_stand_baca.xlsb")
STAN_BACA_DB_FILE_USER = user_path("database_stand_baca.xlsx")


def db_path():
    """Path database rekening yang berlaku sekarang.

    Sengaja fungsi, bukan konstanta: setelah update database berhasil, file
    user baru muncul di tengah sesi dan pipeline harus langsung memakainya
    tanpa perlu restart aplikasi.
    """
    return DB_FILE_USER if os.path.exists(DB_FILE_USER) else DB_FILE_BUNDLED


def stanbaca_db_path():
    """Path database stan baca yang berlaku sekarang (lihat db_path())."""
    if os.path.exists(STAN_BACA_DB_FILE_USER):
        return STAN_BACA_DB_FILE_USER
    return STAN_BACA_DB_FILE_BUNDLED


# Alias lama: dipakai pln_billing.spec & selftest yang memang mengecek resource
# bundled. Jangan dipakai untuk baca database saat runtime - pakai db_path().
DB_FILE = DB_FILE_BUNDLED

# =========================
# STAN BACA (raw meter reading, sebelum potongan jam-nyala)
# =========================
STAN_BACA_DB_FILE = STAN_BACA_DB_FILE_BUNDLED
ENABLE_STAN_BACA = True   # auto-skip kalau file tidak ada

# =========================
# UPDATE DATABASE OTOMATIS
# =========================
# Portal billing = sumber database rekening. Host sama tapi PORT BEDA untuk
# auth dan API (sesuai capture di folder "login/" dan "download data base/").
BILLING_AUTH_URL = "http://10.68.35.109:8020"
BILLING_API_URL = "http://10.68.35.109:7004"
BILLING_TOKEN_FILE = user_path("billing_token.json")

# Export billing minta `size` eksplisit (page 0 + size = ambil semua sekaligus).
# Capture aslinya pakai 14663, yaitu jumlah baris persis; di sini dipakai angka
# aman yang jauh di atas jumlah pelanggan satu ULP.
BILLING_EXPORT_SIZE = 100000

# Database stan baca ditarik per kategori kode baca, satu request masing-masing,
# lalu digabung. Server tidak menyediakan opsi "SEMUA".
KODE_BACA_KATEGORI = ("NORMAL", "GANGGUAN BACA", "GANGGUAN METER")

ENABLE_DB_DOWNLOAD = True   # False = tombol "Cek Database" tidak ditampilkan

# Unduhan file input DLPD. Butuh DUA export: DLPD (semua kolom yang dipakai
# aplikasi) dan DPM (hanya untuk kolom kelainan_bc_meter, yang tidak ada di
# export DLPD), lalu digabung lewat lookup idpel.
UNDUH_SETTINGS_FILE = user_path("unduh_settings.json")
ENABLE_UNDUH_DLPD = True

UNDUHAN_DIR = user_path("unduhan")      # arsip file mentah hasil download
DB_BACKUP_DIR = user_path("db_backup")  # salinan database sebelum ditimpa

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
# IDENTITAS APLIKASI
# =========================
# Dikumpulkan di sini supaya teks kredit tidak tercecer di banyak tempat.
APP_NAMA = "PLN Billing Analyzer"
APP_VERSI = "2.1"
APP_TEMPAT = "Dompu"
APP_TAHUN = "2026"
APP_PEMBUAT = "PMPS"

# =========================
# UI
# =========================
THEME_DARK = "darkly"
THEME_LIGHT = "cosmo"
