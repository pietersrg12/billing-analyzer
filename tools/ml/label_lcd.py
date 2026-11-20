"""
Label otomatis meter LCD (Melcoinda MTS-237, Smartmeter SMI-710, ...).

Layar LCD menampilkan stand + 2 desimal ("26.55") sedangkan ACMT mencatat
angka bulat (26). Model putaran 1 tidak pernah dilatih dengan LCD sehingga
salah membaca angkanya, tetapi kotak deteksinya (pada conf rendah) sudah
cukup tepat menunjuk posisi tiap digit. Jadi:
  posisi digit  <- digit_v6, semua kelas digabung
  angka bulat   <- STAN METER ACMT
  2 digit akhir <- kelas "desimal" (10); nilainya tidak perlu, reader membuangnya

Label hanya ditulis bila jumlah kotak sebaris == len(ACMT) + 2 dan isi kotak
terang (angka gelap di layar terang = LCD, bukan drum hitam meter mekanik:
meter mekanik "01234"+drum merah juga 6 kotak untuk ACMT 1234).
PaddleOCR sudah dicoba dan gagal membaca 7-segmen berkontras rendah.

    python tools/ml/label_lcd.py --model ml_data/digit_v6/weights/best.pt [--keys kandidat.csv]
    python tools/ml/label_lcd.py --model <v7 best.pt> --keys kandidat.csv --ulang
                                                          -> foto jumlah_beda/tak_teratur diproses lagi
    python tools/ml/label_lcd.py --montase               -> 28 label berikutnya untuk dicek mata
    python tools/ml/label_lcd.py --periksa 1 "2,5,9"     -> nomor yang salah dibuang, sisanya lcd2_ok

Wajib diperiksa: aturan di atas masih meloloskan meter mekanik berwarna dan
kotak yang bergeser (±60% di batch pertama). Hanya lcd2_ok yang dipakai
buat_dataset_yolo.py.

Hasil: ml_data/ocr_v2/labels_lcd/*.txt + lcd.csv (bisa dilanjutkan).
"""
import argparse
import csv
import json
import os
import sys

import cv2
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from core import reader  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from siapkan_dataset_ocr import kemerahan  # noqa: E402

SRC = os.path.join(ROOT, "ml_data", "ocr_v1")
OUT = os.path.join(ROOT, "ml_data", "ocr_v2")
LBL = os.path.join(OUT, "labels_lcd")
CSV = os.path.join(OUT, "lcd.csv")
KELAS_DESIMAL = 10
KOLOM = ["key", "status", "n_kotak", "n_target", "gelap"]


def baris_kotak(model, crop, dengan_kelas=False):
    """Kotak digit sebaris dari deteksi conf rendah. Kelas dibuang, kecuali
    `dengan_kelas`: kotak lalu berbentuk [x1, y1, x2, y2, kelas] (kelas dari
    deteksi ber-conf tertinggi di posisi itu)."""
    r = model.predict(crop, conf=0.05, iou=0.45, imgsz=640, verbose=False, device="cpu")[0]
    det = sorted(zip(r.boxes.conf.tolist(), r.boxes.xyxy.tolist(), r.boxes.cls.tolist()),
                 reverse=True)
    kept = []
    for _, b, c in det:  # NMS lintas kelas: satu digit sering terdeteksi 2 kelas
        lebar = b[2] - b[0]
        if all(min(b[2], k[2]) - max(b[0], k[0]) < 0.4 * min(lebar, k[2] - k[0]) for k in kept):
            kept.append(b + [int(c)])
    if len(kept) < 2:
        return []
    h = np.median([k[3] - k[1] for k in kept])
    kept = [k for k in kept if k[3] - k[1] > 0.7 * h]
    rows = []
    for k in sorted(kept, key=lambda k: (k[1] + k[3]) / 2):
        cy = (k[1] + k[3]) / 2
        if rows and abs(cy - rows[-1][-1][5]) < 0.5 * h:
            rows[-1].append(k + [cy])
        else:
            rows.append([k + [cy]])
    best = max(rows, key=len)
    return sorted([b[:5] if dengan_kelas else b[:4] for b in best], key=lambda b: b[0])


def fraksi_gelap(crop, kotak):
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    x1, y1 = int(min(b[0] for b in kotak)), int(min(b[1] for b in kotak))
    x2, y2 = int(max(b[2] for b in kotak)), int(max(b[3] for b in kotak))
    roi = g[y1:y2, x1:x2]
    if roi.size == 0:
        return 1.0
    _, m = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    return float((m > 0).mean())


