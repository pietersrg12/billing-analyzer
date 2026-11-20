"""
Cari meter digital (LCD) di seluruh pelanggan unit lewat foto ACMT.

Foto diunduh ke folder temp, dipilah, lalu langsung dihapus. Yang disimpan
HANYA foto meter LCD (semua bulan yang tersedia), supaya disk tidak menumpuk
oleh ±20 ribu foto meter mekanik.

Pemilah: digit_v7 (kelas 10 = "desimal" LCD) pada crop display. Diuji pada
156 LCD terverifikasi + 300 foto mekanik: skor >= 0.3 menangkap 100% LCD dan
meloloskan 0.3% mekanik. Ambang dibuat 0.2 (lebih longgar); salah tangkap
tetap tersaring saat cek mata label_lcd.py.

Default: pelanggan di ACMT_KodeBaca BLTH terbaru yang BELUM punya foto di
foto/ (billing v.2 + v3), karena foto lokal sudah dipindai label_lcd.py.

    python tools/ml/cari_lcd_acmt.py [--blth 202610] [--semua] [--limit N]
    python tools/ml/cari_lcd_acmt.py --lokal   -> pilah foto yang SUDAH di disk
                                                  (tanpa login), hasil lokal.csv

Login ACMT lewat jendela kecil (username, password, kode enkripsi), logout
di akhir. Bisa dilanjutkan: IDPEL yang sudah ada di hasil.csv dilewati.
Berhenti dengan rapi: buat file STOP di folder keluaran.

Hasil: ml_data/lcd_acmt/foto/<BLTH>/<IDPEL>.jpg + hasil.csv
"""
import argparse
import csv
import glob
import os
import shutil
import sys
import tempfile
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from config import SIMBA_BASE_URL  # noqa: E402
from core import reader  # noqa: E402
from core.simba_client import SimbaAuthError, SimbaClient, SimbaError  # noqa: E402

UNIT = "44320"
OUT = os.path.join(ROOT, "ml_data", "lcd_acmt")
CSV = os.path.join(OUT, "hasil.csv")
STOP = os.path.join(OUT, "STOP")
MODEL = os.path.join(ROOT, "ml_data", "digit_v7", "digit_v7", "weights", "best.pt")
DISPLAY = os.path.join(ROOT, "model", "display_detector.pt")
FOTO_LOKAL = [r"D:\python\billing v.2\foto", os.path.join(ROOT, "foto")]
AMBANG = 0.2
KELAS_DESIMAL = 10
WORKER = 8
ANTRIAN = 24   # foto temp yang menunggu dipilah; dibatasi supaya temp tidak menumpuk
KOLOM = ["idpel", "status", "skor", "blth_foto", "n_simpan"]


def minta_login():
    """Jendela login kecil. Return (username, password, kode) atau None."""
    import tkinter as tk

    hasil = {}
    w = tk.Tk()
    w.title("Login ACMT - cari meter LCD")
    w.attributes("-topmost", True)
    v = [tk.StringVar() for _ in range(3)]
    for i, (lbl, show) in enumerate((("Username", ""), ("Password", "*"), ("Kode Enkripsi", "*"))):
        tk.Label(w, text=lbl).grid(row=i, column=0, sticky="w", padx=8, pady=4)
        tk.Entry(w, textvariable=v[i], show=show, width=44).grid(row=i, column=1, padx=8, pady=4)

    def ok():
        hasil["x"] = tuple(x.get().strip() for x in v)
        w.destroy()

    tk.Button(w, text="Login", command=ok, width=12).grid(row=3, column=1, sticky="e", padx=8, pady=8)
    w.mainloop()
    x = hasil.get("x")
    return x if x and all(x) else None


