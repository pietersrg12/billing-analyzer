"""
Loader DPM untuk format Monitoring_DLPD_Detail (PLN).

Format input yang didukung: file Excel hasil export Monitoring DLPD,
dengan kolom kunci (lowercase): idpel, sahlwbp, pemkwh, daya, tarif,
keterangan_dlpd, thblrek, slalwbp, jamnyala.

Loader memetakan kolom-kolom tersebut ke schema internal aplikasi
(uppercase: IDPEL, STAND_KINI, PEMAKAIAN, DAYA, TARIF, KELAINAN) yang
dipakai oleh analyzer, photo, dan excel module.
"""

import os

import pandas as pd

# Kolom wajib di file DPM (semua lowercase, sesuai export Monitoring DLPD)
REQUIRED_COLS = {"idpel", "sahlwbp", "pemkwh", "daya", "tarif", "keterangan_dlpd"}

# Pemetaan kolom file -> schema internal aplikasi
COL_MAP = {
    "idpel":           "IDPEL",
    "sahlwbp":         "STAND_KINI",
    "pemkwh":          "PEMAKAIAN",
    "daya":            "DAYA",
    "tarif":           "TARIF",
    "keterangan_dlpd": "KELAINAN",
}

# Kolom bongkar/pasang meter - OPSIONAL, hanya ada di export DPM yang lebih
# baru (mulai sekitar 202607). Export lama tidak punya kolom ini, jadi tidak
# boleh masuk REQUIRED_COLS: core/cabut_pasang.py degrade ke no-op kalau
# kolomnya tidak terbawa.
#
# CATATAN: STAND_AWAL (slalwbp) BUKAN STAND_LALU. STAND_LALU berasal dari
# database.xlsb (stand historis terakhir yang tercatat), sedangkan STAND_AWAL
# adalah stand awal periode menurut baris DPM itu sendiri. Validasi cabut/
# pasang membandingkan terhadap STAND_AWAL, karena billing memecah pemakaian
# memakai angka dari baris DPM yang sama.
COL_MAP_OPSIONAL = {
    "slalwbp":        "STAND_AWAL",
    "sahlwbp_cabut":  "STAND_CABUT",
    "slalwbp_pasang": "STAND_PASANG",
}


# Pemisah antara kelainan_bc_meter dan keterangan_dlpd di kolom KELAINAN
# file input hasil gabungan (lihat core/dlpd_merge.py).
SEPARATOR_KELAINAN = " | "


def kelainan_meter(seri):
    """Ambil segmen kelainan_bc_meter dari KELAINAN gabungan.

    Mengembalikan "" untuk nilai tanpa separator. Itu disengaja: file input
    lama (belum digabung dengan export DPM) isinya murni teks DLPD, dan
    mencocokkan kata kunci kelainan baca ke teks DLPD justru salah - "PECAH"
    akan kena "J REKENING PECAHAN", yang sama sekali bukan kelainan baca meter.
    Dengan "" sebagai nilai jatuhan, file lama berperilaku persis seperti
    sebelum fitur gabungan ada.
    """
    teks = seri.fillna("").astype(str)
    punya = teks.str.contains(SEPARATOR_KELAINAN, regex=False)
    # regex=False WAJIB: separatornya mengandung "|", dan pandas memperlakukan
    # pat multi-karakter sebagai regex secara default - " | " lalu terbaca
    # sebagai alternasi "spasi ATAU spasi" dan memotong di spasi pertama,
    # sehingga "GANTI KWH METER | ..." jadi "GANTI".
    potong = teks.str.split(SEPARATOR_KELAINAN, n=1, regex=False)
    return potong.str[0].where(punya, "").str.strip()


