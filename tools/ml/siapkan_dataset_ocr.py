"""
Label otomatis dataset OCR stand meter dari foto + ACMT.

Model lama (display_detector + digit_detector) dijalankan pada setiap foto
yang punya STAN METER ACMT. Kotak digitnya dipakai, angkanya dicocokkan dengan
ACMT:
  persis          semua kotak = digit hitam, cocok dengan STAN METER (zfill)
  merah           kotak terakhir = drum desimal merah, sisanya cocok
  koreksi1(_m)    panjang cocok, beda tepat 1 digit -> label diambil dari ACMT
  beda / gagal    tidak dipakai untuk training, masuk daftar periksa

Drum desimal merah TIDAK PERNAH dilabeli (= latar). Detector lama kadang
melihatnya, kadang tidak; memberinya kelas sendiri membuat objek yang sama
berlabel di satu foto dan tidak berlabel di foto lain. Stand yang dicari
hanya digit hitam, jadi model baru cukup belajar mengabaikannya.

Hasil: ml_data/ocr_v1/crops/*.jpg, labels/*.txt (YOLO, kelas 0-9),
hasil.csv (bisa dilanjutkan - baris yang sudah ada dilewati).

    python tools/ml/siapkan_dataset_ocr.py [--limit N]
"""
import argparse
import csv
import glob
import os
import sys

import cv2
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from core import reader  # noqa: E402

FOTO_ROOTS = [r"D:\python\billing v.2\foto", os.path.join(ROOT, "foto"),
              # meter LCD hasil tools/ml/cari_lcd_acmt.py (pelanggan tanpa foto lokal)
              os.path.join(ROOT, "ml_data", "lcd_acmt", "foto")]
ACMT_GLOB = os.path.join(ROOT, "unduhan", "*", "*", "ACMT_KodeBaca_*.csv")
OUT = os.path.join(ROOT, "ml_data", "ocr_v1")
DESIMAL = None  # penanda kotak drum merah: tidak ditulis ke label
KOLOM = ["key", "IDPEL", "BLTH", "path", "kd_baca", "stan", "ocr", "n_box",
         "n_hitam", "merah_akhir", "status", "conf", "crop"]


def inventaris():
    rows = {}
    for root in FOTO_ROOTS:
        for d in sorted(os.listdir(root)):
            p = os.path.join(root, d)
            if not (d.isdigit() and os.path.isdir(p)):
                continue
            for f in os.listdir(p):
                if f.lower().endswith(".jpg"):
                    rows.setdefault((d, f[:-4]), os.path.join(p, f))
    df = pd.DataFrame([(b, i, p) for (b, i), p in rows.items()],
                      columns=["BLTH", "IDPEL", "path"])
    acmt = pd.concat(pd.read_csv(f, dtype={"IDPEL": str, "BLTH": str},
                                 usecols=["IDPEL", "BLTH", "KD BACA", "STAN METER"])
                     for f in sorted(glob.glob(ACMT_GLOB)))
    acmt = acmt.drop_duplicates(["IDPEL", "BLTH"], keep="last")
    m = df.merge(acmt, on=["IDPEL", "BLTH"], how="inner")
    return m[m["STAN METER"] > 1].reset_index(drop=True)