def daftar_idpel(blth, semua):
    f = sorted(glob.glob(os.path.join(ROOT, "unduhan", UNIT, blth, f"ACMT_KodeBaca_{blth}*.csv")))
    if not f:
        sys.exit(f"tidak ada ACMT_KodeBaca untuk {blth}")
    idpel = set(pd.read_csv(f[-1], dtype={"IDPEL": str}, usecols=["IDPEL"]).IDPEL)
    if not semua:
        ada = {os.path.basename(p)[:-4] for d in FOTO_LOKAL for p in glob.glob(os.path.join(d, "*", "*.jpg"))}
        idpel -= ada
    if os.path.exists(CSV):
        idpel -= set(pd.read_csv(CSV, dtype=str).idpel)
    return sorted(idpel)


def skor_lcd(path):
    """Conf tertinggi kelas desimal di crop display (0 = tidak ada)."""
    import cv2
    img = cv2.imread(path)
    if img is None:
        return None
    box = reader._get_display_bbox(path, DISPLAY)
    src = reader._prepare_crop(img, box) if box else img
    if src is None:
        src = img
    r = reader._load_model(MODEL).predict(src, conf=0.1, imgsz=640, verbose=False, device="cpu")[0]
    return max([c for k, c in zip(r.boxes.cls.tolist(), r.boxes.conf.tolist()) if int(k) == KELAS_DESIMAL],
               default=0.0)


