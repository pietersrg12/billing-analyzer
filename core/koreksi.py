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

- LEBIH TAGIH  : STAND_LALU apa adanya (kolom STAND_RUMAH_KOSONG), sama
                 rumusnya dengan RUMAH KOSONG, beda alasan -> stand turun
                 karena bulan lalu tertagih lebih (taksiran ketinggian).
- KURANG TAGIH : STAND_LALU + KWH_MANUAL, sama rumusnya dengan MANUAL, beda
                 alasan. MANUAL tetap ada atas permintaan user.

Saran otomatis (kolom PILIHAN + DASAR_SARAN), urutan menang dari atas:

1. JAM_NYALA > 720 -> CAP-720 (sheet manapun, kecuali ditimpa aturan 3).
2. REKENING PECAHAN (teks DLPD) -> BIARKAN, kecuali kena CAP-720. Stand
   "minus" di sini wajar karena rekening dipecah saat ganti meter/tarif; di
   202610 user memilih BIARKAN untuk 80 dari 81 baris seperti ini.
3. Stand Minus non-pecahan, bertingkat (diuji terhadap 719 keputusan manual
   user di 202610: cocok 87,6 %):
   a. rollover wajar (is_rollover_wajar)  -> BIARKAN
   b. kode baca GANTI KWH METER          -> BELUM PDL
   c. kode baca tak terbaca / foto bukan  -> RATA2
   d. kode baca RUMAH KOSONG / RATA2 ~ 0  -> RUMAH KOSONG
   e. STAND_KINI <= 1                     -> RATA2
   f. kode baca LEBIH TAGIH / turun sedikit (kini >= 50 % lalu) -> LEBIH TAGIH
   g. sisanya (turun drastis ke angka kecil) -> BELUM PDL (indikasi ganti
      meter yang belum di-PDL)
   Diukur ulang dengan pilihan user 202611 (140008): kecocokan 52 % -> 76 %.

`sheet_tujuan()` memetakan tiap baris ke SATU sheet: pecahan ke
REKENING_PECAHAN, Stand Minus bersaran RUMAH KOSONG/LEBIH TAGIH ke
"Rumah Kosong-Lebih Tagih", sisanya ke sheet STATUS-nya. Satu baris hanya di
satu sheet supaya tidak pernah punya dua STAN BARU di KOREKSI_STAND.

