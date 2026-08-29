"""
Pipeline orchestrator.

Flow:
  LOAD -> PREPARE -> ANALYZE -> SIMBA AUTH -> INFO -> DOWNLOAD -> EXPORT -> FORMAT
"""

import json
import os
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
    """Unit dari token tersimpan: billing dulu, lalu SIMBA. None kalau belum ada.

    Dipakai saat belum ada file DPM yang dipilih (mis. tombol Cek Database).
    Token billing menyimpan unitup secara eksplisit; token SIMBA hanya punya
    username berformat "44320.nama", jadi diambil awalannya.
    """
    try:
        with open(BILLING_TOKEN_FILE, "r", encoding="utf-8") as f:
            u = json.load(f).get("unitup")
        if u:
            return str(u).strip()
    except (OSError, ValueError, AttributeError):
        pass
    try:
        with open(SIMBA_TOKEN_FILE, "r", encoding="utf-8") as f:
            nama = json.load(f).get("username") or ""
        awalan = str(nama).split(".")[0].strip()
        if awalan:
            return awalan
    except (OSError, ValueError, AttributeError):
        pass
    return None


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


def _get_simba_client(
    df_anomali, blth, progress_callback, login_event, credentials_holder
):
    """Setup SIMBA client. Reuse cached token kalau valid, kalau tidak minta login GUI.

    `df_anomali` boleh None (dipakai update database, yang jalan tanpa DPM
    dimuat). Tanpa DPM tidak ada IDPEL untuk memprobe token, jadi token
    tersimpan langsung dipakai dan biar request aslinya yang melempar
    SimbaAuthError kalau ternyata sudah kedaluwarsa - caller menangkapnya,
    menghapus token, lalu meminta login ulang.
    """

    def log(msg):
        if progress_callback:
            progress_callback(("log", msg))

    client = SimbaClient(SIMBA_BASE_URL)

    # Coba pakai token tersimpan
    if client.load_token(SIMBA_TOKEN_FILE):
        log(f"Coba pakai token tersimpan ({client.username})...")

        # Probe pakai IDPEL pertama dari data anomali (atau df asal kalau kosong)
        probe_idpel = None
        if df_anomali is not None and not df_anomali.empty:
            probe_idpel = str(df_anomali["IDPEL"].iloc[0])

        if probe_idpel is None:
            log("Token dipakai tanpa probe (tidak ada IDPEL untuk diuji)")
            return client

        if client.probe(probe_idpel, blth):
            log("Token valid")
            return client

        log("Token expired atau invalid, perlu login ulang")

    # Minta login via UI
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

    if not username or not password:
        raise SimbaAuthError("Username/password kosong")

    log(f"Login ke SIMBA sebagai {username}...")
    client.login(username, password)
    client.save_token(SIMBA_TOKEN_FILE)
    log("Login SIMBA berhasil")

    return client


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

    df = compute_cabut_pasang(df, cfg)
    n_cp, n_cp_masalah = ringkasan_cabut_pasang(df)
    if n_cp:
        log(f"Cabut/pasang meter: {n_cp} pelanggan, {n_cp_masalah} stand bermasalah")

    percent(20)

    if stop_flag and stop_flag():
        log("Dibatalkan")
        return

    # Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬ FILTER UNTUK FOTO Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
    # Stand cabut/pasang yang bermasalah tetap difoto walau STATUS-nya Normal:
    # tanpa foto, pemeriksa tidak punya cara memastikan stand mana yang salah.
    mask_foto = df["STATUS"] != "Normal"
    if "MASALAH_CABUT_PASANG" in df.columns:
        mask_foto = mask_foto | (df["MASALAH_CABUT_PASANG"] != "")

    df_foto = df[mask_foto].copy()
    df_foto["IDPEL"] = df_foto["IDPEL"].astype(str)

    # Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬ SIMBA + DOWNLOAD FOTO + KLASIFIKASI Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
    results = {}
    bulan_list = []
    klasifikasi = {}

    if not ENABLE_PHOTO_DOWNLOAD:
        log("Download foto DINONAKTIFKAN (ENABLE_PHOTO_DOWNLOAD=False) - skip SIMBA & klasifikasi")
        percent(90)
    else:
        # Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬ SIMBA AUTH Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
        simba_client = _get_simba_client(
            df_foto, blth, progress_callback, login_event, credentials_holder
        )
        percent(22)

        if stop_flag and stop_flag():
            log("Dibatalkan")
            return

        # Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬ DOWNLOAD FOTO (info + download pipelined) Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
        n_target = len(df_foto)
        log(f"AMBIL DATA & FOTO DARI SIMBA ({n_target} pelanggan non-Normal)")
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

        try:
            results, bulan_list = download_photos(
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
        except SimbaAuthError as e:
            log(f"ERROR auth SIMBA: {e}")
            # Hapus token agar next run minta login
            try:
                if os.path.exists(SIMBA_TOKEN_FILE):
                    os.remove(SIMBA_TOKEN_FILE)
            except OSError:
                pass
            raise
        except SimbaError as e:
            log(f"ERROR SIMBA: {e}")
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
            log(f"  {n_missing} pelanggan TIDAK dapat foto (kemungkinan tidak ada di SIMBA)")

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
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(output_dir, f"hasil_analisa_{timestamp}.xlsx")
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
        unitup = unit_dari_token()

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


def _unduh_rekening(bulan_list, progress_callback, stop_flag,
                    billing_login_event, billing_credentials_holder, unit=None):
    """Unduh + parse export billing untuk tiap bulan. Return DataFrame gabungan."""

    def log(msg):
        if progress_callback:
            progress_callback(("log", msg))

    frames = []

    def kerja(client):
        del frames[:]
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
            save_path = os.path.join(folder, f"Monitoring_Billing_Detail_{bulan}.xlsx")
            log(f"Unduh database rekening {bulan}...")
            size = client.download_billing_detail(bulan, save_path, BILLING_EXPORT_SIZE)
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
                    login_event, credentials_holder, unit=None):
    """Unduh + parse laporan kode baca (3 kategori/bulan). Return DataFrame gabungan."""

    def log(msg):
        if progress_callback:
            progress_callback(("log", msg))

    client = _get_simba_client(
        None, bulan_list[0], progress_callback, login_event, credentials_holder
    )
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
            df = parse_kode_baca_export(raw, kdbaca)
            n_bulan_ini += len(df)
            log(f"  {kdbaca}: {len(df):,} baris")
            if not df.empty:
                frames.append(df)
        log(f"  total {bulan}: {n_bulan_ini:,} baris")

    return pd.concat(frames, ignore_index=True) if frames else None


