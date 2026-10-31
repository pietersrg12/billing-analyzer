"""
Pipeline orchestrator.

Flow:
  LOAD -> PREPARE -> ANALYZE -> ACMT AUTH -> INFO -> DOWNLOAD -> EXPORT -> FORMAT
"""

import glob
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import pandas as pd

from config import (
    BILLING_API_URL,
    BILLING_AUTH_URL,
    BILLING_EXPORT_SIZE,
    BILLING_TOKEN_FILE,
    DIGIT_MODEL_PATH,
    ENABLE_CLASSIFIER,
    ENABLE_DIGIT_READER,
    ENABLE_PHOTO_DOWNLOAD,
    ENABLE_STAN_BACA,
    ENABLE_UNDUH_PARALEL,
    FOTO_DIR,
    HASIL_DIR,
    JUMLAH_BULAN_FOTO,
    MAX_WORKERS_DOWNLOAD,
    MAX_WORKERS_INFO,
    MODEL_PATH,
    KODE_BACA_KATEGORI,
    SIMBA_BASE_URL,
    SIMBA_TOKEN_FILE,
    UNDUHAN_DIR,
    db_path,
    stanbaca_db_path,
)
from core import settings, verification
from core.analyzer import (
    apply_analysis,
    compute_stanbaca_comparison,
    prepare,
    tandai_tagih_ulang_pasca_nol,
)
from core.cabut_pasang import compute_cabut_pasang, ringkasan as ringkasan_cabut_pasang
from core.classifier import classify_all, is_available as classifier_available
from core.excel import export_excel, format_excel
from core.koreksi import tambah_saran_koreksi
from core.billing_client import BillingAuthError, BillingClient
from core.db_updater import (
    DbUpdateError,
    append_rekening,
    append_stanbaca,
    parse_billing_export,
    parse_kode_baca_export,
)
from core.dlpd_merge import gabung_dlpd_dpm
from core import pagar_terkunci as pt
from core.pagar_terkunci import parse_acmt_lengkap
from core.loader import (
    _read_excel_auto,
    load_data,
    load_stanbaca_data,
    read_unitup,
)
from core.photo import download_photos
from core.reader import is_available as reader_available
from core.reader import read_meter_batch
from core.simba_client import SimbaAuthError, SimbaClient, SimbaError


def unit_dari_token():
    """Unit dari token billing tersimpan. None kalau belum ada.

    Dipakai saat belum ada file DPM yang dipilih (mis. tombol Cek Database).
    ACMT tidak ikut dibaca: sesinya selalu di-logout sehingga tidak ada token
    yang tersimpan - unit dari login ACMT sudah dicatat lewat
    settings.set_unit_aktif().
    """
    try:
        with open(BILLING_TOKEN_FILE, "r", encoding="utf-8") as f:
            u = json.load(f).get("unitup")
        if u:
            return str(u).strip()
    except (OSError, ValueError, AttributeError):
        pass
    return None


def _catat_unit_login(unit, sumber, log=None):
    """Jadikan unit hasil login sebagai unit aktif.

    Kalau berbeda dari unit yang tersimpan, itu dicatat - bukan diganti
    diam-diam. Beda unit antara ACMT dan portal billing adalah keanehan yang
    patut dilihat orang, bukan diselesaikan tanpa jejak.
    """
    if not unit:
        return
    lama = settings.get_unit_aktif()
    if lama and lama != unit:
        if log:
            log(f"Unit aktif berubah: {lama} -> {unit} (dari login {sumber})")
    settings.set_unit_aktif(unit)


def unit_aktif():
    """Unit yang sedang dikerjakan, untuk jalur yang tidak punya file DPM.

    Urutannya: setelan eksplisit -> token tersimpan -> None. Setelan menang
    karena itu pilihan sadar user; token cuma sisa login terakhir yang bisa
    saja milik orang lain di komputer yang sama.
    """
    return settings.get_unit_aktif() or unit_dari_token()


def unit_untuk_dpm(dpm_path, log=None):
    """Unit yang berlaku untuk satu file DPM/DLPD.

    File itu sendiri yang paling berhak menentukan miliknya siapa - lebih tepat
    daripada unit token, yang bisa saja milik user lain di komputer yang sama.
    Kalau filenya tidak menyatakan satu unit yang tunggal, baru jatuh ke token,
    dan itu dicatat di log supaya tidak terjadi diam-diam.
    """
    unit = read_unitup(dpm_path)
    if unit:
        return unit
    unit = unit_dari_token()
    if log:
        if unit:
            log(f"File tidak menyatakan satu unit; memakai unit token: {unit}")
        else:
            log("Unit tidak diketahui - database dianggap belum ada")
    return unit


# Sesi ACMT di-cache di memori selama aplikasi terbuka: satu login dipakai
# ulang oleh semua operasi (Unduh/Jalankan/Update), bukan login tiap tombol.
# Login ulang hanya terjadi kalau server menolak token (via `_kerja_simba`),
# dan logout dilakukan SEKALI saat aplikasi ditutup (`logout_sesi_simba`,
# dipanggil UI di handler close). Token/token_info tetap hanya di memori.
_sesi_simba = None
_sesi_simba_lock = threading.Lock()


def _get_simba_client(progress_callback, login_event, credentials_holder):
    """Kembalikan client ACMT yang masih login, atau login baru lewat dialog GUI.

    Di teks UI/log server ini disebut ACMT (SIMBA sudah jadi nama aplikasi);
    identifier kodenya tetap `simba` karena riwayat.

    Client disimpan di `_sesi_simba` dan dipakai ulang antar operasi selama
    aplikasi terbuka, jadi tidak login tiap tombol. Pemanggil TIDAK boleh
    logout per-operasi; sesi ditutup sekali lewat `logout_sesi_simba` saat app
    ditutup, atau di-reset oleh `_kerja_simba` kalau token ditolak server.
    """
    global _sesi_simba

    def log(msg):
        if progress_callback:
            progress_callback(("log", msg))

    with _sesi_simba_lock:
        if _sesi_simba is not None and getattr(_sesi_simba, "token", None):
            return _sesi_simba

        # Sisa versi lama yang masih menyimpan token: dibuang supaya tidak
        # terbaca sebagai unit atau dikira sesi yang masih hidup.
        _hapus_token(SIMBA_TOKEN_FILE)

        if login_event is None or credentials_holder is None:
            raise SimbaAuthError(
                "Tidak ada mekanisme login (login_event/credentials_holder None)"
            )

        if progress_callback:
            progress_callback(("simba_login_required", None))

        login_event.wait()
        login_event.clear()

        creds = credentials_holder.get()
        if not creds:
            raise SimbaAuthError("Login dibatalkan oleh user")

        username = creds.get("username", "").strip()
        password = creds.get("password", "")
        token_info = (creds.get("token_info") or "").strip()

        if not username or not password:
            raise SimbaAuthError("Username/password kosong")
        if not token_info:
            raise SimbaAuthError("Kode enkripsi ACMT kosong")

        log(f"Login ke ACMT sebagai {username}...")
        client = SimbaClient(SIMBA_BASE_URL)
        client.login(username, password, token_info)
        _catat_unit_login(client.unitup, "ACMT", log)
        log("Login ACMT berhasil")

        _sesi_simba = client
        return client


def _reset_sesi_simba(logout=False, log=None):
    """Lepas sesi ACMT yang tercache. `logout=True` menutup sesi di server dulu
    (best-effort); dipakai saat aplikasi ditutup. Tanpa logout dipakai saat token
    sudah mati (sudah tidak sah di server, jadi tidak perlu dilogout)."""
    global _sesi_simba
    with _sesi_simba_lock:
        client = _sesi_simba
        _sesi_simba = None
    if client is not None and logout:
        try:
            _logout_simba(client, log or (lambda m: None))
        except Exception:
            pass


def logout_sesi_simba(progress_callback=None):
    """Logout sesi ACMT saat aplikasi ditutup. WAJIB dipanggil di handler close.
    No-op kalau tidak ada sesi; tidak pernah raise."""
    def log(msg):
        if progress_callback:
            progress_callback(("log", msg))
    _reset_sesi_simba(logout=True, log=log)