def rapi(kotak):
    """Baris 7-segmen lebarnya tetap: tolak baris yang tidak teratur, lalu
    ganti kotaknya dengan pembagian rata (posisi label jadi konsisten antar
    foto, juga untuk angka "1" yang hanya mengisi sisi kanan selnya)."""
    k = np.array(kotak)
    h = k[:, 3] - k[:, 1]
    w = k[:, 2] - k[:, 0]
    cy = (k[:, 1] + k[:, 3]) / 2
    cx = (k[:, 0] + k[:, 2]) / 2
    if np.std(h) / np.mean(h) > 0.15 or np.ptp(cy) > 0.25 * np.median(h):
        return None
    gap = np.diff(cx)
    if np.std(gap) / np.mean(gap) > 0.25:
        return None
    if np.any(k[1:, 0] < k[:-1, 2] - 0.15 * np.median(w)):  # bertumpuk
        return None
    x1, x2 = k[0, 0], k[-1, 2]
    y1, y2 = np.median(k[:, 1]), np.median(k[:, 3])
    sel = (x2 - x1) / len(k)
    return [(x1 + i * sel, y1, x1 + (i + 1) * sel, y2) for i in range(len(k))]


def proses(model, r):
    crop = cv2.imread(r.crop)
    if crop is None:
        return dict(status="gagal")
    target = str(int(r.stan))
    berkelas = baris_kotak(model, crop, dengan_kelas=True)
    kotak = [b[:4] for b in berkelas]
    n_target = len(target) + 2
    # Model yang sudah mengenal LCD (digit_v7+): bacaannya sendiri dipakai bila
    # bagian bulatnya == ACMT dan diakhiri kotak desimal. Nol di depan ("00026.55")
    # ikut dilabel apa adanya, jadi jumlah kotak tidak harus len(ACMT) + 2.
    kelas = [b[4] for b in berkelas]
    bulat = "".join(str(c) for c in kelas if c < KELAS_DESIMAL)
    i_des = [i for i, c in enumerate(kelas) if c == KELAS_DESIMAL]
    if (bulat.lstrip("0") == target.lstrip("0") and i_des
            and i_des == list(range(len(kelas) - len(i_des), len(kelas)))):
        n_target = len(kelas)
    elif len(kotak) != n_target:
        return dict(status="jumlah_beda", n_kotak=len(kotak), n_target=n_target)
    else:
        kelas = [int(c) for c in target] + [KELAS_DESIMAL, KELAS_DESIMAL]
    gelap = round(fraksi_gelap(crop, kotak), 3)
    a = kotak[-1]
    merah = kemerahan(crop, a[2], a[1], a[2] + 1.3 * (a[2] - a[0]), a[3])
    if gelap > 0.45 or merah > 0.2:  # drum hitam / drum merah meter mekanik
        return dict(status="bukan_lcd", n_kotak=len(kotak), n_target=n_target, gelap=gelap)
    kotak = rapi(kotak)
    if kotak is None:
        return dict(status="tak_teratur", n_kotak=n_target, n_target=n_target, gelap=gelap)
    H, W = crop.shape[:2]
    with open(os.path.join(LBL, r.key + ".txt"), "w") as f:
        for (a, b, c, d), k in zip(kotak, kelas):
            f.write(f"{k} {(a + c) / 2 / W:.6f} {(b + d) / 2 / H:.6f} "
                    f"{(c - a) / W:.6f} {(d - b) / H:.6f}\n")
    return dict(status="lcd2", n_kotak=len(kotak), n_target=n_target, gelap=gelap)


def montase():
    """Gambar 28 label lcd2 yang belum diperiksa (kotak + kelas) untuk dicek mata."""
    s = pd.read_csv(CSV, dtype=str)
    s = s[s.status == "lcd2"].sort_values("key")
    h = pd.read_csv(os.path.join(SRC, "hasil.csv"), dtype=str).set_index("key")
    q = s.head(28)
    if q.empty:
        print("semua label sudah diperiksa")
        return
    no = len([f for f in os.listdir(OUT) if f.startswith("periksa_lcd_") and f.endswith(".json")]) + 1
    json.dump(list(q.key), open(os.path.join(OUT, f"periksa_lcd_{no:03d}.json"), "w"))
    tiles = []
    for i, k in enumerate(q.key, 1):
        im = cv2.imread(h.loc[k, "crop"])
        H, W = im.shape[:2]
        for ln in open(os.path.join(LBL, k + ".txt")):
            c, cx, cy, w, hh = ln.split()
            cx, cy, w, hh = float(cx) * W, float(cy) * H, float(w) * W, float(hh) * H
            col = (255, 120, 0) if c == str(KELAS_DESIMAL) else (0, 0, 255)
            cv2.rectangle(im, (int(cx - w / 2), int(cy - hh / 2)), (int(cx + w / 2), int(cy + hh / 2)), col, 2)
            cv2.putText(im, "d" if c == str(KELAS_DESIMAL) else c,
                        (int(cx - w / 2), int(cy - hh / 2) - 3), 0, 0.9, col, 2)
        t = np.full((210, 360, 3), 255, np.uint8)
        x = cv2.resize(im, (360, min(185, int(360 * H / W))))
        t[:x.shape[0]] = x
        cv2.putText(t, f"#{i}", (3, 205), 0, 0.6, (0, 0, 0), 2)
        tiles.append(t)
    while len(tiles) % 4:
        tiles.append(np.full((210, 360, 3), 255, np.uint8))
    out = os.path.join(OUT, f"periksa_lcd_{no:03d}.jpg")
    cv2.imwrite(out, np.vstack([np.hstack(tiles[i:i + 4]) for i in range(0, len(tiles), 4)]))
    print(f"batch {no}: {len(q)} label -> {out}")