def kemerahan(img, x1, y1, x2, y2):
    """Fraksi piksel merah (drum desimal) di dalam kotak."""
    h, w = img.shape[:2]
    x1, x2 = max(0, int(x1)), min(w, int(x2))
    y1, y2 = max(0, int(y1)), min(h, int(y2))
    if x2 <= x1 or y2 <= y1:
        return 0.0
    hsv = cv2.cvtColor(img[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
    hh, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    red = ((hh < 10) | (hh > 165)) & (s > 90) & (v > 60)
    return float(red.mean())


def beda_satu(a, b):
    return len(a) == len(b) and sum(x != y for x, y in zip(a, b)) == 1


def cocokkan(digits, merah_akhir, target):
    """-> (status, label per kotak) ; drum merah berlabel DESIMAL."""
    s = "".join(digits)
    n = len(s)
    if n == 0:
        return "gagal", None
    if len(target) <= n and target.zfill(n) == s and not merah_akhir:
        return "persis", [int(c) for c in s]
    if n >= 2 and len(target) <= n - 1 and target.zfill(n - 1) == s[:-1]:
        return "merah", [int(c) for c in s[:-1]] + [DESIMAL]
    if n >= 2 and merah_akhir and len(target) <= n - 1 and beda_satu(target.zfill(n - 1), s[:-1]):
        return "koreksi1_m", [int(c) for c in target.zfill(n - 1)] + [DESIMAL]
    if len(target) <= n and beda_satu(target.zfill(n), s) and not merah_akhir:
        return "koreksi1", [int(c) for c in target.zfill(n)]
    if len(target) <= n and target.zfill(n) == s:  # cocok tapi kotak akhir kemerahan
        return "persis_ragu", None
    return "beda", None


def proses(r, digit_model, display_path):
    img = cv2.imread(r.path)
    if img is None:
        return dict(status="gagal")
    box = reader._get_display_bbox(r.path, display_path)
    if not box:
        return dict(status="gagal")
    crop = reader._prepare_crop(img, box)
    if crop is None:
        return dict(status="gagal")
    row = (reader._run_digit_inference(digit_model, crop, 0.25, 0.45, 640)
           or reader._run_digit_inference(digit_model, crop, 0.12, 0.45, 640) or [])
    digits = [str(d["class"]) for d in row]
    merah = [kemerahan(crop, d["x1"], d["y1"], d["x2"], d["y2"]) for d in row]
    merah_akhir = bool(merah) and merah[-1] > 0.2
    status, labels = cocokkan(digits, merah_akhir, str(int(r.STAN)))
    # koreksi1 dengan drum merah di kanan kotak terakhir: sering kali detector
    # melewatkan satu digit hitam dan membaca drum merah sebagai digit, jadi
    # label dari ACMT akan jatuh ke kotak yang salah. (persis tetap aman: drum
    # merah yang tak terdeteksi memang latar.)
    if status == "koreksi1" and row:
        d = row[-1]
        w = d["x2"] - d["x1"]
        if kemerahan(crop, d["x2"], d["y1"], d["x2"] + 1.3 * w, d["y2"]) > 0.25:
            status, labels = status + "_merahhilang", None
    nama = f"{r.BLTH}_{r.IDPEL}"
    crop_path = os.path.join(OUT, "crops", nama + ".jpg")
    cv2.imwrite(crop_path, crop, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if labels:
        H, W = crop.shape[:2]
        with open(os.path.join(OUT, "labels", nama + ".txt"), "w") as f:
            for d, c in zip(row, labels):
                if c is DESIMAL:
                    continue
                cx = (d["x1"] + d["x2"]) / 2 / W
                cy = (d["y1"] + d["y2"]) / 2 / H
                f.write(f"{c} {cx:.6f} {cy:.6f} {(d['x2'] - d['x1']) / W:.6f} "
                        f"{(d['y2'] - d['y1']) / H:.6f}\n")
    n_desimal = 1 if labels and labels[-1] is DESIMAL else 0
    return dict(ocr="".join(digits), n_box=len(row), n_hitam=len(row) - n_desimal,
                merah_akhir=int(merah_akhir), status=status,
                conf=round(float(np.mean([d["confidence"] for d in row])), 3) if row else 0,
                crop=crop_path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    os.makedirs(os.path.join(OUT, "crops"), exist_ok=True)
    os.makedirs(os.path.join(OUT, "labels"), exist_ok=True)
    data = inventaris().rename(columns={"STAN METER": "STAN", "KD BACA": "KD"})
    data = data.sample(frac=1, random_state=0)  # acak: --limit jadi sampel representatif
    if a.limit:
        data = data.head(a.limit)
    hasil_csv = os.path.join(OUT, "hasil.csv")
    sudah = set()
    if os.path.exists(hasil_csv):
        sudah = set(pd.read_csv(hasil_csv, usecols=["key"], dtype=str)["key"])
    data = data[~(data.BLTH + "_" + data.IDPEL).isin(sudah)]
    print(f"diproses: {len(data)} foto (sudah: {len(sudah)})", flush=True)
    digit_model = reader._load_model(os.path.join(ROOT, "model", "digit_detector.pt"))
    display_path = os.path.join(ROOT, "model", "display_detector.pt")
    baru = not os.path.exists(hasil_csv)
    with open(hasil_csv, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=KOLOM)
        if baru:
            w.writeheader()
        for i, r in enumerate(data.itertuples(index=False), 1):
            try:
                hasil = proses(r, digit_model, display_path)
            except Exception as e:  # satu foto rusak tidak menghentikan semuanya
                hasil = dict(status=f"error:{type(e).__name__}")
            w.writerow(dict(key=f"{r.BLTH}_{r.IDPEL}", IDPEL=r.IDPEL, BLTH=r.BLTH,
                            path=r.path, kd_baca=r.KD, stan=int(r.STAN), **hasil))
            if i % 200 == 0:
                f.flush()
                print(f"{i}/{len(data)}", flush=True)
    print("selesai", flush=True)


if __name__ == "__main__":
    main()