def _kerja_simba(kerja, progress_callback, login_event, credentials_holder):
    """Jalankan kerja(client) dengan client ACMT tercache; kalau token ditolak
    server, lepas cache, login ulang (dialog), lalu ulangi sekali.

    Meniru `_kerja_billing`: masa berlaku token ACMT tidak bisa dicek lokal, jadi
    satu-satunya tanda token mati adalah request yang gagal auth."""
    client = _get_simba_client(progress_callback, login_event, credentials_holder)
    try:
        return kerja(client)
    except SimbaAuthError as e:
        if progress_callback:
            progress_callback(("log", f"Token ACMT ditolak server: {e}"))
            progress_callback(("log", "Minta login ACMT ulang..."))
        _reset_sesi_simba(logout=False)
        client = _get_simba_client(progress_callback, login_event, credentials_holder)
        # Gagal lagi setelah token baru berarti bukan soal token - biarkan naik.
        return kerja(client)


def _target_foto(df, cfg):
    """Baris yang fotonya diunduh. `attrs['cakupan']` = keterangan untuk log.

    Default: STATUS bukan Normal, plus cabut/pasang bermasalah dan pelanggan
    PRIORITAS_KELAINAN (KD BACA ACMT) walau STATUS-nya Normal - tanpa foto,
    pemeriksa tidak bisa memastikan apa pun. Saklar `foto_semua_pelanggan`
    (Pengaturan Rule, default 0) mengunduh foto semua pelanggan.
    """
    if float(cfg.get("foto_semua_pelanggan", 0) or 0) >= 1:
        mask = pd.Series(True, index=df.index)
        cakupan = "SEMUA pelanggan - saklar foto semua aktif"
    else:
        mask = df["STATUS"] != "Normal"
        if "MASALAH_CABUT_PASANG" in df.columns:
            mask = mask | (df["MASALAH_CABUT_PASANG"] != "")
        if "KD_BACA_ACMT" in df.columns:
            huruf = df["KD_BACA_ACMT"].fillna("").map(pt.huruf_kode_baca)
            mask = mask | huruf.isin(pt.KODE_PRIORITAS)
        cakupan = "non-Normal + cabut/pasang bermasalah + prioritas KD BACA"
    df_foto = df[mask].copy()
    df_foto["IDPEL"] = df_foto["IDPEL"].astype(str)
    df_foto.attrs["cakupan"] = cakupan
    return df_foto


def _tempel_kd_baca(df, acmt, blth, cfg, log):
    """Tambah kolom KD_BACA_ACMT (label, mis. 'E-RUMAH TUTUP') dan
    STAN_METER_ACMT dari data ACMT, lalu jalankan rule Tagih Ulang Pasca Nol
    yang butuh stan ACMT itu."""
    d = acmt.drop_duplicates(subset=["IDPEL"], keep="first").set_index("IDPEL")
    peta = d["KD BACA"].map(pt.label_kode_baca)
    df = df.copy()
    kunci = pt._idpel12(df["IDPEL"].astype(str))
    df["KD_BACA_ACMT"] = kunci.map(peta).fillna("").values
    df["STAN_METER_ACMT"] = kunci.map(d["STAN METER"]).values
    huruf = df["KD_BACA_ACMT"].map(pt.huruf_kode_baca)
    log(f"KD BACA ACMT: {int((df['KD_BACA_ACMT'] != '').sum()):,} dari {len(df):,} "
        f"pelanggan terpetakan, {int(huruf.isin(pt.KODE_PRIORITAS).sum()):,} "
        f"masuk PRIORITAS_KELAINAN")
    df, n = tandai_tagih_ulang_pasca_nol(df, blth, cfg)
    log(f"Tagih Ulang Pasca Nol: {n:,} pelanggan (bulan lalu 0 kWh, stand "
        f"tagihan tidak didukung stan ACMT)")
    return df


def _tempel_kd_baca_csv(df, blth, unit, cfg, log):
    """KD BACA dari CSV ACMT terbaru yang disimpan Unduh DLPD. Return (df, ada)."""
    pola = os.path.join(UNDUHAN_DIR, str(unit), str(blth), f"ACMT_KodeBaca_{blth}_*.csv")
    files = glob.glob(pola)
    if not unit or not files:
        return df, False
    terbaru = max(files, key=os.path.getmtime)
    try:
        acmt = _baca_csv_acmt(terbaru)
    except Exception as e:
        log(f"CSV ACMT {os.path.basename(terbaru)} tidak terbaca ({e}) - diunduh ulang")
        return df, False
    log(f"KD BACA ACMT dari {os.path.basename(terbaru)}")
    return _tempel_kd_baca(df, acmt, blth, cfg, log), True


def _tempel_kd_baca_unduh(df, blth, unit, client, stop_flag, cfg, log):
    """KD BACA diunduh di sesi ACMT yang sudah login. Gagal -> df apa adanya
    (sheet PRIORITAS_KELAINAN tidak dibuat; tidak jatuh ke kelainan billing)."""
    log(f"Unduh kode baca ACMT {blth} (untuk sheet PRIORITAS_KELAINAN)...")
    try:
        acmt = _unduh_acmt_bulan(client, blth, log, stop_flag)
    except _Dibatalkan:
        return df
    except Exception as e:
        log(f"Kode baca ACMT gagal diunduh ({e}) - sheet PRIORITAS_KELAINAN dan "
            f"rule Tagih Ulang Pasca Nol dilewati")
        return df
    if unit:
        folder = os.path.join(UNDUHAN_DIR, str(unit), str(blth))
        os.makedirs(folder, exist_ok=True)
        acmt.to_csv(os.path.join(folder, f"ACMT_KodeBaca_{blth}_{_stempel_waktu()}.csv"),
                    index=False, encoding="utf-8-sig")
    return _tempel_kd_baca(df, acmt, blth, cfg, log)


def _logout_simba(client, log):
    """Tutup sesi ACMT. Kegagalan hanya dicatat: unduhan yang sudah selesai
    tidak boleh ikut dianggap gagal gara-gara logout."""
    ok, pesan = client.logout()
    if ok:
        log("Logout ACMT berhasil")
    else:
        log(f"Logout ACMT gagal (diabaikan): {pesan}")


