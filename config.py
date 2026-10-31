"""
Konfigurasi aplikasi SIMBA (Sistem Monitoring Baca Meter).

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
# Legacy: token SIMBA tidak lagi disimpan (tiap sesi di-logout). Path ini
# hanya dipakai untuk menghapus sisa file dari versi lama.
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
# Database dipisah PER UNIT: database_44320.xlsx, database_44210.xlsx, dst.
#
# Bukan sekadar kerapian. Isinya cuma IDPEL tanpa kolom unit, dan check_coverage
# hanya memeriksa BULAN - jadi satu file bersama membuat database unit lain
# terbaca sebagai "sudah lengkap", tombol Update tidak pernah muncul, dan
# analisisnya menjadikan semua pelanggan "DATA BARU" tanpa gejala apa pun.
# Nama file yang membawa kode unit membuat salah pasang jadi mustahil.
#
# Ekstensi .xlsx karena pyxlsb read-only (tidak ada pustaka Python yang bisa
# MENULIS .xlsb); .xlsb tetap dibaca supaya file lama yang di-rename ikut jalan.
DB_PREFIX = "database"
STAN_BACA_PREFIX = "database_stand_baca"


def _cari_db(prefix, unitup):
    """Path database unit tsb. Return None kalau belum ada.

    Sengaja TIDAK pernah jatuh ke nama tanpa akhiran unit: justru itu yang bisa
    memasangkan data satu unit ke unit lain tanpa ketahuan.
    """
    if not unitup:
        return None
    for ext in (".xlsx", ".xlsb"):
        p = user_path(f"{prefix}_{unitup}{ext}")
        if os.path.exists(p):
            return p
    return None


def db_path(unitup):
    """Database rekening milik unit tsb, atau None kalau belum diunduh."""
    return _cari_db(DB_PREFIX, unitup)


def stanbaca_db_path(unitup):
    """Database stan baca milik unit tsb, atau None kalau belum diunduh."""
    return _cari_db(STAN_BACA_PREFIX, unitup)


def db_path_baru(unitup):
    """Path tujuan penulisan database rekening unit tsb (selalu .xlsx)."""
    return user_path(f"{DB_PREFIX}_{unitup}.xlsx")


def stanbaca_db_path_baru(unitup):
    """Path tujuan penulisan database stan baca unit tsb (selalu .xlsx)."""
    return user_path(f"{STAN_BACA_PREFIX}_{unitup}.xlsx")


# =========================
# STAN BACA (raw meter reading, sebelum potongan jam-nyala)
# =========================
ENABLE_STAN_BACA = True   # auto-skip kalau file unit tsb belum ada

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

# DLPD dan DPM ditarik bersamaan (2 thread) karena keduanya independen dan
# waktunya didominasi generate di server AP2T, bukan transfer. Set False untuk
# kembali ke berurutan kalau server ternyata mengantre export per token.
ENABLE_UNDUH_PARALEL = True

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
# Ini nama TAMPILAN saja. Nama internal (PLN-Billing.exe, folder data
# PLN-Billing, AppId installer) sengaja tetap supaya instalasi lama ter-upgrade
# tanpa kehilangan token, foto, dan database.
APP_NAMA = "SIMBA"
APP_SUBJUDUL = "Sistem Monitoring Baca Meter"
APP_VERSI = "2.7"
APP_TEMPAT = "Dompu"
APP_TAHUN = "2026"
APP_PEMBUAT = "PMPS, RIP & FDP"

# =========================
# UI
# =========================
THEME_DARK = "darkly"
THEME_LIGHT = "cosmo"

# Logo transparan, disiapkan sekali oleh tools/siapkan_logo.py dari logo_baru/.
LOGO_PATH = resource_path("assets", "logo_simba.png")
LOGO_EMBLEM_PATH = resource_path("assets", "logo_emblem.png")
