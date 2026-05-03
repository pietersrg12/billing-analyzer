import os
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from dateutil.relativedelta import relativedelta

from config import FOTO_DIR


def build_bulan_list(blth):
    dt = datetime.strptime(blth, "%Y%m")
    return [(dt - relativedelta(months=i)).strftime("%Y%m") for i in range(3)]


def download_photos(
    df,
    session,
    base_url,
    foto_dir,
    blth,
    max_workers,
    progress_callback=None,
    stop_flag=None,
    max_retry=3
):

    os.makedirs(foto_dir, exist_ok=True)
    bulan_list = build_bulan_list(blth)

    def task(args):
        idpel, blth, idx = args

        # Path format: foto/BLTH/IDPEL.jpg
        # Cek folder sesuai periode blth masing-masing
        target_dir = os.path.join(FOTO_DIR, blth)
        path = os.path.join(target_dir, f"{idpel}.jpg")

        if os.path.exists(path):
            return (idpel, idx, path)

        # Pastikan folder ada sebelum download
        os.makedirs(target_dir, exist_ok=True)

        for _ in range(max_retry):
            try:
                r = session.get(base_url, params={
                    "idpel": idpel,
                    "fotoke": 1,
                    "blth": blth
                }, timeout=6)

                ct = r.headers.get("Content-Type","")
                if "image" in ct and len(r.content) > 4000:
                    with open(path, "wb") as f:
                        f.write(r.content)
                    return (idpel, idx, path)
            except:
                time.sleep(0.5)

        return (idpel, idx, None)

    tasks = [(idpel, b, i+1)
             for idpel in df["IDPEL"]
             for i, b in enumerate(bulan_list)]

    total = len(tasks)
    done = 0
    start_time = time.time()

    results = {}

    with ThreadPoolExecutor(max_workers) as exe:
        futures = [exe.submit(task, t) for t in tasks]

        for f in as_completed(futures):

            if stop_flag and stop_flag():
                return {}, bulan_list  # cancel

            idpel, idx, path = f.result()

            if path:
                results.setdefault(idpel, {})[idx] = path

            done += 1

            if progress_callback:
                elapsed = time.time() - start_time
                rate = done / elapsed if elapsed > 0 else 0
                remaining = (total - done) / rate if rate > 0 else 0

                progress_callback({
                    "type": "photo",
                    "done": done,
                    "total": total,
                    "eta": int(remaining)
                })

    return results, bulan_list