def run_pipeline(
    dpm_path,
    blth,
    progress_callback=None,
    stop_flag=None,
    login_event=None,
    credentials_holder=None,
    verify_event=None,
    verify_holder=None,
):

    def log(msg):
        if progress_callback:
            progress_callback(("log", msg))

    def percent(p):
        if progress_callback:
            progress_callback(("percent", p))

    output_dir = os.path.join(HASIL_DIR, blth)
    os.makedirs(output_dir, exist_ok=True)

    cfg = settings.load_rules()

    # Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬ LOAD Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
    log("LOAD DATA")
    unitup = unit_untuk_dpm(dpm_path, log)
    log(f"Unit: {unitup or 'tidak diketahui'}")
    berkas_db = db_path(unitup)
    if berkas_db:
        log(f"Database rekening: {os.path.basename(berkas_db)}")
    else:
        log("Database rekening unit ini belum ada - semua baris jadi DATA BARU. "
            "Pakai tombol Cek Database untuk mengunduhnya.")
    dpm, db = load_data(dpm_path, berkas_db)

    stanbaca_db = None
    if ENABLE_STAN_BACA:
        stanbaca_db = load_stanbaca_data(stanbaca_db_path(unitup))
        if stanbaca_db is None:
            log("Database stan baca unit ini belum ada - dilewati")
        else:
            log(f"Database stan baca dimuat ({len(stanbaca_db)} baris)")

    percent(5)

    if stop_flag and stop_flag():
        log("Dibatalkan")
        return

    # ----- VERIFIKASI COVERAGE DATABASE (min N bulan) -----
    n_bulan = cfg["jumlah_bulan_rata2"]
    idpel_list = dpm["IDPEL"].astype(str).unique().tolist()

    cov_rekening = verification.check_coverage(db, blth, n_bulan, idpel_list)
    cov_stanbaca = (
        verification.check_coverage(stanbaca_db, blth, n_bulan, idpel_list)
        if ENABLE_STAN_BACA else None
    )

    if verify_event is not None and verify_holder is not None:
        if progress_callback:
            progress_callback(("verification_required", {
                "rekening": cov_rekening,
                "stanbaca": cov_stanbaca,
                "n_bulan": n_bulan,
            }))
        verify_event.wait()
        verify_event.clear()

        if not verify_holder.get():
            log("Dibatalkan (verifikasi database)")
            return

    if stop_flag and stop_flag():
        log("Dibatalkan")
        return

    # Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬ PREPARE Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
    log("PREPARE")
    df = prepare(dpm, db, cfg)
    percent(10)

    if stop_flag and stop_flag():
        log("Dibatalkan")
        return

    # Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬ ANALYZE Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
    log("ANALYZE")
    df = apply_analysis(df, cfg)

    if stanbaca_db is not None:
        df = compute_stanbaca_comparison(df, stanbaca_db, blth, cfg)
        if "STAND_BACA_LALU" in df.columns:
            n_tanpa = int(df["STAND_BACA_LALU"].isna().sum())
            if n_tanpa:
                bulan_lalu = (pd.Period(str(blth), freq="M") - 1).strftime("%Y%m")
                log(f"PERINGATAN: stan baca {bulan_lalu} tidak ada untuk "
                    f"{n_tanpa:,} dari {len(df):,} pelanggan - PEMAKAIAN_ASLI "
                    f"mereka dikosongkan. Update database stan baca.")

    df = compute_cabut_pasang(df, cfg)
    n_cp, n_cp_masalah = ringkasan_cabut_pasang(df)
    if n_cp:
        log(f"Cabut/pasang meter: {n_cp} pelanggan, {n_cp_masalah} stand bermasalah")

    percent(20)

    if stop_flag and stop_flag():
        log("Dibatalkan")
        return

    # Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬ FILTER UNTUK FOTO Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
    # KD BACA ACMT untuk sheet PRIORITAS_KELAINAN: dari CSV yang disimpan
    # Unduh DLPD kalau ada; kalau belum, diunduh di sesi ACMT foto di bawah.
    df, ada_kd = _tempel_kd_baca_csv(df, blth, unitup, cfg, log)
    df_foto = _target_foto(df, cfg)

    # Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬ ACMT + DOWNLOAD FOTO + KLASIFIKASIÃ¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
    results = {}
    bulan_list = []
    klasifikasi = {}

    if not ENABLE_PHOTO_DOWNLOAD:
        log("Download foto DINONAKTIFKAN (ENABLE_PHOTO_DOWNLOAD=False) - skip ACMT & klasifikasi")
        if not ada_kd:
            log("KD BACA ACMT tidak tersedia - sheet PRIORITAS_KELAINAN dan rule "
                "Tagih Ulang Pasca Nol dilewati")
        percent(90)
    else:
        # Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬ SIMBA AUTH Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
        simba_client = _get_simba_client(
            progress_callback, login_event, credentials_holder
        )
        percent(22)

        if stop_flag and stop_flag():
            log("Dibatalkan")
            return

        # KD BACA belum ada dari CSV: unduh di sesi yang sama (tanpa login
        # tambahan), lalu target foto dihitung ulang supaya pelanggan
        # prioritas ikut difoto.
        if not ada_kd:
            df = _tempel_kd_baca_unduh(df, blth, unitup, simba_client, stop_flag, cfg, log)
            df_foto = _target_foto(df, cfg)

        # Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬ DOWNLOAD FOTO (info + download pipelined) Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
        n_target = len(df_foto)
        log(f"AMBIL DATA & FOTO DARI ACMT ({n_target} pelanggan, {df_foto.attrs['cakupan']})")
        log(f"  Pipeline: INFO + DOWNLOAD jalan bersamaan (22-85%)")

        # State untuk throttle log: log tiap kelipatan 10% kemajuan gabungan
        photo_state = {
            "info_started": False,
            "dl_started": False,
            "info_bucket": -1,
            "dl_bucket": -1,
        }

        def photo_progress(data):
            info_done = data.get("info_done", 0)
            info_total = data.get("info_total", 0) or 0
            dl_done = data.get("dl_done", 0)
            dl_total = data.get("dl_total", 0) or 0
            dl_ok = data.get("dl_ok", 0)
            dl_fail = data.get("dl_fail", 0)
            eta_info = data.get("eta_info", 0)
            eta_dl = data.get("eta_dl", 0)

            # Progress 22-85% (range 63%) terbagi rata 50/50 untuk info & download.
            # Karena keduanya overlap, ambil rata-rata bobot.
            info_frac = (info_done / info_total) if info_total else 1.0
            dl_frac = (dl_done / dl_total) if dl_total else 0.0
            # Kalau dl_total masih 0 (info baru mulai), pakai info saja.
            if dl_total == 0:
                p = 22 + info_frac * 63
            else:
                # Begitu download mulai, weight sama: bar isi proporsional
                # sampai keduanya selesai.
                p = 22 + (info_frac * 0.4 + dl_frac * 0.6) * 63

            percent(p)
            if progress_callback:
                progress_callback(("eta", max(eta_info, eta_dl)))

            # Log INFO setiap kelipatan 10%
            if info_total > 0:
                if not photo_state["info_started"]:
                    photo_state["info_started"] = True
                    log(f"  [INFO] mulai: {info_total} item")
                pct_info = int(info_done / info_total * 100) if info_total else 100
                bucket = pct_info // 10
                if bucket > photo_state["info_bucket"] or info_done == info_total:
                    photo_state["info_bucket"] = bucket
                    eta_str = f", ETA {eta_info}s" if eta_info else ""
                    log(f"  [INFO] {info_done}/{info_total} ({pct_info}%){eta_str}")

            # Log DOWNLOAD setiap kelipatan 10% (tapi total bisa naik selama
            # info berjalan, jadi log juga saat dl_total bertambah signifikan)
            if dl_total > 0:
                if not photo_state["dl_started"]:
                    photo_state["dl_started"] = True
                    log(f"  [DOWNLOAD] mulai (target bertumbuh selama info berjalan)")
                pct_dl = int(dl_done / dl_total * 100) if dl_total else 0
                bucket = pct_dl // 10
                if bucket > photo_state["dl_bucket"] or (
                    info_done == info_total and dl_done == dl_total
                ):
                    photo_state["dl_bucket"] = bucket
                    eta_str = f", ETA {eta_dl}s" if eta_dl else ""
                    log(
                        f"  [DOWNLOAD] {dl_done}/{dl_total} "
                        f"ok={dl_ok} fail={dl_fail} ({pct_dl}%){eta_str}"
                    )

        def _kerja_download_foto(simba_client):
            return download_photos(
                df_foto,
                simba_client,
                blth,
                FOTO_DIR,
                JUMLAH_BULAN_FOTO,
                MAX_WORKERS_INFO,
                MAX_WORKERS_DOWNLOAD,
                progress_callback=photo_progress,
                stop_flag=stop_flag,
            )

        try:
            # Sesi ACMT TIDAK di-logout di sini: dipakai ulang antar operasi dan
            # ditutup sekali saat aplikasi ditutup. Kalau token ditolak di tengah,
            # _kerja_simba login ulang lalu mengulang download.
            results, bulan_list = _kerja_simba(
                _kerja_download_foto, progress_callback,
                login_event, credentials_holder,
            )
        except SimbaAuthError as e:
            log(f"ERROR auth ACMT: {e}")
            raise
        except SimbaError as e:
            log(f"ERROR ACMT: {e}")
            raise

        # Summary download
        n_idpel_with_photo = len(results)
        n_files = sum(len(v) for v in results.values())
        log(
            f"Download selesai: {n_idpel_with_photo}/{n_target} pelanggan dapat foto, "
            f"total {n_files} file tersimpan"
        )
        if n_idpel_with_photo < n_target:
            n_missing = n_target - n_idpel_with_photo
            log(f"  {n_missing} pelanggan TIDAK dapat foto (kemungkinan tidak ada di ACMT)")

        percent(85)

        if stop_flag and stop_flag():
            log("Dibatalkan")
            return

        # Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬ KLASIFIKASI FOTO (KWH METER vs BUKAN) Ã¢â€â‚¬
        if ENABLE_CLASSIFIER and classifier_available(MODEL_PATH):
            log("KLASIFIKASI FOTO (KWH METER vs BUKAN)")

            # Hanya klasifikasi foto bulan terbaru (idx=1, sesuai bulan_list[0])
            idpel_to_path = {}
            for idpel, m in results.items():
                p = m.get(1)
                if p:
                    idpel_to_path[idpel] = p

            if idpel_to_path:
                def classify_progress(done, total, idpel, label):
                    # 85-90%
                    p = 85 + (done / total) * 5
                    percent(p)

                klasifikasi = classify_all(
                    idpel_to_path,
                    MODEL_PATH,
                    progress_callback=classify_progress,
                    stop_flag=stop_flag,
                )

                n_bukan = sum(1 for v in klasifikasi.values() if v == "bukan_kwh")
                n_kwh = sum(1 for v in klasifikasi.values() if v == "kwh_meter")
                n_unknown = sum(1 for v in klasifikasi.values()
                                if v not in ("bukan_kwh", "kwh_meter"))
                log(
                    f"Klasifikasi selesai: {n_bukan} bukan_kwh, "
                    f"{n_kwh} kwh_meter, {n_unknown} unknown"
                )
            else:
                log("Tidak ada foto bulan terbaru untuk diklasifikasi")
        else:
            if not ENABLE_CLASSIFIER:
                log("Klasifikasi dilewati (ENABLE_CLASSIFIER=False)")
            else:
                log("Klasifikasi dilewati (model atau ultralytics tidak tersedia)")

        percent(90)

        percent(90)

    if stop_flag and stop_flag():
        log("Dibatalkan")
        return

    # â”€â”€â”€ READ METER DIGITS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    ocr_results = {}

    if not ENABLE_DIGIT_READER:
        log("Digit reader DINONAKTIFKAN (ENABLE_DIGIT_READER=False)")
    elif not reader_available(DIGIT_MODEL_PATH):
        log(f"Digit reader tidak tersedia (model tidak ditemukan: {DIGIT_MODEL_PATH})")
        log("  Jalankan tools/train_yolo.py setelah anotasi selesai")
    else:
        log("BACA DIGIT METER DARI FOTO")

        if results:
            idpel_to_read = {}
            for idpel in df_foto["IDPEL"].unique():
                m = results.get(idpel, {})
                p = m.get(1)
                if p:
                    idpel_to_read[idpel] = p

            if idpel_to_read:
                def read_progress(done, total, idpel, result):
                    p = 90 + (done / total) * 5
                    percent(p)
                    if result.get("success"):
                        log(f"  [{done}/{total}] {idpel}: stand={result['stand']} (conf={result['confidence']:.2f})")
                    else:
                        log(f"  [{done}/{total}] {idpel}: GAGAL - {result.get('error', 'unknown')}")

                ocr_results = read_meter_batch(
                    idpel_to_read,
                    DIGIT_MODEL_PATH,
                    progress_callback=read_progress,
                    stop_flag=stop_flag,
                    conf_threshold=0.3,
                )

                n_ok = sum(1 for v in ocr_results.values() if v.get("success"))
                log(f"Pembacaan digit selesai: {n_ok}/{len(ocr_results)} berhasil")
            else:
                log("Tidak ada foto untuk dibaca digitnya")
        else:
            log("Tidak ada hasil download foto untuk dibaca digitnya")

    percent(95)

    # â•â•â• EXPORT â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    log("EXPORT EXCEL")
    df = tambah_saran_koreksi(df, cfg, klasifikasi)
    n_saran = (df["PILIHAN"] != "BIARKAN").sum()
    log(f"Saran koreksi stand otomatis: {n_saran} pelanggan (lihat sheet KOREKSI_STAND)")
    output_file = os.path.join(output_dir, f"hasil_analisa_{_stempel_waktu()}.xlsx")
    sheet_map = export_excel(df, output_file, bulan_list, klasifikasi, ocr_results)

    log("FORMAT EXCEL")
    format_excel(output_file, sheet_map, results, bulan_list, ocr_results, cfg)
    percent(100)

    log(f"SELESAI -> {output_file}")


