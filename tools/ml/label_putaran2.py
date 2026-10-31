"""
Putaran 2 label otomatis: jalankan model hasil putaran 1 (digit_v6) pada foto
yang BELUM dipakai training (status beda / koreksi1_merahhilang / persis_ragu,
atau jumlah digit di luar 5-6), lalu cocokkan lagi dengan ACMT.

Tujuan utama: meter LCD (Melcoinda MTS-237, Smartmeter SMI-710, ...). Layarnya
menampilkan 2 angka desimal ("35.95") sedangkan ACMT mencatat angka bulat (35),
jadi di putaran 1 hampir semua LCD jatuh ke "beda" dan tidak pernah dilatih.

Digit desimal LCD diberi SATU kelas sendiri: 10 ("desimal"); nilainya tidak\nperlu karena reader membuangnya.
Bentuknya sama persis dengan digit biasa, yang membedakan hanya posisinya
sesudah titik, jadi model harus belajar dari konteks. Reader cukup membuang
kelas >= 10 untuk mendapat stand. Drum merah meter mekanik tetap TIDAK
dilabeli (= latar), sama seperti putaran 1, supaya label lama tetap konsisten.

Status:
  persis      cocok ACMT, kotak terakhir tidak merah
  merah       kotak terakhir drum merah, sisanya cocok (merah tidak dilabeli)
  lcd2        tanpa merah, digit[:-2] == ACMT -> 2 kotak akhir kelas 10
  koreksi1    panjang sama, beda tepat 1 digit (label dari ACMT; mekanik saja)
  desimal1    digit[:-1] == ACMT tanpa merah: LCD 1 desimal atau mekanik?
              ragu -> tidak dipakai
  beda/gagal  tidak dipakai

Crop display diambil dari putaran 1 (ocr_v1/crops), jadi tidak perlu
display detector lagi. Hasil: ml_data/ocr_v2/labels/*.txt + hasil.csv
(bisa dilanjutkan).

    python tools/ml/label_putaran2.py --model ml_data/digit_v6/weights/best.pt [--limit N]
"""
import argparse
import csv
import os
import sys

import cv2
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
from core import reader  # noqa: E402
from siapkan_dataset_ocr import kemerahan, beda_satu  # noqa: E402

SRC = os.path.join(ROOT, "ml_data", "ocr_v1")
OUT = os.path.join(ROOT, "ml_data", "ocr_v2")
STATUS_PAKAI_V1 = {"persis", "merah", "koreksi1", "koreksi1_m"}
KELAS_DESIMAL = 10
KOLOM = ["key", "status2", "ocr2", "n_box", "n_label", "n_desimal", "conf_min", "merah_akhir"]


def cocokkan(s, merah_akhir, target):
    """-> (status, kelas per kotak; None = tidak dilabeli)."""
    n = len(s)
    if n == 0:
        return "gagal", None
    t = target.lstrip("0") or "0"
    bulat = lambda x: x.lstrip("0") or "0"  # noqa: E731
    if bulat(s) == t and not merah_akhir:
        return "persis", [int(c) for c in s]
    if n >= 2 and merah_akhir and bulat(s[:-1]) == t:
        return "merah", [int(c) for c in s[:-1]] + [None]
    if n >= 3 and not merah_akhir and bulat(s[:-2]) == t:
        return "lcd2", [int(c) for c in s[:-2]] + [KELAS_DESIMAL, KELAS_DESIMAL]
    if n >= 2 and not merah_akhir and bulat(s[:-1]) == t:
        return "desimal1", None
    if not merah_akhir and len(t) <= n and beda_satu(t.zfill(n), s):
        return "koreksi1", [int(c) for c in t.zfill(n)]
    return "beda", None


def proses(r, model):
    crop = cv2.imread(r.crop)
    if crop is None:
        return dict(status2="gagal")
    row = (reader._run_digit_inference(model, crop, 0.25, 0.45, 640)
           or reader._run_digit_inference(model, crop, 0.12, 0.45, 640) or [])
    s = "".join(str(d["class"]) for d in row)
    merah_akhir = bool(row) and kemerahan(crop, row[-1]["x1"], row[-1]["y1"],
                                          row[-1]["x2"], row[-1]["y2"]) > 0.2
    status, kelas = cocokkan(s, merah_akhir, str(int(r.stan)))
    n_label = n_des = 0
    if kelas:
        H, W = crop.shape[:2]
        with open(os.path.join(OUT, "labels", r.key + ".txt"), "w") as f:
            for d, c in zip(row, kelas):
                if c is None:
                    continue
                n_label += 1
                n_des += c >= KELAS_DESIMAL
                f.write(f"{c} {(d['x1'] + d['x2']) / 2 / W:.6f} {(d['y1'] + d['y2']) / 2 / H:.6f} "
                        f"{(d['x2'] - d['x1']) / W:.6f} {(d['y2'] - d['y1']) / H:.6f}\n")
    return dict(status2=status, ocr2=s, n_box=len(row), n_label=n_label, n_desimal=n_des,
                conf_min=round(min(d["confidence"] for d in row), 3) if row else 0,
                merah_akhir=int(merah_akhir))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    os.makedirs(os.path.join(OUT, "labels"), exist_ok=True)

    d = pd.read_csv(os.path.join(SRC, "hasil.csv"), dtype=str)
    sudah_dilatih = d.status.isin(STATUS_PAKAI_V1) & d.n_hitam.isin(["5", "6"])
    d = d[d.kd_baca.isin(["Z", "F"]) & d.crop.notna() & ~sudah_dilatih]
    d = d.sample(frac=1, random_state=0)
    if a.limit:
        d = d.head(a.limit)
    hasil_csv = os.path.join(OUT, "hasil.csv")
    if os.path.exists(hasil_csv):
        d = d[~d.key.isin(set(pd.read_csv(hasil_csv, usecols=["key"], dtype=str).key))]
    print(f"diproses: {len(d)} foto", flush=True)

    model = reader._load_model(os.path.abspath(a.model))
    baru = not os.path.exists(hasil_csv)
    with open(hasil_csv, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=KOLOM)
        if baru:
            w.writeheader()
        for i, r in enumerate(d.itertuples(index=False), 1):
            try:
                hasil = proses(r, model)
            except Exception as e:  # satu foto rusak tidak menghentikan semuanya
                hasil = dict(status2=f"error:{type(e).__name__}")
            w.writerow(dict(key=r.key, **hasil))
            if i % 200 == 0:
                f.flush()
                print(f"{i}/{len(d)}", flush=True)
    s = pd.read_csv(hasil_csv, dtype=str)
    print("status2:", s.status2.value_counts().to_dict())
    print("selesai", flush=True)


if __name__ == "__main__":
    main()