def periksa(no, salah):
    """Batch `no` sudah diperiksa: nomor di `salah` dibuang, sisanya lcd2_ok."""
    keys = json.load(open(os.path.join(OUT, f"periksa_lcd_{no:03d}.json")))
    buang = {keys[i - 1] for i in salah}
    s = pd.read_csv(CSV, dtype=str)
    for k in buang:
        p = os.path.join(LBL, k + ".txt")
        if os.path.exists(p):
            os.remove(p)
    s.loc[s.key.isin(buang), "status"] = "ditolak"
    s.loc[s.key.isin(set(keys) - buang), "status"] = "lcd2_ok"
    s.to_csv(CSV, index=False)
    print(f"batch {no}: ditolak {len(buang)}, diterima {len(keys) - len(buang)}; status:",
          s.status.value_counts().to_dict())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model")
    ap.add_argument("--keys", help="csv berkolom key; default semua foto KD Z/F")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--ulang", action="store_true",
                    help="proses lagi foto berstatus jumlah_beda/tak_teratur (mis. dengan model baru)")
    ap.add_argument("--montase", action="store_true")
    ap.add_argument("--periksa", nargs=2, metavar=("BATCH", "SALAH"),
                    help='mis. --periksa 1 "2,5,9" (nomor gambar yang salah; "-" = tidak ada)')
    a = ap.parse_args()
    os.makedirs(LBL, exist_ok=True)
    if a.montase:
        return montase()
    if a.periksa:
        salah = [int(x) for x in a.periksa[1].split(",") if x.strip().isdigit()]
        return periksa(int(a.periksa[0]), salah)

    d = pd.read_csv(os.path.join(SRC, "hasil.csv"), dtype=str)
    d = d[d.kd_baca.isin(["Z", "F"]) & d.crop.notna()]
    if a.keys:
        d = d[d.key.isin(set(pd.read_csv(a.keys, dtype=str).key))]
    d = d.sample(frac=1, random_state=0)
    # Pelanggan split test tidak pernah masuk training (buat_dataset_yolo.py),
    # jadi melabelnya hanya membuang waktu periksa mata.
    # split.csv (dikunci buat_dataset_yolo.py); IDPEL yang belum ada di sana
    # belum punya split dan tetap diproses.
    split_csv = os.path.join(SRC, "split.csv")
    if os.path.exists(split_csv):
        t = pd.read_csv(split_csv, dtype=str)
        d = d[~d.IDPEL.isin(set(t[t.split == "test"].IDPEL))]
    if a.ulang and os.path.exists(CSV):
        s = pd.read_csv(CSV, dtype=str)
        s[~s.status.isin(["jumlah_beda", "tak_teratur"])].to_csv(CSV, index=False)
    if a.limit:
        d = d.head(a.limit)
    if os.path.exists(CSV):
        d = d[~d.key.isin(set(pd.read_csv(CSV, usecols=["key"], dtype=str).key))]
    print(f"diproses: {len(d)} foto", flush=True)
    model = reader._load_model(os.path.abspath(a.model))
    baru = not os.path.exists(CSV)
    with open(CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=KOLOM)
        if baru:
            w.writeheader()
        for i, r in enumerate(d.itertuples(index=False), 1):
            try:
                hasil = proses(model, r)
            except Exception as e:  # satu foto rusak tidak menghentikan semuanya
                hasil = dict(status=f"error:{type(e).__name__}")
            w.writerow(dict(key=r.key, **hasil))
            if i % 200 == 0:
                f.flush()
                print(f"{i}/{len(d)}", flush=True)
    print("status:", pd.read_csv(CSV, dtype=str).status.value_counts().to_dict())


if __name__ == "__main__":
    main()