# =========================
# UPDATE DATABASE OTOMATIS
# =========================

def run_db_check(blth, unitup=None, progress_callback=None):
    """Cek kelengkapan kedua database untuk analisis periode `blth`.

    Aturannya sama dengan verifikasi yang jalan di dalam pipeline: minimal
    `jumlah_bulan_rata2` bulan SEBELUM blth harus ada. Bedanya di sini tidak
    ada daftar IDPEL untuk dicek per pelanggan - tombol ini dipakai sebelum
    file DPM dipilih, jadi yang dilaporkan cuma bulan yang hilang db-wide.
    """

    def log(msg):
        if progress_callback:
            progress_callback(("log", msg))

    cfg = settings.load_rules()
    n_bulan = cfg["jumlah_bulan_rata2"]

    if not unitup:
        unitup = unit_aktif()

    log(f"Cek database untuk periode {blth} (butuh {n_bulan} bulan ke belakang)")
    log(f"Unit: {unitup or 'belum diketahui - login dulu lewat Update Database'}")

    db = None
    berkas_db = db_path(unitup)
    if not berkas_db:
        log("Database rekening unit ini belum ada")
    else:
        try:
            terbaca = _read_excel_auto(berkas_db)
            terbaca["BULAN"] = terbaca["BULAN"].astype(int)
            db = terbaca
            log(f"Database rekening: {len(db):,} baris ({os.path.basename(berkas_db)})")
        except Exception as e:
            # db sengaja dibiarkan None: DataFrame setengah jadi (mis. tanpa
            # kolom BULAN) akan meledak di check_coverage, jauh dari sumbernya.
            log(f"Database rekening tidak terbaca: {e}")

    stanbaca_db = None
    if ENABLE_STAN_BACA:
        stanbaca_db = load_stanbaca_data(stanbaca_db_path(unitup))
        if stanbaca_db is None:
            log("Database stan baca unit ini belum ada")
        else:
            log(f"Database stan baca: {len(stanbaca_db):,} baris")

    cov_rekening = verification.check_coverage(db, blth, n_bulan)
    cov_stanbaca = (
        verification.check_coverage(stanbaca_db, blth, n_bulan)
        if ENABLE_STAN_BACA else None
    )

    # Jumlah baris per bulan. check_coverage menganggap sebuah bulan "ada"
    # begitu ada SATU baris saja, jadi bulan yang tarikannya gagal separuh
    # bisa lolos sebagai lengkap. Hitungan ini ditampilkan di dialog supaya
    # bulan yang isinya tipis kelihatan dan bisa ditarik ulang manual.
    if cov_rekening:
        cov_rekening["jumlah_per_bulan"] = _hitung_per_bulan(db, cov_rekening)
    if cov_stanbaca:
        cov_stanbaca["jumlah_per_bulan"] = _hitung_per_bulan(stanbaca_db, cov_stanbaca)

    return {
        "blth": blth,
        "n_bulan": n_bulan,
        "unitup": unitup,
        "rekening": cov_rekening,
        "stanbaca": cov_stanbaca,
    }


def _hitung_per_bulan(df, cov):
    """{bulan: jumlah_baris} untuk bulan-bulan yang diverifikasi."""
    if df is None or df.empty:
        return {}
    hitung = df["BULAN"].astype(int).value_counts()
    return {b: int(hitung.get(int(b), 0)) for b in cov.get("bulan_list", [])}


def _get_billing_client(progress_callback, login_event, credentials_holder,
                        paksa_login=False):
    """Setup client portal billing. Reuse token tersimpan, kalau tidak minta login GUI.

    `paksa_login=True` melewati token tersimpan - dipakai saat server sudah
    menolak token itu, supaya tidak berputar memakai token yang sama.
    """

    def log(msg):
        if progress_callback:
            progress_callback(("log", msg))

    client = BillingClient(BILLING_AUTH_URL, BILLING_API_URL)

    if not paksa_login and client.load_token(BILLING_TOKEN_FILE):
        log(f"Coba pakai token billing tersimpan ({client.username})...")
        if client.probe():
            log("Token billing masih berlaku")
            return client
        log("Token billing kedaluwarsa, perlu login ulang")

    if login_event is None or credentials_holder is None:
        raise BillingAuthError(
            "Tidak ada mekanisme login billing (login_event/credentials_holder None)"
        )

    if progress_callback:
        progress_callback(("billing_login_required", None))

    login_event.wait()
    login_event.clear()

    creds = credentials_holder.get()
    if not creds:
        raise BillingAuthError("Login billing dibatalkan oleh user")

    username = creds.get("username", "").strip()
    password = creds.get("password", "")
    token_info = (creds.get("token_info") or "").strip()

    if not username or not password:
        raise BillingAuthError("Username/password billing kosong")
    if not token_info:
        raise BillingAuthError("Kode enkripsi billing kosong")

    log(f"Login ke portal billing sebagai {username}...")
    client.login(username, password, token_info)
    client.save_token(BILLING_TOKEN_FILE)
    _catat_unit_login(client.unitup, "portal billing", log)
    log(f"Login billing berhasil ({client.nama} - unit {client.unitup})")

    return client


