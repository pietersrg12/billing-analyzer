"""
Pipeline orchestrator.

Flow:
  LOAD -> PREPARE -> ANALYZE -> SIMBA AUTH -> INFO -> DOWNLOAD -> EXPORT -> FORMAT
"""

import os
from datetime import datetime

from config import (
    DB_FILE,
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
    SIMBA_BASE_URL,
    SIMBA_TOKEN_FILE,
    STAN_BACA_DB_FILE,
)
from core import settings, verification
from core.analyzer import (
    apply_analysis,
    compute_stanbaca_comparison,
    prepare,
)
from core.classifier import classify_all, is_available as classifier_available
from core.excel import export_excel, format_excel
from core.koreksi import tambah_saran_koreksi
from core.loader import load_data, load_stanbaca_data
from core.photo import download_photos
from core.reader import is_available as reader_available
from core.reader import read_meter_batch
from core.simba_client import SimbaAuthError, SimbaClient, SimbaError


def _get_simba_client(
    df_anomali, blth, progress_callback, login_event, credentials_holder
):
    """Setup SIMBA client. Reuse cached token kalau valid, kalau tidak minta login GUI."""

    def log(msg):
        if progress_callback:
            progress_callback(("log", msg))

    client = SimbaClient(SIMBA_BASE_URL)

    # Coba pakai token tersimpan
    if client.load_token(SIMBA_TOKEN_FILE):
        log(f"Coba pakai token tersimpan ({client.username})...")

        # Probe pakai IDPEL pertama dari data anomali (atau df asal kalau kosong)
        probe_idpel = None
        if not df_anomali.empty:
            probe_idpel = str(df_anomali["IDPEL"].iloc[0])

        if probe_idpel and client.probe(probe_idpel, blth):
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
    dpm, db = load_data(dpm_path, DB_FILE)

    stanbaca_db = None
    if ENABLE_STAN_BACA:
        stanbaca_db = load_stanbaca_data(STAN_BACA_DB_FILE)
        if stanbaca_db is None:
            log("Database stan baca tidak ditemukan/tidak valid - dilewati")
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

    percent(20)

    if stop_flag and stop_flag():
        log("Dibatalkan")
        return

    # Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬ FILTER UNTUK FOTO Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
    df_foto = df[df["STATUS"] != "Normal"].copy()
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
