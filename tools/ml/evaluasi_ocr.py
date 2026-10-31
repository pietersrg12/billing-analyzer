"""
Bandingkan akurasi OCR end-to-end (foto -> stand) antara dua digit model
pada set test (pelanggan yang tidak pernah dilihat saat training).

"Benar" = stand terbaca == STAN METER ACMT. Drum merah: model lama ikut
membacanya, jadi untuk model lama dihitung juga skor "buang digit akhir"
sebagai pembanding yang adil. Skor dipisah per KD BACA: Z/F adalah ukuran
akurasi OCR; N/M/2/7 justru DIHARAPKAN berbeda (stand sengaja tidak sama
dengan foto), jadi di sana "tidak cocok" adalah temuan, bukan kesalahan.

Berjalan di dua tempat:
  - repo  : python tools/ml/evaluasi_ocr.py --baru <best.pt>
  - paket flashdisk (buat_paket_gpu.py): reader.py, display_detector.pt,
    digit_detector.pt dan test/ ada di samping skrip ini; latih.bat
    memanggilnya otomatis setelah training.
"""
import argparse
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DI_PAKET = os.path.exists(os.path.join(HERE, "reader.py"))
if DI_PAKET:
    sys.path.insert(0, HERE)
    import reader  # noqa: E402
    MODEL_DIR = HERE
    TEST_CSV = os.path.join(HERE, "test", "test.csv")
else:
    sys.path.insert(0, ROOT)
    from core import reader  # noqa: E402
    MODEL_DIR = os.path.join(ROOT, "model")
    TEST_CSV = os.path.join(ROOT, "ml_data", "ocr_v1", "yolo", "test.csv")


def imgsz_latih(model_path):
    """imgsz saat model dilatih (runs/<nama>/args.yaml); 640 = default reader.

    Model yang dilatih di CPU dengan --imgsz 320 harus dibaca di 320 juga,
    kalau tidak digitnya tampil 2x lebih besar dari yang pernah dilihat model.
    """
    args = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(model_path))), "args.yaml")
    if os.path.exists(args):
        for baris in open(args, encoding="utf-8"):
            if baris.startswith("imgsz:"):
                return int(baris.split(":", 1)[1])
    return 640


def angka(s):
    return int(s) if s and s.isdigit() else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baru", required=True)
    ap.add_argument("--lama", default=os.path.join(MODEL_DIR, "digit_detector.pt"))
    ap.add_argument("--test", default=TEST_CSV)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    t = pd.read_csv(a.test, dtype=str)
    # path relatif (paket) dihitung dari folder test.csv
    base = os.path.dirname(os.path.abspath(a.test))
    t["path"] = [p if os.path.isabs(p) else os.path.join(base, p) for p in t.path]
    if a.limit:
        t = t.sample(min(a.limit, len(t)), random_state=0)
    stan = t.stan.astype(int)
    display = os.path.join(MODEL_DIR, "display_detector.pt")
    # test.csv juga memuat foto sulit terverifikasi dari split lain; skor utama
    # hanya dari pelanggan test supaya tetap mewakili kondisi lapangan.
    ocr_wajar = t.kd_baca.isin(["Z", "F"]) & (t.split == "test")
    lain = ~t.kd_baca.isin(["Z", "F"]) & (t.split == "test")

    baris = []
    for nama, mp in (("lama", a.lama), ("baru", a.baru)):
        sz = imgsz_latih(mp)
        print(f"membaca {len(t)} foto dengan model {nama} (imgsz {sz})...", flush=True)
        bacaan = [reader.read_meter_digits(p, mp, display, imgsz=sz).get("stand") or ""
                  for p in t.path]
        t[f"ocr_{nama}"] = bacaan
        benar = pd.Series([angka(s) for s in bacaan], index=t.index) == stan
        buang = pd.Series([angka(s[:-1]) if len(s) > 1 else None for s in bacaan],
                          index=t.index) == stan
        t[f"benar_{nama}"] = benar
        if "hasil_visual" in t:  # foto sulit yang stand-nya terverifikasi visual
            sulit = t.hasil_visual == "cocok"
            if sulit.any():
                baris.append(f"{nama:5s} foto sulit terverifikasi benar: "
                             f"{benar[sulit].mean():6.1%}  n={int(sulit.sum())}")
        baris.append(f"{nama:5s} KD Z/F benar: {benar[ocr_wajar].mean():6.1%}  "
                     f"(+buang digit akhir: {(benar | buang)[ocr_wajar].mean():6.1%})  "
                     f"n={int(ocr_wajar.sum())}   |  KD lain cocok: "
                     f"{benar[lain].mean():6.1%} n={int(lain.sum())}")

    ringkas = "\n".join(baris)
    print("\n" + ringkas)
    out_dir = os.path.dirname(os.path.abspath(a.baru))
    t.to_csv(os.path.join(out_dir, "evaluasi.csv"), index=False)
    with open(os.path.join(out_dir, "evaluasi.txt"), "w") as f:
        f.write(ringkas + "\n")
    print("detail:", os.path.join(out_dir, "evaluasi.csv"))


if __name__ == "__main__":
    main()