def pilah_lokal():
    """Foto terbaru tiap pelanggan di FOTO_LOKAL -> lokal.csv. Tidak mengunduh.

    Foto lokal sudah dilabel label_lcd.py, tetapi di sana LCD hanya dikenali
    bila labelnya sekaligus berhasil; LCD yang salah dibaca v7 tercatat
    "jumlah_beda". Daftar ini menandai pelanggan LCD-nya secara langsung.
    """
    keluar = os.path.join(OUT, "lokal.csv")
    terbaru = {}
    for d in FOTO_LOKAL:
        for p in glob.glob(os.path.join(d, "*", "*.jpg")):
            b, i = os.path.basename(os.path.dirname(p)), os.path.basename(p)[:-4]
            if b.isdigit() and b > terbaru.get(i, ("",))[0]:
                terbaru[i] = (b, p)
    sudah = set(pd.read_csv(keluar, dtype=str).idpel) if os.path.exists(keluar) else set()
    antre = sorted(set(terbaru) - sudah)
    print(f"pelanggan dengan foto lokal: {len(terbaru)}, akan dipilah: {len(antre)}", flush=True)
    reader._load_model(MODEL)
    baru = not os.path.exists(keluar)
    n_lcd = 0
    t0 = time.time()
    with open(keluar, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["idpel", "status", "skor", "blth_foto"])
        if baru:
            w.writeheader()
        for k, i in enumerate(antre, 1):
            b, p = terbaru[i]
            s = skor_lcd(p)
            lcd = s is not None and s >= AMBANG
            n_lcd += lcd
            w.writerow(dict(idpel=i, status="lcd" if lcd else ("bukan_lcd" if s is not None else "rusak"),
                            skor="" if s is None else round(s, 3), blth_foto=b))
            if k % 500 == 0:
                f.flush()
                sisa = (len(antre) - k) / (k / (time.time() - t0)) / 60
                print(f"{k}/{len(antre)}  LCD {n_lcd}  ~{sisa:.0f} menit lagi", flush=True)
    print(f"selesai: LCD {n_lcd} dari {len(antre)} -> {keluar}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blth", default="202610")
    ap.add_argument("--semua", action="store_true", help="termasuk pelanggan yang sudah punya foto lokal")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--lokal", action="store_true", help="pilah foto lokal saja, tanpa login/unduh")
    a = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    if a.lokal:
        return pilah_lokal()
    if os.path.exists(STOP):
        os.remove(STOP)
    idpel = daftar_idpel(a.blth, a.semua)
    if a.limit:
        idpel = idpel[:a.limit]
    print(f"akan diperiksa: {len(idpel)} pelanggan", flush=True)
    if not idpel:
        return

    kred = minta_login()
    if not kred:
        sys.exit("login dibatalkan")
    klien = SimbaClient(SIMBA_BASE_URL)
    klien.login(*kred)
    print(f"login ACMT ok (unit {klien.unitup})", flush=True)
    reader._load_model(MODEL)

    tmp = tempfile.mkdtemp(prefix="cari_lcd_")

    def ambil(i):
        """info + unduh foto terbaru ke temp. Return (idpel, status, records, path)."""
        try:
            rec = klien.get_info_pelanggan(i, a.blth)
        except SimbaAuthError:
            return i, "auth", None, None
        except (SimbaError, Exception):
            return i, "error_info", None, None
        rec = sorted([r for r in rec if r.get("blth") and klien.extract_first_foto_url(r)],
                     key=lambda r: r["blth"], reverse=True)
        if not rec:
            return i, "tanpa_foto", None, None
        p = os.path.join(tmp, f"{i}.jpg")
        try:
            ok = klien.download_foto(klien.extract_first_foto_url(rec[0]), p)
        except SimbaAuthError:
            return i, "auth", None, None
        except Exception:
            ok = False
        return (i, "ok", rec, p) if ok else (i, "gagal_unduh", None, None)

    baru = not os.path.exists(CSV)
    n = {"lcd": 0, "bukan": 0, "lain": 0}
    t0 = time.time()
    try:
        with open(CSV, "a", newline="", encoding="utf-8") as fcsv, ThreadPoolExecutor(WORKER) as pool:
            w = csv.DictWriter(fcsv, fieldnames=KOLOM)
            if baru:
                w.writeheader()
            antre = iter(idpel)
            jalan = set()
            selesai = 0
            berhenti = False
            while True:
                while not berhenti and len(jalan) < ANTRIAN:
                    i = next(antre, None)
                    if i is None:
                        break
                    jalan.add(pool.submit(ambil, i))
                if not jalan:
                    break
                beres, jalan = wait(jalan, return_when=FIRST_COMPLETED)
                for fut in beres:
                    i, st, rec, p = fut.result()
                    selesai += 1
                    if st == "auth":
                        print("token ACMT tidak berlaku lagi - berhenti", flush=True)
                        berhenti = True
                        continue
                    baris = dict(idpel=i, status=st, skor="", blth_foto="", n_simpan=0)
                    if st == "ok":
                        s = skor_lcd(p)
                        baris["skor"] = "" if s is None else round(s, 3)
                        baris["blth_foto"] = rec[0]["blth"]
                        if s is not None and s >= AMBANG:
                            baris["status"] = "lcd"
                            n["lcd"] += 1
                            # meter LCD: simpan semua bulan (stand berbeda = label berbeda)
                            for r in rec:
                                tujuan = os.path.join(OUT, "foto", r["blth"], f"{i}.jpg")
                                os.makedirs(os.path.dirname(tujuan), exist_ok=True)
                                if r is rec[0]:
                                    shutil.move(p, tujuan)
                                    baris["n_simpan"] += 1
                                elif klien.download_foto(klien.extract_first_foto_url(r), tujuan):
                                    baris["n_simpan"] += 1
                        else:
                            baris["status"] = "bukan_lcd"
                            n["bukan"] += 1
                        if os.path.exists(p):
                            os.remove(p)
                    else:
                        n["lain"] += 1
                    w.writerow(baris)
                    if selesai % 200 == 0:
                        fcsv.flush()
                        laju = selesai / (time.time() - t0)
                        sisa = (len(idpel) - selesai) / laju / 60
                        print(f"{selesai}/{len(idpel)}  LCD {n['lcd']}  bukan {n['bukan']}  "
                              f"lain {n['lain']}  ~{sisa:.0f} menit lagi", flush=True)
                    if os.path.exists(STOP):
                        print("file STOP ditemukan - berhenti", flush=True)
                        berhenti = True
    finally:
        ok, pesan = klien.logout()
        print(f"logout ACMT: {pesan}", flush=True)
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"selesai: LCD {n['lcd']}, bukan LCD {n['bukan']}, lain {n['lain']} -> {OUT}", flush=True)


if __name__ == "__main__":
    main()
