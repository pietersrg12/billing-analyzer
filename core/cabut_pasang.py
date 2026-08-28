"""
Validasi stand bongkar/pasang meter (cabut & pasang kWh meter).

Saat terjadi ganti meter atau mutasi tarif di tengah bulan, billing memecah
pemakaian satu periode menjadi DUA segmen dan menjumlahkannya:

    pemkwh = (sahlwbp_cabut - slalwbp) + (sahlwbp - slalwbp_pasang)
             \\___ segmen meter lama __/   \\___ segmen meter baru __/

Artinya tiap kolom:

- STAND_AWAL   (slalwbp)        stand awal periode pada baris DPM itu sendiri
                                - BUKAN STAND_LALU, yang berasal dari
                                  database.xlsb (lihat core/loader.py).
- STAND_CABUT  (sahlwbp_cabut)  stand terakhir meter LAMA saat dicabut.
- STAND_PASANG (slalwbp_pasang) stand awal meter BARU saat dipasang. Untuk
                                meter baru biasanya 0.
- STAND_KINI   (sahlwbp)        stand akhir periode di meter yang terpasang.

Dua aturan yang harus dipenuhi supaya kedua segmen tidak minus:

    1. STAND_CABUT  >= STAND_AWAL   (segmen meter lama)
    2. STAND_PASANG <= STAND_KINI   (segmen meter baru)

Kalau salah satu stand salah entry, segmen jadi minus dan billing memakai
rollover meter (100000 - stand_lalu + stand_kini) sehingga terbit tagihan
mustahil - pola yang sama dengan keterangan_dlpd "M KWH MAXIMUM". Contoh
nyata dari DPM 202608: satu pelanggan dengan STAND_AWAL = STAND_KINI = 11456
(meter tidak bergerak sama sekali) tapi STAND_CABUT = 22 ditagih 100.000 kWh.

Batasnya inklusif: segmen bernilai NOL (STAND_CABUT = STAND_AWAL atau
STAND_PASANG = STAND_KINI) berarti meter tidak berputar pada segmen itu -
sah, tidak memicu rollover, dan penjumlahan dua segmennya tetap cocok
dengan pemkwh. Hanya segmen MINUS yang merusak perhitungan. Contoh dari
DPM 202608: STAND_AWAL = STAND_CABUT = 2933 lalu STAND_PASANG = 0 ke
STAND_KINI = 357, pemkwh 357 - konsisten, bukan pelanggaran.

Modul ini murni jalur informasi: TIDAK mengubah STATUS hasil rule chain di
core/analyzer.py, sama seperti compute_stanbaca_comparison(). Alasannya, rule
chain memakai first-match-wins sehingga kasus ini justru terkubur - dari 19
pelanggaran pada data 202608, 11 mendarat di sheet "Stand Minus" (tempat
core/koreksi.py menyarankan "RUMAH KOSONG", saran yang salah total untuk
kasus ganti meter) dan 8 sisanya di "Stand Tidak Wajar". Di kedua sheet itu
penyebab sebenarnya tidak kelihatan; sheet CABUT_PASANG yang mengangkatnya.

Gerbang deteksi memakai STAND_CABUT/STAND_PASANG > 0, BUKAN kolom
tglcabutpasang - kolom itu terisi di semua baris DPM (berisi tanggal cabut/
pasang terakhir kapan pun, ada yang bertahun 2011) sehingga tidak bisa
membedakan aktivitas periode ini.
"""

import pandas as pd

# Kolom hasil dari modul ini (dipakai core/excel.py untuk menyusun sheet).
KOLOM_CABUT_PASANG = (
    "STAND_AWAL", "STAND_CABUT", "STAND_PASANG",
    "PEMAKAIAN_CABUT_PASANG", "SELISIH_CABUT_PASANG", "MASALAH_CABUT_PASANG",
)

# Kolom DPM yang wajib ada supaya modul ini bisa jalan.
_KOLOM_SUMBER = ("STAND_AWAL", "STAND_CABUT", "STAND_PASANG", "STAND_KINI")

MASALAH_CABUT = "STAND CABUT < STAND AWAL"
MASALAH_PASANG = "STAND PASANG > STAND KINI"
MASALAH_SELISIH = "PEMAKAIAN TIDAK COCOK DENGAN STAND CABUT/PASANG"


def tersedia(df):
    """True kalau df punya semua kolom sumber yang dibutuhkan."""
    return all(c in df.columns for c in _KOLOM_SUMBER)


def compute_cabut_pasang(df, cfg):
    """Tambah kolom validasi stand bongkar/pasang ke df.

    No-op (return df apa adanya) kalau kolom cabut/pasang tidak terbawa dari
    file DPM - export lama tidak punya kolom ini.

    Kolom yang ditambahkan:
      ADA_CABUT_PASANG       ada aktivitas cabut/pasang di periode ini
      CEK_CABUT              True kalau STAND_CABUT >= STAND_AWAL
      CEK_PASANG             True kalau STAND_PASANG <= STAND_KINI
      PEMAKAIAN_CABUT_PASANG pemakaian hasil hitung dua segmen
      SELISIH_CABUT_PASANG   PEMAKAIAN (ditagih) - PEMAKAIAN_CABUT_PASANG
      MASALAH_CABUT_PASANG   ringkasan teks masalah, kosong kalau lolos

    Semua kolom hanya bermakna pada baris ADA_CABUT_PASANG; baris lain
    diisi nilai netral (False / NA / string kosong) supaya tidak mengotori
    sheet lain yang memakai df yang sama.
    """
    if not tersedia(df):
        return df

    df = df.copy()
    tol = cfg["cabut_pasang_toleransi"]

    awal = pd.to_numeric(df["STAND_AWAL"], errors="coerce").fillna(0)
    cabut = pd.to_numeric(df["STAND_CABUT"], errors="coerce").fillna(0)
    pasang = pd.to_numeric(df["STAND_PASANG"], errors="coerce").fillna(0)
    kini = pd.to_numeric(df["STAND_KINI"], errors="coerce").fillna(0)
    pakai = pd.to_numeric(df["PEMAKAIAN"], errors="coerce").fillna(0)

    ada = (cabut > 0) | (pasang > 0)
    df["ADA_CABUT_PASANG"] = ada

    df["CEK_CABUT"] = (cabut >= awal) & ada
    df["CEK_PASANG"] = (pasang <= kini) & ada

    hitung = (cabut - awal) + (kini - pasang)
    selisih = pakai - hitung

    df["PEMAKAIAN_CABUT_PASANG"] = hitung.where(ada).round(0).astype("Int64")
    df["SELISIH_CABUT_PASANG"] = selisih.where(ada).round(0).astype("Int64")

    # Ringkasan teks: gabung semua masalah yang ditemukan pada baris itu.
    masalah = pd.Series("", index=df.index)
    for kondisi, teks in (
        (ada & ~df["CEK_CABUT"], MASALAH_CABUT),
        (ada & ~df["CEK_PASANG"], MASALAH_PASANG),
        (ada & (selisih.abs() > tol), MASALAH_SELISIH),
    ):
        masalah = masalah.where(~kondisi, (masalah + " | " + teks).str.strip(" |"))

    df["MASALAH_CABUT_PASANG"] = masalah

    return df


def ringkasan(df):
    """(n_aktivitas, n_bermasalah) untuk log pipeline & sheet RINGKASAN."""
    if "ADA_CABUT_PASANG" not in df.columns:
        return 0, 0
    ada = df["ADA_CABUT_PASANG"].fillna(False)
    return int(ada.sum()), int((ada & (df["MASALAH_CABUT_PASANG"] != "")).sum())