def _read_excel_auto(path):
    """Baca Excel, pilih engine berdasarkan ekstensi."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".xlsb":
        return pd.read_excel(path, engine="pyxlsb")
    return pd.read_excel(path)


def read_blth(dpm_path):
    """Ambil BLTH (thblrek) dari file DPM untuk auto-fill UI.

    Return string 6 digit (mis. '202606') atau None bila gagal.
    """
    try:
        df = pd.read_excel(dpm_path, usecols=["thblrek"], nrows=1)
        val = df["thblrek"].iloc[0]
        if pd.isna(val):
            return None
        return str(int(val))
    except Exception:
        return None


def load_data(dpm_path, db_path):
    """Load DPM + database, lakukan mapping & cleaning.

    Returns
    -------
    dpm : DataFrame dengan kolom IDPEL, STAND_KINI, PEMAKAIAN, DAYA, TARIF,
          KELAINAN, plus STAND_AWAL/STAND_CABUT/STAND_PASANG bila tersedia
          di file (lihat COL_MAP_OPSIONAL)
    db  : DataFrame database historis (IDPEL, BULAN, STAND, PEMAKAIAN, DAYA, KEY)
    """

    dpm = _read_excel_auto(dpm_path)
    db = _read_excel_auto(db_path)

    # =========================
    # VALIDASI FORMAT
    # =========================
    cols_lower = {c.lower() for c in dpm.columns}
    missing = REQUIRED_COLS - cols_lower
    if missing:
        raise ValueError(
            "Format DPM tidak dikenali. "
            f"Kolom hilang: {sorted(missing)}. "
            "Pastikan file adalah export Monitoring_DLPD_Detail."
        )

    # Normalisasi nama kolom ke lowercase agar matching deterministic
    dpm.columns = [c.lower() for c in dpm.columns]

    # =========================
    # MAPPING & SELEKSI KOLOM
    # =========================
    opsional = [c for c in COL_MAP_OPSIONAL if c in dpm.columns]
    dpm = dpm[list(COL_MAP.keys()) + opsional].rename(
        columns={**COL_MAP, **COL_MAP_OPSIONAL}
    )

    # =========================
    # CLEANING
    # =========================
    dpm["IDPEL"] = dpm["IDPEL"].astype(str).str.strip()

    num_cols = ["STAND_KINI", "PEMAKAIAN", "DAYA"]
    num_cols += [COL_MAP_OPSIONAL[c] for c in opsional]
    for col in num_cols:
        dpm[col] = pd.to_numeric(dpm[col], errors="coerce").fillna(0)

    dpm["TARIF"] = dpm["TARIF"].fillna("").astype(str).str.strip()
    dpm["KELAINAN"] = dpm["KELAINAN"].fillna("").astype(str).str.strip()

    db["IDPEL"] = db["IDPEL"].astype(str)
    db["BULAN"] = db["BULAN"].astype(int)

    return dpm, db


def load_stanbaca_data(path):
    """Load database stan baca (hasil baca meter asli per kejadian baca,
    sebelum potongan billing). Skema sumber (export "STAN BACA"): IDPEL,
    STAN METER, STAN BACA, TGL BACA, KD BACA - satu baris per kejadian baca
    (bisa lebih dari satu per bulan per IDPEL).

    STAND diambil dari kolom STAN METER (angka mentah hasil baca fisik
    meter di lapangan) - BUKAN STAN BACA, yang merupakan angka hasil
    proses/koreksi sistem billing (bisa berbeda signifikan dari STAN METER
    kalau KD BACA menandakan ada koreksi, mis. kode N/"KWH LEBIH TAGIH").

    Siklus baca PLN: pembacaan fisik dilakukan di akhir bulan (median
    tanggal 26), dan hasilnya dipakai untuk REKENING BULAN BERIKUTNYA -
    bukan bulan saat baca terjadi. Jadi BULAN (bulan rekening) = bulan
    TGL BACA + 1, supaya sebanding dengan BULAN di database.xlsb (yang
    memang berisi bulan rekening).

    Kalau ada lebih dari satu baca dalam bulan rekening yang sama untuk 1
    IDPEL, ambil yang paling baru (by TGL BACA) supaya konsisten dengan
    cara database.xlsb menyimpan satu STAND per IDPEL per bulan.

    Return None (bukan raise) kalau file tidak ada, atau kolom yang
    dibutuhkan tidak ditemukan, supaya pipeline bisa lanjut tanpa fitur ini
    (graceful degradation, sama seperti core/classifier.py dan
    core/reader.py).
    """
    if not path or not os.path.exists(path):
        return None

    try:
        sb = _read_excel_auto(path)
    except Exception:
        return None

    sb.columns = [c.strip().lower() for c in sb.columns]
    if not {"idpel", "stan meter", "tgl baca"}.issubset(sb.columns):
        return None

    try:
        out = pd.DataFrame()
        out["IDPEL"] = sb["idpel"].astype(str).str.strip()
        out["STAND"] = pd.to_numeric(sb["stan meter"], errors="coerce")
        out["_TGL"] = pd.to_datetime(sb["tgl baca"], dayfirst=True, errors="coerce")
    except (ValueError, TypeError, KeyError):
        return None

    out = out.dropna(subset=["STAND", "_TGL"])
    if out.empty:
        return None

    # Bulan rekening = bulan baca + 1 (lihat catatan siklus baca di atas)
    out["BULAN"] = (out["_TGL"] + pd.DateOffset(months=1)).dt.strftime("%Y%m").astype(int)

    # Bulan rekening yang sama, IDPEL yang sama -> ambil baca paling baru
    out = out.sort_values(["IDPEL", "BULAN", "_TGL"])
    out = out.groupby(["IDPEL", "BULAN"], as_index=False).tail(1)

    return out[["IDPEL", "BULAN", "STAND"]].reset_index(drop=True)