def _kerja_billing(kerja, progress_callback, login_event, credentials_holder):
    """Jalankan kerja(client); kalau token ditolak server, login ulang lalu ulangi.

    Token portal billing membawa klaim exp bertahun-tahun ke depan, jadi
    probe() lokal bisa bilang "masih berlaku" padahal server sudah tidak
    mengakuinya (mis. login dari tempat lain). Satu-satunya cara tahu adalah
    request sungguhan gagal - jadi kegagalan itu yang dipakai sebagai pemicu
    login ulang, bukan dibiarkan jadi error buntu.
    """

    def log(msg):
        if progress_callback:
            progress_callback(("log", msg))

    client = _get_billing_client(progress_callback, login_event, credentials_holder)
    try:
        return kerja(client)
    except BillingAuthError as e:
        log(f"Token ditolak server: {e}")
        _hapus_token(BILLING_TOKEN_FILE)
        log("Minta login ulang untuk ambil token baru...")
        client = _get_billing_client(
            progress_callback, login_event, credentials_holder, paksa_login=True
        )
        # Gagal lagi setelah token baru berarti bukan soal token - biarkan naik.
        return kerja(client)


def _folder_unduhan(client, blth):
    """unduhan/<unitup>/<blth>/ - dipisah per unit supaya file dari unit
    berbeda tidak saling menimpa, dan per bulan supaya mudah ditelusuri."""
    unit = str(client.unitup or "unit")
    return os.path.join(UNDUHAN_DIR, unit, str(blth))


def _sufiks_kode(kode_list):
    """['T0','T1'] -> '_T0T1' untuk menandai cakupan file di namanya."""
    if not kode_list:
        return ""
    return "_" + "".join(str(k).strip().upper() for k in kode_list)


def _stempel_waktu():
    """'20260913_194512' - penanda waktu untuk nama file hasil & unduhan.

    Setiap unduhan diberi stempel supaya tarikan ulang periode yang sama tidak
    menimpa file sebelumnya; riwayat file mentahnya tetap bisa ditelusuri.
    """
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _pastikan_unit_cocok(client, unit_diharapkan, sumber):
    """Tolak kalau unit login beda dari unit yang sedang dikerjakan.

    Daftar bulan yang kurang dihitung untuk `unit_diharapkan`, tapi hasil
    unduhan ditulis ke unit yang login. Kalau keduanya beda, yang ditarik adalah
    bulan yang kurang di unit LAIN - database unit yang benar bisa tetap bolong
    tanpa ada yang memberi tahu. Karena itu dihentikan sebelum menulis apa pun.
    """
    if not unit_diharapkan or not client.unitup:
        return
    if str(client.unitup) != str(unit_diharapkan):
        raise DbUpdateError(
            f"Anda login {sumber} sebagai unit {client.unitup}, tapi yang mau "
            f"diperbarui database unit {unit_diharapkan}. Login sebagai "
            f"{unit_diharapkan}, atau ganti unit aktif ke {client.unitup} lalu "
            f"tekan Cek Database lagi."
        )


def _unduh_rekening(bulan_list, progress_callback, stop_flag,
                    billing_login_event, billing_credentials_holder, unit=None,
                    unit_diharapkan=None):
    """Unduh + parse export billing untuk tiap bulan. Return DataFrame gabungan."""

    def log(msg):
        if progress_callback:
            progress_callback(("log", msg))

    frames = []
    # Satu stempel per pemanggilan, di LUAR kerja: login ulang yang mengulang
    # kerja memakai nama yang sama, bukan menyisakan setengah set file.
    stempel = _stempel_waktu()

    def kerja(client):
        del frames[:]
        _pastikan_unit_cocok(client, unit_diharapkan, "portal billing")
        # Unit dicatat DI SINI, satu-satunya tempat ia diketahui pasti: client
        # yang benar-benar berhasil login. Pemanggil memakainya untuk memilih
        # file database tujuan.
        if unit is not None:
            unit["unitup"] = client.unitup
        for bulan in bulan_list:
            if stop_flag and stop_flag():
                log("Dibatalkan")
                return None

            folder = _folder_unduhan(client, bulan)
            os.makedirs(folder, exist_ok=True)
            save_path = os.path.join(
                folder, f"Monitoring_Billing_Detail_{bulan}_{stempel}.xlsx")
            log(f"Unduh database rekening {bulan}...")
            size = client.download_billing_detail(
                bulan, save_path, BILLING_EXPORT_SIZE, catat=log)
            log(f"  file diterima {size / 1048576:.1f} MB")

            df = parse_billing_export(save_path, bulan)
            log(f"  terparsing {len(df):,} baris")
            frames.append(df)
        return True

    hasil = _kerja_billing(
        kerja, progress_callback, billing_login_event, billing_credentials_holder
    )
    if hasil is None:
        return None
    return pd.concat(frames, ignore_index=True) if frames else None


def _unduh_stanbaca(bulan_list, progress_callback, stop_flag,
                    login_event, credentials_holder, unit=None,
                    unit_diharapkan=None):
    """Unduh + parse laporan kode baca (3 kategori/bulan). Return DataFrame gabungan."""

    def log(msg):
        if progress_callback:
            progress_callback(("log", msg))

    # Sesi ACMT di-cache & dipakai ulang antar operasi (tidak logout di sini);
    # _kerja_simba login ulang otomatis kalau token ditolak server.
    def kerja(client):
        _pastikan_unit_cocok(client, unit_diharapkan, "ACMT")
        if unit is not None:
            unit["unitup"] = client.unitup

        frames = []
        for bulan in bulan_list:
            if stop_flag and stop_flag():
                log("Dibatalkan")
                return None

            log(f"Unduh database stan baca {bulan}...")
            n_bulan_ini = 0
            for kdbaca in KODE_BACA_KATEGORI:
                if stop_flag and stop_flag():
                    log("Dibatalkan")
                    return None
                raw = client.download_kode_baca(bulan, kdbaca)
                df = parse_kode_baca_export(raw, kdbaca, bulan)
                n_bulan_ini += len(df)
                log(f"  {kdbaca}: {len(df):,} baris")
                if not df.empty:
                    frames.append(df)
            log(f"  total {bulan}: {n_bulan_ini:,} baris")

        return pd.concat(frames, ignore_index=True) if frames else None

    return _kerja_simba(kerja, progress_callback, login_event, credentials_holder)


def run_db_update(
    bulan_rekening,
    bulan_stanbaca,
    unit_diharapkan=None,
    progress_callback=None,
    stop_flag=None,
    login_event=None,
    credentials_holder=None,
    billing_login_event=None,
    billing_credentials_holder=None,
):
    """Unduh bulan-bulan yang hilang lalu tulis ke database.

    `bulan_rekening` / `bulan_stanbaca` = list "YYYYMM" (boleh kosong).
    Penulisan database dilakukan SEKALI di akhir per database, bukan per bulan:
    satu file berisi ratusan ribu baris dan penulisannya puluhan detik.
    """

    def log(msg):
        if progress_callback:
            progress_callback(("log", msg))

    def percent(p):
        if progress_callback:
            progress_callback(("percent", p))

    if unit_diharapkan:
        log(f"Unit yang diperbarui: {unit_diharapkan}")

    hasil = {"rekening": None, "stanbaca": None}
    # Unit tiap sumber dicatat terpisah: rekening dari portal billing, stan baca
    # dari ACMT. Keduanya biasanya sama, tapi jangan diasumsikan - kalau user
    # login sebagai unit berbeda di dua sistem itu, masing-masing tetap harus
    # menulis ke database unitnya sendiri.
    unit_rek = {"unitup": None}
    unit_sb = {"unitup": None}
    percent(0)

    # ----- REKENING -----
    if bulan_rekening:
        log(f"=== DATABASE REKENING: {len(bulan_rekening)} bulan ===")
        try:
            df = _unduh_rekening(
                bulan_rekening, progress_callback, stop_flag,
                billing_login_event, billing_credentials_holder, unit_rek,
                unit_diharapkan,
            )
        except BillingAuthError:
            # Token ditolak server: buang supaya run berikutnya minta login lagi.
            _hapus_token(BILLING_TOKEN_FILE)
            raise
        if df is None:
            return hasil
        percent(40)
        log(f"Tulis database rekening ({len(df):,} baris baru diunduh)...")
        hasil["rekening"] = append_rekening(df, unit_rek["unitup"])
        _log_statistik(log, "Database rekening", hasil["rekening"])
    percent(50)

    if stop_flag and stop_flag():
        log("Dibatalkan")
        return hasil

    # ----- STAN BACA -----
    if bulan_stanbaca:
        log(f"=== DATABASE STAN BACA: {len(bulan_stanbaca)} bulan ===")
        df = _unduh_stanbaca(
            bulan_stanbaca, progress_callback, stop_flag,
            login_event, credentials_holder, unit_sb, unit_diharapkan,
        )
        if df is None:
            return hasil
        percent(85)
        log(f"Tulis database stan baca ({len(df):,} baris baru diunduh)...")
        hasil["stanbaca"] = append_stanbaca(df, unit_sb["unitup"])
        _log_statistik(log, "Database stan baca", hasil["stanbaca"])

    percent(100)
    log("UPDATE DATABASE SELESAI")
    return hasil