def run_db_update(
    bulan_rekening,
    bulan_stanbaca,
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

    hasil = {"rekening": None, "stanbaca": None}
    # Unit tiap sumber dicatat terpisah: rekening dari portal billing, stan baca
    # dari SIMBA. Keduanya biasanya sama, tapi jangan diasumsikan - kalau user
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
        try:
            df = _unduh_stanbaca(
                bulan_stanbaca, progress_callback, stop_flag,
                login_event, credentials_holder, unit_sb,
            )
        except SimbaAuthError:
            _hapus_token(SIMBA_TOKEN_FILE)
            raise
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
):
    """Unduh export DLPD + DPM lalu gabungkan jadi satu file input.

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

    def kerja(client):
        """Unduh kedua export. Dipisah jadi fungsi supaya bisa diulang utuh
        setelah login ulang - token baru berarti seluruh rangkaian request
        harus dijalankan lagi, bukan disambung di tengah."""
        if stop_flag and stop_flag():
            log("Dibatalkan")
            return None

        folder = _folder_unduhan(client, blth)
        os.makedirs(folder, exist_ok=True)
        sufiks = _sufiks_kode(kd_proses)
        jalur["dlpd"] = os.path.join(
            folder, f"Monitoring_Dlpd_Detail_{blth}{sufiks}.xlsx")
        jalur["dpm"] = os.path.join(
            folder, f"Monitoring_DPM_Detail_{blth}{sufiks}.xlsx")
        jalur["keluar"] = os.path.join(
            folder, f"DLPD_{blth}{sufiks}_gabungan.xlsx")

        log(f"Unduh export DLPD {blth} (unit {client.unitap}/{client.unitup})...")
        percent(10)
        n = client.download_dlpd_detail(
            blth, kd_proses, jalur["dlpd"],
            dlpd=setelan["dlpd"],
            status_verifikasi=setelan["status_verifikasi_dlpd"],
        )
        log(f"  file DLPD diterima {n / 1048576:.1f} MB")
        percent(40)

        if stop_flag and stop_flag():
            log("Dibatalkan")
            return None

        # DPM ditarik dengan Kd Proses yang SAMA supaya setiap baris DLPD punya
        # peluang ketemu pasangannya; kalau pilihannya berbeda, sebagian baris
        # pasti tidak cocok bukan karena datanya memang tidak ada.
        log(f"Unduh export DPM {blth} (untuk kolom kelainan_bc_meter)...")
        n = client.download_dpm_detail(
            blth, kd_proses, jalur["dpm"],
            kodeposting=setelan["kodeposting_dpm"],
        )
        log(f"  file DPM diterima {n / 1048576:.1f} MB")
        percent(70)
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
    percent(100)

    return stat