MANUAL, KURANG TAGIH, SALAH ENTRY, SALAH FOTO, SALAH PDL tidak pernah
disarankan otomatis - butuh penilaian kasus per kasus.
"""

import pandas as pd

from core.loader import kelainan_meter

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
PILIHAN_LEBIH_TAGIH = "LEBIH TAGIH"
PILIHAN_KURANG_TAGIH = "KURANG TAGIH"

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
    PILIHAN_LEBIH_TAGIH,
    PILIHAN_KURANG_TAGIH,
])

# Opsi yang butuh isian KWH_MANUAL (ditambahkan ke STAND_LALU).
PILIHAN_BUTUH_KWH_MANUAL = (PILIHAN_MANUAL, PILIHAN_KURANG_TAGIH)

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
    PILIHAN_LEBIH_TAGIH: "LEBIH TAGIH - STAND KEMBALI KE STAND LALU (PEMAKAIAN 0)",
    PILIHAN_KURANG_TAGIH: "KURANG TAGIH - PEMAKAIAN SESUAI KWH MANUAL",
}

# Nama sheet hasil pemetaan (lihat sheet_tujuan). Maks 31 karakter (Excel).
SHEET_REKENING_PECAHAN = "REKENING_PECAHAN"
SHEET_RUMAH_KOSONG = "Rumah Kosong-Lebih Tagih"

STATUS_STAND_MINUS = "Stand Minus"
TEKS_PECAHAN = "REKENING PECAHAN"

# Ambang aturan Stand Minus (lihat docstring modul).
RATA2_RUMAH_KOSONG_MAKS = 5      # kWh/bulan: riwayat praktis nol
RASIO_TURUN_SEDIKIT = 0.5        # STAND_KINI >= 50 % STAND_LALU
STAND_TAK_TERBACA_MAKS = 1       # stand 1 = meter tak terbaca
ROLLOVER_DIGIT_MIN = 4           # meter 4 digit ke atas
ROLLOVER_RASIO_LALU = 0.9        # stand lalu >= 90 % dari 10^digit (mis. >= 9000)
ROLLOVER_TOLERANSI = 2           # kWh
JAM_ROLLOVER_MAKS = 720          # di atasnya pola M KWH MAXIMUM, bukan rollover wajar


def is_pecahan(df):
    """True untuk baris REKENING PECAHAN. Dicari di seluruh KELAINAN: frasa ini
    istilah DLPD, tidak pernah muncul di segmen kelainan baca, dan file lama
    tanpa segmen gabungan pun tetap terdeteksi."""
    return df["KELAINAN"].fillna("").astype(str).str.upper().str.contains(
        TEKS_PECAHAN, regex=False
    )


def is_rollover_wajar(df):
    """Stand berputar lewat 9999/99999 dan billing sudah menghitungnya benar.

    Contoh 202611: 99942 -> 591, pemakaian 649 (= 100591 - 99942); 9982 -> 48,
    pemakaian 66. User memilih BIARKAN untuk keduanya. Syarat diperketat
    karena pola hitungnya mudah cocok secara kebetulan: stand kini 1 (tak
    terbaca) dan tagihan M KWH MAXIMUM (JN ribuan) dikecualikan.
    """
    lalu = pd.to_numeric(df["STAND_LALU"], errors="coerce")
    kini = pd.to_numeric(df["STAND_KINI"], errors="coerce")
    pakai = pd.to_numeric(df["PEMAKAIAN"], errors="coerce")
    jam = pd.to_numeric(df["JAM_NYALA"], errors="coerce")
    digit = lalu.fillna(0).clip(lower=0).round().astype("int64").astype(str).str.len()
    batas = 10.0 ** digit
    return (
        (digit >= ROLLOVER_DIGIT_MIN)
        & (lalu >= batas * ROLLOVER_RASIO_LALU)
        & (kini > STAND_TAK_TERBACA_MAKS)
        & (kini < lalu * RASIO_TURUN_SEDIKIT)
        & (((kini + batas - lalu) - pakai).abs() <= ROLLOVER_TOLERANSI)
        & (jam <= JAM_ROLLOVER_MAKS)
    ).fillna(False)


def tambah_saran_koreksi(df, cfg, klasifikasi=None):
    """Tambah kolom PILIHAN (saran otomatis) + DASAR_SARAN ke df.

    Urutan aturan ada di docstring modul. Normal & DATA BARU selalu BIARKAN.
    """
    df = df.copy()

    klasifikasi = klasifikasi or {}
    jam_batas = cfg["jam_nyala_tinggi_min"]
    jam_nyala = pd.to_numeric(df["JAM_NYALA"], errors="coerce").fillna(0)
    lalu = pd.to_numeric(df["STAND_LALU"], errors="coerce")
    kini = pd.to_numeric(df["STAND_KINI"], errors="coerce")
    rata2 = pd.to_numeric(df["RATA2"], errors="coerce").fillna(0)

    df["PILIHAN"] = PILIHAN_BIARKAN
    df["DASAR_SARAN"] = ""

    def tetapkan(mask, pilihan, dasar):
        df.loc[mask, "PILIHAN"] = pilihan
        df.loc[mask, "DASAR_SARAN"] = dasar

    # Dicocokkan HANYA ke segmen kelainan_bc_meter, bukan ke seluruh KELAINAN.
    # Kata kuncinya kosakata kelainan baca meter; kalau diadu dengan teks DLPD,
    # "PECAH" akan kena "J REKENING PECAHAN" - istilah rekening, bukan meter
    # rusak. File input lama (tanpa segmen bc-meter) menghasilkan "" di sini.
    kelainan = kelainan_meter(df["KELAINAN"]).str.upper()
    kel_tak_terbaca = pd.Series(False, index=df.index)
    for kw in KELAINAN_TAK_TERBACA_KEYWORDS:
        kel_tak_terbaca |= kelainan.str.contains(kw, regex=False)
    foto_bukan_kwh = df["IDPEL"].astype(str).map(
        lambda x: klasifikasi.get(x) == "bukan_kwh"
    )

    pecahan = is_pecahan(df)
    is_cap = jam_nyala > jam_batas
    # Stand Minus MENIMPA CAP-720: baris stand minus dengan JN > 720 adalah
    # pola rollover billing (M KWH MAXIMUM) - di 202610 user tidak pernah
    # memilih CAP-720 untuknya, melainkan RATA2/RUMAH KOSONG/BELUM PDL.
    sm = (df["STATUS"] == STATUS_STAND_MINUS) & ~pecahan

    # 1. CAP-720 (sheet manapun, termasuk pecahan)
    tetapkan(is_cap, PILIHAN_CAP720, "JAM NYALA > 720")

    # 2. Pecahan: stand turun wajar karena rekening dipecah
    tetapkan(pecahan & ~is_cap, PILIHAN_BIARKAN, "REKENING PECAHAN")

    # 3. Stand Minus bertingkat - ditulis dari prioritas TERENDAH ke tertinggi,
    #    supaya aturan yang lebih kuat menimpa.
    tetapkan(sm, PILIHAN_BELUM_PDL, "TURUN DRASTIS - INDIKASI GANTI METER")
    tetapkan(sm & (kini >= lalu * RASIO_TURUN_SEDIKIT),
             PILIHAN_LEBIH_TAGIH, "STAND TURUN SEDIKIT")
    tetapkan(sm & kelainan.str.contains("LEBIH TAGIH", regex=False),
             PILIHAN_LEBIH_TAGIH, "KODE BACA LEBIH TAGIH")
    # Stand kini 1 DI BAWAH rumah kosong: kalau riwayatnya nol, user memilih
    # RUMAH KOSONG (202611), dan STAN BARU-nya toh sama (lalu + rata2 ~ 0).
    tetapkan(sm & (kini <= STAND_TAK_TERBACA_MAKS),
             PILIHAN_RATA2, "STAND KINI <= 1 (TAK TERBACA)")
    tetapkan(sm & (rata2 <= RATA2_RUMAH_KOSONG_MAKS),
             PILIHAN_RUMAH_KOSONG, "RATA-RATA PEMAKAIAN ~ 0")
    tetapkan(sm & kelainan.str.contains("RUMAH KOSONG", regex=False),
             PILIHAN_RUMAH_KOSONG, "KODE BACA RUMAH KOSONG")
    tetapkan(sm & foto_bukan_kwh, PILIHAN_RATA2, "FOTO BUKAN KWH METER")
    tetapkan(sm & kel_tak_terbaca, PILIHAN_RATA2, "KODE BACA TAK TERBACA")
    tetapkan(sm & kelainan.str.contains("GANTI KWH", regex=False),
             PILIHAN_BELUM_PDL, "KODE BACA GANTI KWH METER")
    # Paling kuat: rollover meter yang tagihannya sudah benar. Mengoreksinya
    # (mis. RUMAH KOSONG) justru menghapus tagihan sah.
    tetapkan(sm & is_rollover_wajar(df), PILIHAN_BIARKAN, "ROLLOVER WAJAR - CEK FOTO")
    # Stand "minus" karena ganti meter yang tercatat dan stand cabut/pasangnya
    # konsisten (443200390253, 202611: 48726 -> meter baru 27 -> 105). Bukan
    # indikasi ganti meter lagi - gantinya sudah ada di data billing.
    if {"ADA_CABUT_PASANG", "MASALAH_CABUT_PASANG"} <= set(df.columns):
        ganti_sah = (df["ADA_CABUT_PASANG"].fillna(False).astype(bool)
                     & df["MASALAH_CABUT_PASANG"].fillna("").eq(""))
        tetapkan(sm & ganti_sah, PILIHAN_BIARKAN,
                 "GANTI METER TERCATAT - STAND CABUT/PASANG SESUAI")

    # Normal & DATA BARU tidak pernah dikoreksi otomatis
    tetapkan(df["STATUS"].isin(["Normal", "DATA BARU"]), PILIHAN_BIARKAN, "")

    return df


def sheet_tujuan(df):
    """Nama sheet untuk tiap baris (Series). Satu baris = satu sheet."""
    tujuan = df["STATUS"].astype(str).copy()
    if "PILIHAN" in df.columns:
        rk = (df["STATUS"] == STATUS_STAND_MINUS) & df["PILIHAN"].isin(
            [PILIHAN_RUMAH_KOSONG, PILIHAN_LEBIH_TAGIH]
        )
        tujuan[rk] = SHEET_RUMAH_KOSONG
    tujuan[is_pecahan(df)] = SHEET_REKENING_PECAHAN
    return tujuan
