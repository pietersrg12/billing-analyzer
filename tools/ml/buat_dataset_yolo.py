"""
Susun dataset YOLO dari hasil siapkan_dataset_ocr.py.

Split per IDPEL (bukan per foto): foto satu pelanggan dari bulan berbeda
hampir identik, jadi split per foto membuat val/test "bocor" dan skornya
terlalu bagus. Pembagiannya DIKUNCI di split.csv: pelanggan yang sudah punya
split tidak pernah pindah, pelanggan baru dibagi dengan hash IDPEL. Dulu
seluruh daftar diacak ulang tiap kali dibuat, sehingga menambah pelanggan
(mis. cari_lcd_acmt.py) memindahkan pelanggan test lama ke train - test
bocor dan skor model lama vs baru tidak bisa dibandingkan. test.csv memuat SEMUA foto pelanggan test, termasuk yang gagal
dilabel otomatis, supaya evaluasi_ocr.py mengukur akurasi di dunia nyata,
bukan hanya di foto yang memang mudah.

Hanya foto dengan 5-6 digit hitam yang masuk training: kurang dari itu hampir
selalu berarti digit nol di depan terlewat, dan kotak yang tak berlabel akan
mengajari model bahwa digit itu latar.

Sumber label, satu foto satu sumber (urut prioritas):
  v1   siapkan_dataset_ocr.py (model lama vs ACMT)
  lcd  label_lcd.py, hanya yang lolos periksa mata (lcd2_ok)
  v2   label_putaran2.py (model putaran sebelumnya vs ACMT, foto sulit)
Kelas 10 = digit desimal LCD.

Folder hasil (ml_data/ocr_v1/yolo) bisa disalin utuh ke komputer GPU:
dataset.yaml tidak menyimpan path absolut.

    python tools/ml/buat_dataset_yolo.py
"""
import os
import shutil
import zlib

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "ml_data", "ocr_v1")
SRC2 = os.path.join(ROOT, "ml_data", "ocr_v2")
DST = os.path.join(SRC, "yolo")
STATUS_PAKAI = {"persis", "persis_merahhilang", "merah", "koreksi1", "koreksi1_m"}
STATUS_PAKAI_V2 = {"persis", "merah", "koreksi1"}
# Label LCD yang lolos periksa mata masih puluhan, tenggelam di antara belasan
# ribu meter mekanik; diulang di train (augmentasi membuat tiap salinan beda).
ULANG_LCD = 5
# Hanya kode yang STAN METER-nya memang angka di meter. N (KWH LEBIH TAGIH),
# M (KURANG TAGIH), 2 (GANTI KWH METER), 7 (STAN DARI PELANGGAN) dst. sengaja
# berbeda dari foto - 73% foto N tidak cocok, vs 28% untuk Z - jadi koreksi1
# di sana akan menempelkan angka yang salah ke kotak digit.
KD_PAKAI = {"Z", "F"}
PORSI = {"train": 0.8, "val": 0.1, "test": 0.1}
SPLIT_CSV = os.path.join(SRC, "split.csv")
# hasil.csv saat digit_v6/v7 dibuat: sumber pembagian awal yang dikunci
HASIL_AWAL = os.path.join(SRC, "hasil_sebelum_lcd_acmt.csv")


def split_acak(idpel):
    """Cara lama (acak seed 0 atas daftar terurut) - hanya untuk split awal."""
    idpel = np.array(sorted(idpel))
    np.random.default_rng(0).shuffle(idpel)
    n = len(idpel)
    a, b = int(n * PORSI["train"]), int(n * (PORSI["train"] + PORSI["val"]))
    bagian = {i: "train" for i in idpel[:a]}
    bagian.update({i: "val" for i in idpel[a:b]})
    bagian.update({i: "test" for i in idpel[b:]})
    return bagian


def split_hash(i):
    """Pelanggan baru: tetap untuk IDPEL yang sama, tidak menggeser yang lain."""
    x = zlib.crc32(i.encode()) % 100
    return "train" if x < 80 else "val" if x < 90 else "test"


def muat_split(idpel_sekarang):
    if os.path.exists(SPLIT_CSV):
        bagian = pd.read_csv(SPLIT_CSV, dtype=str).set_index("IDPEL").split.to_dict()
    else:
        awal = pd.read_csv(HASIL_AWAL if os.path.exists(HASIL_AWAL)
                           else os.path.join(SRC, "hasil.csv"), dtype=str)
        bagian = split_acak(awal.IDPEL.unique())
    baru = [i for i in sorted(set(idpel_sekarang)) if i not in bagian]
    bagian.update({i: split_hash(i) for i in baru})
    pd.DataFrame(sorted(bagian.items()), columns=["IDPEL", "split"]).to_csv(SPLIT_CSV, index=False)
    print(f"split: {len(bagian)} pelanggan ({len(baru)} baru) -> {SPLIT_CSV}")
    return bagian


