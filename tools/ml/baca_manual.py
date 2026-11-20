"""
Pembacaan stand secara visual (oleh Claude di sesi Claude Code, atau oleh
orang) untuk foto yang gagal dilabel otomatis.

Pembaca TIDAK diberi angka ACMT/OCR: montase hanya bernomor, supaya bacaan
tidak terpengaruh. Pembandingan dengan ACMT terjadi di buat_dataset_yolo.py.

  python tools/ml/baca_manual.py buat            -> montase batch berikutnya
  python tools/ml/baca_manual.py simpan B "r1,r2,..."
        r = angka stand (digit hitam saja, tanpa drum merah),
            ?  = tidak terbaca, X = bukan foto meter / display tak terlihat
  python tools/ml/baca_manual.py status
  python tools/ml/baca_manual.py ekspor          (otomatis setiap simpan)

Aturan baca: hanya digit hitam; digit bergulir di antara dua angka, digit
paling kiri yang terpotong, atau ragu sedikit pun -> "?" (label yang salah
lebih merusak daripada label yang tidak ada).

Hasil: ml_data/ocr_v1/baca_manual.csv (key, bacaan, batch) dan
       ml_data/ocr_v1/kunci_jawaban_visual.csv (lengkap, berdiri sendiri)
"""
import json
import os
import sys

import cv2
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "ml_data", "ocr_v1")
DIR_BATCH = os.path.join(SRC, "baca_manual")
HASIL = os.path.join(SRC, "baca_manual.csv")
PER_BATCH = 28
STATUS_SULIT = {"beda", "koreksi1_merahhilang", "persis_ragu"}
KD_OCR = {"Z", "F"}


def antrean():
    d = pd.read_csv(os.path.join(SRC, "hasil.csv"), dtype=str)
    d = d[d.status.isin(STATUS_SULIT) & d.kd_baca.isin(KD_OCR) & d.crop.notna()]
    sudah = set()
    if os.path.exists(HASIL):
        sudah = set(pd.read_csv(HASIL, dtype=str).key)
    for f in os.listdir(DIR_BATCH):  # batch yang sudah dibuat tapi belum disimpan
        if f.endswith(".json"):
            sudah |= set(json.load(open(os.path.join(DIR_BATCH, f))))
    d = d[~d.key.isin(sudah)]
    return d.sample(frac=1, random_state=0)  # acak: campuran bulan & merek


def buat():
    q = antrean().head(PER_BATCH)
    if q.empty:
        print("antrean kosong")
        return
    no = len([f for f in os.listdir(DIR_BATCH) if f.endswith(".json")]) + 1
    tiles = []
    for i, r in enumerate(q.itertuples(), 1):
        im = cv2.imread(r.crop)
        h, w = im.shape[:2]
        im = cv2.resize(im, (360, max(1, int(360 * h / w))))[:210]
        t = np.full((240, 360, 3), 255, np.uint8)
        t[:im.shape[0]] = im
        cv2.putText(t, f"#{i}", (5, 233), 0, 0.7, (0, 0, 255), 2)
        tiles.append(t)
    while len(tiles) % 4:
        tiles.append(np.full((240, 360, 3), 255, np.uint8))
    img = np.vstack([np.hstack(tiles[i:i + 4]) for i in range(0, len(tiles), 4)])
    path = os.path.join(DIR_BATCH, f"b{no:04d}.jpg")
    cv2.imwrite(path, img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    json.dump(list(q.key), open(os.path.join(DIR_BATCH, f"b{no:04d}.json"), "w"))
    print(f"batch {no}: {len(q)} foto -> {path}")


def simpan(no, teks):
    keys = json.load(open(os.path.join(DIR_BATCH, f"b{int(no):04d}.json")))
    bacaan = [x.strip() for x in teks.split(",")]
    if len(bacaan) != len(keys):
        raise SystemExit(f"jumlah bacaan {len(bacaan)} != jumlah foto {len(keys)}")
    for b in bacaan:
        if not (b.isdigit() or b in ("?", "X")):
            raise SystemExit(f"bacaan tidak sah: {b!r}")
    baru = pd.DataFrame({"key": keys, "bacaan": bacaan, "batch": int(no)})
    if os.path.exists(HASIL):
        lama = pd.read_csv(HASIL, dtype=str)
        baru = pd.concat([lama[lama.batch.astype(int) != int(no)], baru])
    baru.to_csv(HASIL, index=False)
    status()


def ekspor():
    """Kunci jawaban visual yang berdiri sendiri (tidak butuh Claude/batch json).

    hasil: cocok        bacaan visual == ACMT  -> stand terverifikasi dua sumber
           beda         bacaan visual != ACMT  -> kandidat salah input (atau salah
                        baca visual pada foto buram: periksa fotonya)
           tak_terbaca  buram / terhalang / digit bergulir / digit kiri terpotong
           bukan_meter  foto bukan display meter
    Dipakai buat_dataset_yolo.py (kolom bacaan_visual di test.csv) dan putaran
    label berikutnya: STAN_TERVERIFIKASI bisa langsung menjadi label foto sulit.
    """
    b = pd.read_csv(HASIL, dtype=str)
    d = pd.read_csv(os.path.join(SRC, "hasil.csv"), dtype=str)
    m = b.merge(d[["key", "IDPEL", "BLTH", "path", "crop", "kd_baca", "stan"]], on="key")
    angka = m.bacaan.str.isdigit()
    sama = angka & (pd.to_numeric(m.bacaan, errors="coerce") == pd.to_numeric(m.stan))
    m["hasil"] = "tak_terbaca"
    m.loc[m.bacaan == "X", "hasil"] = "bukan_meter"
    m.loc[angka & sama, "hasil"] = "cocok"
    m.loc[angka & ~sama, "hasil"] = "beda"
    m["STAN_TERVERIFIKASI"] = m.stan.where(m.hasil == "cocok")
    m = m.rename(columns={"stan": "stan_acmt", "bacaan": "bacaan_visual"})
    out = os.path.join(SRC, "kunci_jawaban_visual.csv")
    m[["key", "IDPEL", "BLTH", "kd_baca", "stan_acmt", "bacaan_visual", "hasil",
       "STAN_TERVERIFIKASI", "path", "crop", "batch"]].to_csv(out, index=False)
    print(m.hasil.value_counts().to_dict(), "->", out)


def status():
    if not os.path.exists(HASIL):
        print("belum ada bacaan")
        return
    b = pd.read_csv(HASIL, dtype=str)
    d = pd.read_csv(os.path.join(SRC, "hasil.csv"), dtype=str)[["key", "stan"]]
    m = b.merge(d, on="key")
    angka = m[m.bacaan.str.isdigit()]
    cocok = (angka.bacaan.astype(int) == angka.stan.astype(int))
    print(f"terbaca {len(b)} foto: angka {len(angka)}, '?' {(b.bacaan == '?').sum()}, "
          f"'X' {(b.bacaan == 'X').sum()} | cocok ACMT {int(cocok.sum())}, "
          f"beda ACMT {int((~cocok).sum())} | sisa antrean {len(antrean())}")


if __name__ == "__main__":
    os.makedirs(DIR_BATCH, exist_ok=True)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "buat":
        buat()
    elif cmd == "simpan":
        simpan(sys.argv[2], sys.argv[3])
        ekspor()
    elif cmd == "ekspor":
        ekspor()
    else:
        status()