def _log_statistik(log, judul, stat):
    if not stat:
        return
    n_lama = stat["n_lama"]
    n_total = stat["n_total"]
    n_baru = stat["n_baru"]
    n_unduh = stat["n_diunduh"]
    log(f"{judul}: {n_lama:,} -> {n_total:,} baris (+{n_baru:,} baru dari {n_unduh:,} diunduh)")
    log(f"  disimpan: {stat['path']}")
    if stat.get("backup"):
        log(f"  backup  : {stat['backup']}")


def _hapus_token(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def run_unduh_dlpd(
    blth,
    kd_proses,
    progress_callback=None,
    stop_flag=None,
    billing_login_event=None,
    billing_credentials_holder=None,
    login_event=None,
    credentials_holder=None,
):
    """Unduh export DLPD + DPM lalu gabungkan jadi satu file input.

    Setelah itu otomatis membuat Daftar Pagar Terkunci (`stat["pagar"]`),
    memakai login ACMT lewat `login_event`/`credentials_holder`. Login itu
    opsional: kalau dibatalkan, file DLPD tetap jadi tapi daftar tidak dibuat.

    Dua file diperlukan karena export DLPD tidak membawa `kelainan_bc_meter`;
    kolom itu hanya ada di export DPM dan di-lookup lewat idpel.

    Return dict statistik dari gabung_dlpd_dpm (termasuk `path` file hasil),
    atau None kalau dibatalkan.
    """

    def log(msg):
        if progress_callback:
            progress_callback(("log", msg))

    def percent(p):
        if progress_callback:
            progress_callback(("percent", p))

    if not kd_proses:
        raise DbUpdateError("Belum ada Kd Proses yang dipilih")

    setelan = settings.load_unduh_settings()
    percent(0)
    log(f"=== UNDUH FILE DLPD {blth} ===")
    log(f"Kd Proses: {', '.join(kd_proses)}")

    jalur = {}
    # Satu stempel untuk ketiga file (DLPD, DPM, gabungan) supaya satu set bisa
    # ditelusuri bersama, dan dihitung di luar kerja agar login ulang tidak
    # memecah set itu ke dua stempel.
    stempel = _stempel_waktu()

    def kerja(client):
        """Unduh kedua export. Dipisah jadi fungsi supaya bisa diulang utuh
        setelah login ulang - token baru berarti seluruh rangkaian request
        harus dijalankan lagi, bukan disambung di tengah."""
        if stop_flag and stop_flag():
            log("Dibatalkan")
            return None

        folder = _folder_unduhan(client, blth)
        os.makedirs(folder, exist_ok=True)
        jalur["unit"] = client.unitup
        sufiks = _sufiks_kode(kd_proses)
        jalur["dlpd"] = os.path.join(
            folder, f"Monitoring_Dlpd_Detail_{blth}{sufiks}_{stempel}.xlsx")
        jalur["dpm"] = os.path.join(
            folder, f"Monitoring_DPM_Detail_{blth}{sufiks}_{stempel}.xlsx")
        jalur["keluar"] = os.path.join(
            folder, f"DLPD_{blth}{sufiks}_gabungan_{stempel}.xlsx")

        # DPM ditarik dengan Kd Proses yang SAMA supaya setiap baris DLPD punya
        # peluang ketemu pasangannya; kalau pilihannya berbeda, sebagian baris
        # pasti tidak cocok bukan karena datanya memang tidak ada.
        def unduh_dlpd():
            n = client.download_dlpd_detail(
                blth, kd_proses, jalur["dlpd"],
                dlpd=setelan["dlpd"],
                status_verifikasi=setelan["status_verifikasi_dlpd"],
                catat=log,
            )
            log(f"  file DLPD diterima {n / 1048576:.1f} MB")
            return n

        def unduh_dpm():
            n = client.download_dpm_detail(
                blth, kd_proses, jalur["dpm"],
                kodeposting=setelan["kodeposting_dpm"],
                catat=log,
            )
            log(f"  file DPM diterima {n / 1048576:.1f} MB")
            return n

        if ENABLE_UNDUH_PARALEL:
            # DLPD & DPM independen dan waktunya didominasi generate di server;
            # dijalankan bersamaan pada client yang sama. BillingAuthError dari
            # salah satunya sengaja digelembungkan keluar supaya _kerja_billing
            # login ulang lalu menjalankan SELURUH kerja lagi (bukan disambung).
            log(f"Unduh export DLPD + DPM {blth} paralel "
                f"(unit {client.unitap}/{client.unitup})...")
            percent(10)
            with ThreadPoolExecutor(max_workers=2,
                                    thread_name_prefix="unduh") as pool:
                futs = {
                    pool.submit(unduh_dlpd): "DLPD",
                    pool.submit(unduh_dpm): "DPM",
                }
                selesai = 0
                for fut in as_completed(futs):
                    fut.result()  # re-raise; BillingAuthError naik ke _kerja_billing
                    selesai += 1
                    percent(40 if selesai == 1 else 70)
        else:
            log(f"Unduh export DLPD {blth} "
                f"(unit {client.unitap}/{client.unitup})...")
            percent(10)
            unduh_dlpd()
            percent(40)
            if stop_flag and stop_flag():
                log("Dibatalkan")
                return None
            log(f"Unduh export DPM {blth} (untuk kolom kelainan_bc_meter)...")
            unduh_dpm()
            percent(70)

        if stop_flag and stop_flag():
            log("Dibatalkan")
            return None
        return True

    if _kerja_billing(kerja, progress_callback,
                      billing_login_event, billing_credentials_holder) is None:
        return None

    if stop_flag and stop_flag():
        log("Dibatalkan")
        return None

    log("Gabungkan kelainan_bc_meter ke keterangan_dlpd...")
    stat = gabung_dlpd_dpm(jalur["dlpd"], jalur["dpm"], jalur["keluar"])

    log(f"  DLPD {stat['n_dlpd']:,} baris, DPM {stat['n_dpm']:,} baris")
    log(f"  {stat['n_cocok']:,} baris dapat kelainan_bc_meter")
    if stat.get("n_sudah_gabung"):
        log(f"  {stat['n_sudah_gabung']:,} baris sudah bergabung sebelumnya - dilewati")
    if stat["n_tak_cocok"]:
        # Sedikit tidak cocok itu wajar (DLPD memuat pelanggan yang tidak
        # terbawa filter DPM); kalau angkanya besar, biasanya Kd Proses atau
        # filter kodeposting-nya yang perlu diperiksa.
        log(f"  {stat['n_tak_cocok']:,} baris tanpa pasangan di DPM "
            f"- keterangan_dlpd-nya dibiarkan apa adanya")
    log(f"File siap dipakai: {jalur['keluar']}")
    percent(75)

    # Daftar pagar terkunci menumpang di ujung alur. Apa pun yang terjadi di
    # sini tidak boleh membuat file DLPD yang sudah jadi dianggap gagal.
    stat["pagar"] = None
    if stop_flag and stop_flag():
        log("Dibatalkan - daftar pagar terkunci dilewati")
    else:
        try:
            stat["pagar"] = _buat_pagar_terkunci(
                blth, jalur["unit"], jalur["keluar"], stempel,
                progress_callback, stop_flag, login_event, credentials_holder,
                kd_proses,
            )
        except _Dibatalkan:
            log("Dibatalkan - daftar pagar terkunci dilewati")
            stat["pagar"] = {"error": "dibatalkan"}
        except Exception as e:
            log(f"ERROR daftar pagar terkunci: {e}")
            stat["pagar"] = {"error": str(e)}
    percent(100)

    return stat


# =========================
# DAFTAR PAGAR TERKUNCI
# =========================

class _Dibatalkan(Exception):
    """Operator menekan Batal saat daftar pagar terkunci dibuat."""


def _cek_batal(stop_flag):
    if stop_flag and stop_flag():
        raise _Dibatalkan()


def _coba_ulang(fungsi, label, log, stop_flag, jeda=(5, 15, 30)):
    """Jalankan `fungsi`; SimbaError (5xx/putus) diulang dengan jeda.

    SimbaAuthError tidak diulang - token mati tidak sembuh dengan menunggu.
    Penantian dicek tiap 0,5 detik supaya tombol Batal tetap responsif.
    """
    for i in range(len(jeda) + 1):
        _cek_batal(stop_flag)
        try:
            return fungsi()
        except SimbaError as e:
            if i == len(jeda):
                raise
            log(f"  {label} gagal ({e}); coba lagi {jeda[i]} dtk...")
            batas = time.monotonic() + jeda[i]
            while time.monotonic() < batas:
                _cek_batal(stop_flag)
                time.sleep(0.5)


def _unduh_acmt_bulan(client, bulan, log, stop_flag):
    """Satu bulan laporan kode baca ACMT, ketiga kategori -> DataFrame lengkap."""
    frames = []
    for kdbaca in KODE_BACA_KATEGORI:
        raw = _coba_ulang(lambda: client.download_kode_baca(bulan, kdbaca),
                          f"ACMT {bulan} {kdbaca}", log, stop_flag)
        df = parse_acmt_lengkap(raw, kdbaca, bulan)
        log(f"  ACMT {bulan} {kdbaca}: {len(df):,} baris")
        frames.append(df)
    return pt.rapikan_acmt(pd.concat(frames, ignore_index=True))


def _baca_csv_acmt(path):
    return pt.rapikan_acmt(pd.read_csv(path, dtype=str, encoding="utf-8-sig"))


def _unduh_acmt_pagar(blth, unit, folder, stempel, progress_callback, stop_flag,
                      login_event, credentials_holder, bulan_di_db=()):
    """Satu sesi ACMT: BLTH ini + bulan lalu yang belum ada di mana pun.

    Bulan di `bulan_di_db` sudah lengkap di database stan baca (yang juga
    berasal dari ACMT), jadi tidak diunduh lagi.
    Return (df_acmt_ini atau None, {bulan: df}, alasan_kalau_None).
    """

    def log(msg):
        if progress_callback:
            progress_callback(("log", msg))

    # Bulan lampau tidak berubah: diunduh sekali lalu dibaca dari cache.
    # Cache dibaca SEBELUM login supaya riwayat tetap ada walau login batal.
    acmt_lalu = {}
    cache_bulan = {}
    for bln in pt.bulan_sebelumnya(blth):
        cache = os.path.join(UNDUHAN_DIR, str(unit), bln, f"ACMT_KodeBaca_{bln}.csv")
        if bln in bulan_di_db and not os.path.exists(cache):
            continue
        cache_bulan[bln] = cache
        if os.path.exists(cache):
            try:
                acmt_lalu[bln] = _baca_csv_acmt(cache)
                log(f"  ACMT {bln}: cache ({len(acmt_lalu[bln]):,} baris)")
            except Exception as e:
                log(f"  cache ACMT {bln} rusak ({e}) - unduh ulang")

    try:
        client = _get_simba_client(progress_callback, login_event, credentials_holder)
    except (SimbaAuthError, SimbaError) as e:
        log(f"Login ACMT tidak dilakukan ({e}) - ACMT bulan ini tidak ikut")
        return None, acmt_lalu, f"login ACMT tidak dilakukan ({e})"

    try:
        if unit and client.unitup and str(client.unitup) != str(unit):
            log(f"Login ACMT unit {client.unitup}, DLPD unit {unit} - ACMT tidak ikut")
            return None, {}, f"unit ACMT {client.unitup} beda dari DLPD {unit}"

        for bln, cache in cache_bulan.items():
            _cek_batal(stop_flag)
            if bln in acmt_lalu:
                continue
            try:
                df = _unduh_acmt_bulan(client, bln, log, stop_flag)
            except (SimbaAuthError, _Dibatalkan):
                raise
            except Exception as e:
                log(f"  ACMT {bln} gagal diunduh ({e}) - riwayat bulan ini tanpa ACMT")
                continue
            acmt_lalu[bln] = df
            # Bulan kosong (mis. di luar retensi server) tidak di-cache: cache
            # kosong akan dipakai selamanya dan bulan itu tidak pernah diisi.
            if df.empty:
                log(f"  ACMT {bln} kosong - tidak di-cache")
                continue
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            df.to_csv(cache, index=False, encoding="utf-8-sig")

        # BLTH ini selalu ditarik baru - baca susulan bisa masih masuk.
        _cek_batal(stop_flag)
        try:
            acmt_ini = _unduh_acmt_bulan(client, blth, log, stop_flag)
        except (SimbaError, ValueError) as e:
            log(f"ACMT {blth} gagal diunduh ({e}) - stand 1 tidak ikut")
            return None, acmt_lalu, f"ACMT {blth} gagal diunduh ({e})"
        mentah = os.path.join(folder, f"ACMT_KodeBaca_{blth}_{stempel}.csv")
        acmt_ini.to_csv(mentah, index=False, encoding="utf-8-sig")
        log(f"  mentah ACMT {blth} disimpan: {mentah}")
        return acmt_ini, acmt_lalu, None
    except SimbaAuthError as e:
        log(f"Sesi ACMT ditolak ({e}) - stand 1 tidak ikut")
        # Token mati: lepas dari cache supaya operasi berikutnya login ulang,
        # bukan memakai sesi mati yang sama lalu gagal lagi. Tidak logout
        # (sudah tidak sah di server). Sesi yang masih hidup tetap dipakai ulang.
        _reset_sesi_simba(logout=False)
        return None, acmt_lalu, f"sesi ACMT ditolak ({e})"


def _master_pelanggan(unit, log):
    """Monitoring_Billing_Detail terbaru unit tsb (nama, alamat, kddk, gardu)."""
    pola = os.path.join(UNDUHAN_DIR, str(unit), "*", "Monitoring_Billing_Detail_*.xlsx")
    files = [f for f in glob.glob(pola) if not os.path.basename(f).startswith("~$")]
    if not files:
        log("Master pelanggan (Monitoring_Billing_Detail) tidak ada - rute dari ACMT saja")
        return None
    terbaru = max(files, key=os.path.getmtime)
    perlu = {"idpel", "nama", "alamat", "tarif", "daya", "kddk", "kdgardu", "namagardu"}
    try:
        df = pd.read_excel(terbaru, usecols=lambda c: str(c).strip().lower() in perlu)
    except Exception as e:
        log(f"Master pelanggan tidak terbaca ({e})")
        return None
    log(f"Master pelanggan: {os.path.basename(terbaru)} ({len(df):,} baris)")
    return pt.rapikan_master(df)


def _buat_pagar_terkunci(blth, unit, path_gabungan, stempel, progress_callback,
                         stop_flag, login_event, credentials_holder, kd_proses=None):
    """Bangun Daftar Pagar Terkunci dari DLPD gabungan + ACMT + database.

    Return dict ringkasan untuk messagebox "Unduh DLPD Selesai".
    """

    def log(msg):
        if progress_callback:
            progress_callback(("log", msg))

    def percent(p):
        if progress_callback:
            progress_callback(("percent", p))

    log(f"=== DAFTAR PAGAR TERKUNCI {blth} ===")
    folder = os.path.dirname(path_gabungan)
    daftar = (settings.load_unduh_settings().get("kode_akses_pagar")
              or list(pt.KODE_AKSES_DEFAULT))

    batas_baru = settings.load_rules()["pagar_stan_lalu_meter_baru"]
    dlpd = _read_excel_auto(path_gabungan)

    # Database stan baca dibaca dulu: KD BACA + STAN METER-nya adalah data
    # ACMT yang sudah tersimpan, jadi bulan yang lengkap di sana tidak perlu
    # diunduh ulang dari ACMT.
    db_sb = load_stanbaca_data(stanbaca_db_path(unit), dengan_kd_baca=True)
    bulan_di_db = set()
    if db_sb is None:
        log("Database stan baca unit ini belum ada - riwayat diunduh dari ACMT")
    else:
        hitung_bln = db_sb.groupby("BULAN").size()
        ambang = hitung_bln.median() * verification.RASIO_BULAN_MIN
        bulan_di_db = {str(b) for b, n in hitung_bln.items() if n >= ambang}
        ada = [b for b in pt.bulan_sebelumnya(blth) if b in bulan_di_db]
        log(f"Database stan baca: riwayat {len(ada)} bulan ({', '.join(sorted(ada)) or '-'})")
    _cek_batal(stop_flag)

    # ----- Unduh ACMT (sumber stand 1 DAN kode baca akses) -----
    acmt_ini, acmt_lalu, alasan = _unduh_acmt_pagar(
        blth, unit, folder, stempel, progress_callback, stop_flag,
        login_event, credentials_holder, bulan_di_db,
    )
    percent(88)
    # Kedua aturan bersumber dari ACMT. Tanpa ACMT bulan ini daftar TIDAK
    # dibuat - kelainan_bc_meter billing sengaja tidak dipakai sebagai
    # cadangan, karena isinya bisa berbeda dari kode baca ACMT untuk pelanggan
    # yang sama (billing "KWH METER TINGGI", ACMT Z/NORMAL).
    if acmt_ini is None:
        log(f"Daftar pagar terkunci TIDAK dibuat: {alasan}. Login ACMT diperlukan.")
        return {"error": f"login ACMT diperlukan - {alasan}"}

    # Cakupan = pelanggan di file DLPD, yaitu Kd Proses yang dipilih (T0 =
    # hari baca A, T1 = B, ...). Laporan ACMT selalu satu unit penuh, jadi
    # tanpa saringan ini memilih T0 tetap merekap semua hari. Riwayat tetap
    # dihitung dari data satu unit.
    idpel_dlpd = set(pt.info_dlpd(dlpd)["IDPEL"])
    n_unit = acmt_ini["IDPEL"].nunique()
    acmt_ini = acmt_ini[acmt_ini["IDPEL"].isin(idpel_dlpd)].reset_index(drop=True)
    hari = sorted(h for h in acmt_ini["KODE RBM"].str[6:7].unique() if h)
    cakupan = (f"Kd Proses {', '.join(kd_proses or []) or '-'}: "
               f"{acmt_ini['IDPEL'].nunique():,} dari {n_unit:,} pelanggan ACMT unit"
               f" (hari baca {', '.join(hari) or '-'})")
    log(f"Cakupan {cakupan}")
    if acmt_ini.empty:
        log("Daftar pagar terkunci TIDAK dibuat: tidak ada pelanggan DLPD di data ACMT")
        return {"error": "tidak ada pelanggan file DLPD di data ACMT"}

    # ----- B: kode akses = KD BACA ACMT -----
    df_kode, hitung = pt.kode_akses_acmt(acmt_ini, daftar)
    log("Kode baca ACMT bulan ini (cek ejaan):")
    for kode, n in hitung.items():
        tanda = "  <- akses" if pt.cocok_akses(pt.nama_kode_baca(kode), daftar) else ""
        log(f"  {kode}: {n:,}{tanda}")
    for k in daftar:
        if not (df_kode["KODE"] == k).any():
            log(f"  (kode akses '{k}' tidak ada bulan ini)")
    log(f"Kode akses bulan ini: {len(df_kode):,} pelanggan")

    # ----- A: stand 1 -----
    df_s1, n_baru = pt.stand1_acmt(acmt_ini, batas_baru)
    log(f"Stand 1 ACMT {blth}: {len(df_s1):,} pelanggan "
        f"({n_baru:,} meter baru STAN LALU < {batas_baru:g} tidak dilaporkan)")
    _cek_batal(stop_flag)

    # ----- Riwayat -----
    db_rek = None
    berkas = db_path(unit)
    if berkas:
        log(f"Membaca database rekening {os.path.basename(berkas)}...")
        try:
            db_rek = _read_excel_auto(berkas)[["IDPEL", "BULAN", "STAND"]]
        except Exception as e:
            log(f"  database rekening tidak terbaca ({e})")
    else:
        log("Database rekening unit ini belum ada - riwayat tanpa database rekening")
    _cek_batal(stop_flag)

    # Riwayat kode: KD BACA dari database stan baca + unduhan ACMT bulan lalu.
    acmt_isi = {b: d for b, d in acmt_lalu.items() if d is not None and not d.empty}
    ada_acmt = bulan_di_db | set(acmt_isi)
    n_acmt = len([b for b in pt.bulan_sebelumnya(blth) if b in ada_acmt])
    tanpa = [b for b in pt.bulan_sebelumnya(blth) if b not in ada_acmt]
    log(f"Riwayat kode baca ACMT: {n_acmt} bulan (database stan baca + unduhan)"
        + (f"; tanpa data: {', '.join(tanpa)}" if tanpa else ""))
    riw = pt.riwayat(blth, db_rek, db_sb, acmt_isi, daftar_acmt=daftar)
    percent(93)

    # ----- Gabung + tulis -----
    master = _master_pelanggan(unit, log)
    hasil = pt.gabung(df_s1, df_kode, acmt_ini, dlpd, master, riw)

    rbm = acmt_ini["KODE RBM"]
    biller = set(rbm[rbm.str.len() >= 6].str[3:6])
    if master is not None:
        # Hanya biller dalam cakupan Kd Proses - biller hari lain tidak perlu
        # tampil sebagai baris nol di REKAP.
        m = master[master["IDPEL"].isin(idpel_dlpd)]
        biller |= set(m["KDDK"][m["KDDK"].str.len() >= 6].str[3:6])

    t = pd.to_datetime(acmt_ini["TGL BACA"], format=pt.FORMAT_TGL_ACMT,
                       errors="coerce").max()
    tgl = t.strftime("%d/%m/%Y") if pd.notna(t) else ""

    catatan = [f"Cakupan {cakupan}",
               "Stand 1 dan kode akses dari KD BACA ACMT",
               f"Riwayat {pt.JENDELA_RIWAYAT} bulan: kode baca ACMT {n_acmt} bulan; "
               f"stand 1 dari database rekening/stan baca + ACMT",
               f"{n_baru:,} meter baru (STAN LALU < {batas_baru:g}, atur di "
               f"Pengaturan Rule) tidak dilaporkan"]

    # Di hasil/<blth>/ (bersebelahan hasil_analisa), bukan di folder unduhan:
    # ini laporan untuk dibuka operator, sedangkan unduhan berisi file mentah.
    folder_hasil = os.path.join(HASIL_DIR, str(blth))
    os.makedirs(folder_hasil, exist_ok=True)
    path = os.path.join(folder_hasil, f"Pagar_Terkunci_{unit}_{blth}_{stempel}.xlsx")
    pt.tulis_excel(hasil, path, {
        "unit": unit, "blth": blth, "tgl_baca": tgl,
        "catatan": catatan, "daftar_kode": daftar, "semua_biller": biller,
    })

    per_riwayat = hasil["RIWAYAT"].value_counts().to_dict()
    ringkas = {
        "path": path,
        "n_total": len(hasil),
        "n_stand1": int(hasil["_STAND1"].sum()),
        "n_akses": int(hasil["_KODE"].ne("").sum()),
        "n_kronis": int((hasil["KALI (TERMASUK BULAN INI)"] >= 3).sum()),
        "per_riwayat": {k: int(per_riwayat.get(k, 0)) for k in pt.URUTAN_RIWAYAT},
        "n_meter_baru": n_baru,
    }
    log(f"Daftar pagar terkunci: {ringkas['n_total']:,} pelanggan "
        f"(stand 1 {ringkas['n_stand1']:,}, kode akses {ringkas['n_akses']:,}, "
        f"kronis {ringkas['n_kronis']:,})")
    log(f"  disimpan: {path}")
    return ringkas
