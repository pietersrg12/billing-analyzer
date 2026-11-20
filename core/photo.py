"""
Photo downloader untuk SIMBA API.

Pipelined parallel:
- INFO  : POST /acmt/informasi/infopelanggan per IDPEL (return URL semua bulan)
- DOWNLOAD : GET URL foto, simpan ke foto/{BLTH}/{IDPEL}.jpg

Kedua phase berjalan BERSAMAAN: begitu info per-IDPEL selesai, URL foto-nya
langsung di-submit ke download pool tanpa menunggu seluruh info batch kelar.

Photo file is shared between runs because struktur folder per BLTH foto
(bukan per BLTH input). Kalau file sudah ada DAN benar-benar gambar, skip;
file yang bukan gambar dihapus lalu diunduh ulang (lihat _foto_valid).
"""

import os
import time
from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
    wait as wait_futures,
    FIRST_COMPLETED,
)
from datetime import datetime

from dateutil.relativedelta import relativedelta

from core.simba_client import SimbaAuthError, SimbaError, adalah_gambar


def build_bulan_list(blth, n):
    """Return list n BLTH ke belakang, terbaru dulu (index 0 = blth)."""
    dt = datetime.strptime(blth, "%Y%m")
    return [(dt - relativedelta(months=i)).strftime("%Y%m") for i in range(n)]


def _foto_path(foto_dir, blth, idpel):
    return os.path.join(foto_dir, blth, f"{idpel}.jpg")


def _foto_valid(path):
    """True kalau file foto ada dan benar-benar gambar.

    File yang ada tapi bukan gambar - mis. amplop JSON 432 byte yang tersimpan
    sebagai .jpg sebelum download_foto mengikuti `urlPhoto` - dihapus supaya
    diunduh ulang. Kalau hanya dicek keberadaannya, cache melewatinya selamanya
    dan format_excel gagal saat menyisipkannya.
    """
    try:
        with open(path, "rb") as f:
            awal = f.read(4)
    except OSError:
        return False
    if adalah_gambar(awal):
        return True
    try:
        os.remove(path)
    except OSError:
        pass
    return False


