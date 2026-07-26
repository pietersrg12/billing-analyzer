"""
Saran koreksi stand otomatis.

Prinsip (dari user): hasil DPM tidak boleh ada pemakaian > 720 jam nyala,
dan stand tidak boleh minus kecuali benar-benar rollover. Yang dikoreksi
adalah STAND_KINI, dengan 4 opsi pengganti:

- RATA2        : STAND_LALU + rata-rata pemakaian (kolom STAND_RATA2)
                 -> untuk meter tidak terbaca / tidak jelas.
- CAP-720      : STAND_LALU + 718 jam x daya (kolom STAND_P1)
                 -> untuk pemakaian melebihi batas 720 jam nyala.
- RUMAH KOSONG : STAND_LALU apa adanya, pemakaian 0 (kolom STAND_RUMAH_KOSONG)
                 -> untuk stand minus pada rumah kosong / riwayat sering 0.
- MANUAL       : STAND_LALU + kWh yang ditentukan sendiri (kolom KWH_MANUAL)
                 -> untuk penyesuaian kurang tagih bertahap.
- SALAH ENTRY  : STAN_MANUAL langsung jadi stand baru (bukan ditambah ke
                 STAND_LALU) -> untuk typo/salah input angka stand.
- SALAH FOTO   : STAND_LALU + rata-rata pemakaian (kolom STAND_RATA2),
                 sama seperti RATA2 -> untuk foto yang salah/tidak sesuai
                 sehingga stand tidak bisa diverifikasi dari foto.
- SALAH PDL    : STAN_MANUAL kalau diisi, else fallback ke STAND_RATA2
                 -> data pelanggan salah, stand perlu dikoreksi manual.
- BELUM PDL    : sama seperti SALAH PDL (STAN_MANUAL atau fallback RATA2)
                 -> proses PDL pelanggan belum selesai.

Hanya 2 kelompok yang diisi otomatis ke kolom PILIHAN, sisanya BIARKAN:

1. Sheet "Stand Minus" (STATUS == "Stand Minus", STAND_KINI < STAND_LALU):
   RATA2 kalau ada indikasi meter tidak terbaca (KELAINAN, indikasi stan
   baca tak pernah dibaca, foto bukan_kwh), sisanya RUMAH KOSONG.
2. JAM_NYALA (dari PEMAKAIAN/DAYA di uploadan DPM/Monitoring DLPD) > 720:
   CAP-720. Berlaku di sheet manapun, tidak digerbang oleh kelompok 1.

Opsi lain - MANUAL, SALAH ENTRY, SALAH PDL, BELUM PDL - tidak pernah
disarankan otomatis, murni pilihan manual user lewat dropdown di Excel,
karena butuh penilaian kasus per kasus yang tidak aman ditebak sistem.
"""

import pandas as pd

# Keyword KELAINAN yang menandakan meter tidak bisa dibaca dengan benar.
# Format DPM Monitoring DLPD memakai kode DLPD (mis. "M KWH MAXIMUM"), tapi
# export lain bisa membawa nama kelainan baca - keduanya dicakup di sini.
KELAINAN_TAK_TERBACA_KEYWORDS = (
    "TIDAK ADA", "BURAM", "PECAH", "DALAM BANGUNAN",
    "ANJING", "STAN DARI PELANGGAN",
)

PILIHAN_BIARKAN = "BIARKAN"
PILIHAN_RATA2 = "RATA2"
PILIHAN_CAP720 = "CAP-720"
PILIHAN_RUMAH_KOSONG = "RUMAH KOSONG"
PILIHAN_MANUAL = "MANUAL"
PILIHAN_SALAH_ENTRY = "SALAH ENTRY"
PILIHAN_SALAH_FOTO = "SALAH FOTO"
PILIHAN_SALAH_PDL = "SALAH PDL"
PILIHAN_BELUM_PDL = "BELUM PDL"

# Urut A-Z biar enak dibaca di dropdown Excel.
PILIHAN_OPTIONS = sorted([
    PILIHAN_BIARKAN,
    PILIHAN_RATA2,
    PILIHAN_CAP720,
    PILIHAN_RUMAH_KOSONG,
    PILIHAN_MANUAL,
    PILIHAN_SALAH_ENTRY,
    PILIHAN_SALAH_FOTO,
    PILIHAN_SALAH_PDL,
    PILIHAN_BELUM_PDL,
])