def main():
    d = pd.read_csv(os.path.join(SRC, "hasil.csv"), dtype=str)
    d["split"] = d.IDPEL.map(muat_split(d.IDPEL.unique()))

    zf = d.kd_baca.isin(KD_PAKAI)
    pakai = d[d.status.isin(STATUS_PAKAI) & d.n_hitam.isin(["5", "6"]) & zf].copy()
    pakai["lbl"] = [os.path.join(SRC, "labels", k + ".txt") for k in pakai.key]
    pakai["sumber"] = "v1"
    # Putaran 2 (label_putaran2.py / label_lcd.py), kalau sudah dijalankan.
    # Satu foto hanya diambil dari satu sumber: v1, lalu LCD, lalu v2.
    tambahan = []
    lcd_csv = os.path.join(SRC2, "lcd.csv")
    if os.path.exists(lcd_csv):
        s = pd.read_csv(lcd_csv, dtype=str)
        # hanya yang sudah lolos periksa mata (label_lcd.py --periksa)
        tambahan.append((s[s.status == "lcd2_ok"].key, os.path.join(SRC2, "labels_lcd"), "lcd"))
    v2_csv = os.path.join(SRC2, "hasil.csv")
    if os.path.exists(v2_csv):
        s = pd.read_csv(v2_csv, dtype=str)
        # meter mekanik wajib 5-6 kotak berlabel: kurang dari itu = nol depan
        # terlewat, dan kotaknya akan diajarkan sebagai latar
        mek = s.status2.isin(STATUS_PAKAI_V2) & s.n_label.isin(["5", "6"])
        # koreksi1 pada foto sulit: hanya kalau bedanya di digit terakhir
        # (drum bergulir). Beda di tengah pada foto jelas sering kali memang
        # salah input (foto 01275, ACMT 1975) - label ACMT di situ salah.
        stan = s.key.map(d.set_index("key").stan)
        akhir = [isinstance(o, str) and isinstance(t, str) and len(o) >= len(t)
                 and o[:-1] == t.zfill(len(o))[:-1] for o, t in zip(s.ocr2, stan)]
        mek &= (s.status2 != "koreksi1") | pd.Series(akhir, index=s.index)
        tambahan.append((s[mek | (s.status2 == "lcd2")].key, os.path.join(SRC2, "labels"), "v2"))
    for keys, folder, nama in tambahan:
        t = d[d.key.isin(set(keys)) & zf & ~d.key.isin(set(pakai.key))].copy()
        t["lbl"] = [os.path.join(folder, k + ".txt") for k in t.key]
        t["sumber"] = nama
        pakai = pd.concat([pakai, t])

    # Hanya images/labels yang dibuat ulang; runs/ (hasil training) tetap.
    for sub in ("images", "labels"):
        shutil.rmtree(os.path.join(DST, sub), ignore_errors=True)
    for sp in ("train", "val"):
        os.makedirs(os.path.join(DST, "images", sp))
        os.makedirs(os.path.join(DST, "labels", sp))
    dipakai = []
    for r in pakai[pakai.split != "test"].itertuples():
        if not os.path.exists(r.lbl):
            continue
        nama = os.path.basename(r.crop)[:-4]
        ulang = ULANG_LCD if r.sumber == "lcd" and r.split == "train" else 1
        for i in range(ulang):
            n = nama if i == 0 else f"{nama}_u{i}"
            shutil.copy2(r.crop, os.path.join(DST, "images", r.split, n + ".jpg"))
            shutil.copy2(r.lbl, os.path.join(DST, "labels", r.split, n + ".txt"))
        dipakai.append((r.split, r.sumber))

    # Kunci jawaban visual (baca_manual.py): foto sulit yang stand-nya sudah
    # dipastikan dua sumber. Di test dipakai untuk skor "foto sulit".
    kunci = os.path.join(SRC, "kunci_jawaban_visual.csv")
    if os.path.exists(kunci):
        k = pd.read_csv(kunci, dtype=str)[["key", "bacaan_visual", "hasil"]]
        d = d.merge(k.rename(columns={"hasil": "hasil_visual"}), on="key", how="left")
    # Foto sulit terverifikasi dari split mana pun ikut ke test.csv: statusnya
    # "beda", jadi tidak pernah punya label dan tidak pernah dilatih. Skor utama
    # evaluasi tetap dihitung dari split == "test" saja.
    sulit = d.hasil_visual.eq("cocok") if "hasil_visual" in d else False
    d[(d.split == "test") | sulit].to_csv(os.path.join(DST, "test.csv"), index=False)
    with open(os.path.join(DST, "dataset.yaml"), "w") as f:
        f.write("# path sengaja tidak diisi: ultralytics memakai folder file ini\n")
        f.write("train: images/train\nval: images/val\n\nnc: 11\n")
        # kelas 10 = digit desimal LCD (dibuang reader); lihat label_lcd.py
        f.write("names: ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9', 'desimal']\n")

    print("status semua foto:", d.status.value_counts().to_dict())
    print("sumber label:", pd.Series(dipakai).value_counts().to_dict())
    for sp in ("train", "val"):
        print(f"{sp}: {len(os.listdir(os.path.join(DST, 'images', sp)))} gambar")
    print(f"test: {int((d.split == 'test').sum())} foto (semua status) -> test.csv")
    print("dataset:", DST)


if __name__ == "__main__":
    main()