def download_photos(
    df,
    simba_client,
    blth,
    foto_dir,
    jumlah_bulan,
    workers_info,
    workers_download,
    progress_callback=None,
    stop_flag=None,
):

    bulan_list = build_bulan_list(blth, jumlah_bulan)
    idpels = list(dict.fromkeys(df["IDPEL"].astype(str)))  # unique, preserve order

    # Map idpel -> {blth_foto: filepath} untuk file yang sudah ada di disk
    existing_map = {}

    # Pre-scan disk: kalau semua file untuk IDPEL sudah ada, skip API call
    api_idpels = []
    for idpel in idpels:
        existing = {}
        for b in bulan_list:
            p = _foto_path(foto_dir, b, idpel)
            if _foto_valid(p):
                existing[b] = p
        existing_map[idpel] = existing
        if len(existing) != len(bulan_list):
            api_idpels.append(idpel)

    # ────────────────────────────────────────────────
    # PIPELINED: INFO + DOWNLOAD jalan bersamaan
    # ────────────────────────────────────────────────

    info_total = len(api_idpels)
    info_done = 0
    info_start = time.time()

    dl_total = 0   # bertambah saat info selesai dan menemukan URL valid
    dl_done = 0
    dl_ok = 0
    dl_fail = 0
    dl_start = None  # set saat task download pertama disubmit

    auth_failed_info = False
    auth_failed_dl = False

    def fetch_info(idpel):
        try:
            records = simba_client.get_info_pelanggan(idpel, blth)
        except SimbaAuthError:
            return idpel, None, "auth"
        except SimbaError:
            return idpel, None, "error"
        except Exception:
            return idpel, None, "error"
        return idpel, records, None

    def do_download(task):
        idpel, b, url, path = task
        try:
            ok = simba_client.download_foto(url, path)
        except SimbaAuthError:
            return idpel, b, None, "auth"
        except Exception:
            return idpel, b, None, "error"
        return idpel, b, path if ok else None, None if ok else "fail"

    def emit_progress():
        if not progress_callback:
            return
        elapsed_info = time.time() - info_start
        info_rate = info_done / elapsed_info if elapsed_info > 0 else 0
        info_remaining = (info_total - info_done) / info_rate if info_rate > 0 else 0

        elapsed_dl = (time.time() - dl_start) if dl_start else 0
        dl_rate = dl_done / elapsed_dl if elapsed_dl > 0 else 0
        dl_remaining = (dl_total - dl_done) / dl_rate if dl_rate > 0 else 0

        progress_callback({
            "info_done": info_done,
            "info_total": info_total,
            "dl_done": dl_done,
            "dl_total": dl_total,
            "dl_ok": dl_ok,
            "dl_fail": dl_fail,
            "eta_info": int(info_remaining),
            "eta_dl": int(dl_remaining),
        })

    if api_idpels:
        # 2 pool terpisah supaya info & download tidak berebut worker slot.
        # Connection pool di SimbaClient (size 100) cukup untuk keduanya.
        info_pool = ThreadPoolExecutor(
            max_workers=workers_info, thread_name_prefix="info"
        )
        dl_pool = ThreadPoolExecutor(
            max_workers=workers_download, thread_name_prefix="dl"
        )

        # Single as_completed loop: gabung info + download futures.
        # Saat info selesai → submit dl tasks ke dl_pool, masuk ke pending set.
        # Saat dl selesai → update counter.
        # Loop berhenti setelah info_done == info_total DAN dl_done == dl_total.
        pending = set()
        future_kind = {}  # future -> ('info', None) atau ('dl', None)

        try:
            for ip in api_idpels:
                f = info_pool.submit(fetch_info, ip)
                pending.add(f)
                future_kind[f] = "info"

            while pending:
                if stop_flag and stop_flag():
                    for f in pending:
                        f.cancel()
                    return {}, bulan_list

                # FIRST_COMPLETED: blocking sampai minimal 1 future selesai.
                # Mendukung penambahan future dinamis (download tasks) di tiap iterasi.
                done_set, _ = wait_futures(pending, return_when=FIRST_COMPLETED)

                for fut in done_set:
                    pending.discard(fut)
                    kind = future_kind.pop(fut, None)

                    if kind == "info":
                        if fut.cancelled():
                            info_done += 1
                            continue
                        try:
                            idpel, records, err = fut.result()
                        except Exception:
                            info_done += 1
                            continue

                        info_done += 1

                        if err == "auth":
                            auth_failed_info = True
                            # Cancel sisa info yang belum jalan
                            for p in list(pending):
                                if future_kind.get(p) == "info":
                                    p.cancel()
                                    pending.discard(p)
                                    future_kind.pop(p, None)
                            continue

                        if records is not None:
                            rec_by_blth = {
                                r.get("blth"): r for r in records if r.get("blth")
                            }
                            for b in bulan_list:
                                rec = rec_by_blth.get(b)
                                if not rec:
                                    continue
                                url = simba_client.extract_first_foto_url(rec)
                                if not url:
                                    continue
                                target_path = _foto_path(foto_dir, b, idpel)
                                if _foto_valid(target_path):
                                    existing_map.setdefault(idpel, {})[b] = target_path
                                    continue
                                if dl_start is None:
                                    dl_start = time.time()
                                dl_total += 1
                                dl_fut = dl_pool.submit(
                                    do_download, (idpel, b, url, target_path)
                                )
                                pending.add(dl_fut)
                                future_kind[dl_fut] = "dl"

                    elif kind == "dl":
                        if fut.cancelled():
                            dl_done += 1
                            dl_fail += 1
                            continue
                        try:
                            idpel, b, path, err = fut.result()
                        except Exception:
                            dl_done += 1
                            dl_fail += 1
                            continue

                        dl_done += 1
                        if path:
                            dl_ok += 1
                            existing_map.setdefault(idpel, {})[b] = path
                        else:
                            dl_fail += 1
                            if err == "auth":
                                auth_failed_dl = True
                                # Stop submit baru
                                for p in list(pending):
                                    if future_kind.get(p) == "info":
                                        p.cancel()
                                        pending.discard(p)
                                        future_kind.pop(p, None)

                emit_progress()
        finally:
            info_pool.shutdown(wait=False)
            dl_pool.shutdown(wait=True)

    if auth_failed_info:
        raise SimbaAuthError("Token expired saat fetch infopelanggan")
    if auth_failed_dl:
        raise SimbaAuthError("Token expired saat download foto")

    # ────────────────────────────────────────────────
    # FORMAT OUTPUT untuk excel.py
    # results[idpel][idx_1based] = filepath
    # idx 1 = bulan_list[0] = BLTH terbaru
    # ────────────────────────────────────────────────

    results = {}
    for idpel, m in existing_map.items():
        per_idx = {}
        for i, b in enumerate(bulan_list, start=1):
            p = m.get(b)
            if p and _foto_valid(p):
                per_idx[i] = p
        if per_idx:
            results[idpel] = per_idx

    return results, bulan_list