# Opsi yang butuh isian STAN_MANUAL (stand baru langsung, bukan kWh) di
# sheet status - dipakai excel.py utk tahu kolom mana yang perlu formula
# mirror ke KOREKSI_STAND. SALAH ENTRY: STAN_MANUAL wajib (tidak ada
# fallback, karena tidak ada cara menebak angka yang benar). SALAH PDL /
# BELUM PDL: STAN_MANUAL opsional - kalau dikosongkan, fallback ke STAND_RATA2.
PILIHAN_BUTUH_STAN_MANUAL = (PILIHAN_SALAH_ENTRY, PILIHAN_SALAH_PDL, PILIHAN_BELUM_PDL)
PILIHAN_STAN_MANUAL_FALLBACK_RATA2 = (PILIHAN_SALAH_PDL, PILIHAN_BELUM_PDL)

ALASAN_MAP = {
    PILIHAN_RATA2: "TIDAK TERBACA - STAND DIGANTI STAND LALU + RATA-RATA",
    PILIHAN_CAP720: "PEMAKAIAN MELEBIHI 720 JAM NYALA - STAND DIBATASI P1",
    PILIHAN_RUMAH_KOSONG: "RUMAH KOSONG - STAND TETAP (PEMAKAIAN 0)",
    PILIHAN_MANUAL: "PENYESUAIAN KURANG TAGIH BERTAHAP",
    PILIHAN_SALAH_ENTRY: "SALAH ENTRY - STAND DIGANTI SESUAI STAN MANUAL",
    PILIHAN_SALAH_FOTO: "SALAH FOTO - STAND DIGANTI STAND LALU + RATA-RATA",
    PILIHAN_SALAH_PDL: "SALAH PDL - PERLU KOREKSI DATA PELANGGAN",
    PILIHAN_BELUM_PDL: "BELUM PDL - PERLU PROSES PDL",
}


def tambah_saran_koreksi(df, cfg, klasifikasi=None):
    """Tambah kolom PILIHAN (saran koreksi otomatis) ke df.

    2 kelompok independen (tidak saling menggerbang satu sama lain):
      1. Sheet "Stand Minus" -> RATA2 (indikasi tak terbaca) atau
         RUMAH KOSONG (selainnya).
      2. JAM_NYALA > jam_nyala_tinggi_min (720) -> CAP-720.
      Selain kedua kelompok itu -> BIARKAN.
    """
    df = df.copy()

    klasifikasi = klasifikasi or {}
    jam_batas = cfg["jam_nyala_tinggi_min"]
    jam_nyala = pd.to_numeric(df["JAM_NYALA"], errors="coerce").fillna(0)

    df["PILIHAN"] = PILIHAN_BIARKAN

    # 1. JAM_NYALA > 720 -> CAP-720
    is_cap = jam_nyala > jam_batas
    df.loc[is_cap, "PILIHAN"] = PILIHAN_CAP720

    # 2. Sheet "Stand Minus" -> RATA2 (tak terbaca) atau RUMAH KOSONG
    is_stand_minus = df["STATUS"] == "Stand Minus"

    kelainan = df["KELAINAN"].fillna("").astype(str).str.upper()
    kel_tak_terbaca = pd.Series(False, index=df.index)
    for kw in KELAINAN_TAK_TERBACA_KEYWORDS:
        kel_tak_terbaca |= kelainan.str.contains(kw, regex=False)

    foto_bukan_kwh = df["IDPEL"].astype(str).map(
        lambda x: klasifikasi.get(x) == "bukan_kwh"
    )
    is_tak_terbaca = kel_tak_terbaca | foto_bukan_kwh

    df.loc[is_stand_minus, "PILIHAN"] = PILIHAN_RUMAH_KOSONG
    df.loc[is_stand_minus & is_tak_terbaca, "PILIHAN"] = PILIHAN_RATA2

    # Normal & DATA BARU tidak pernah dikoreksi otomatis
    df.loc[df["STATUS"].isin(["Normal", "DATA BARU"]), "PILIHAN"] = PILIHAN_BIARKAN

    return df
