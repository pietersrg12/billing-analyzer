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


def baca_db_cache(path):
    """Baca file database (rekening / stan baca) lewat cache pickle.

    Database unit berukuran 6-10 MB xlsx dan butuh 10-50 detik untuk dibaca
    openpyxl - setiap Jalankan dan setiap Unduh DLPD (pagar terkunci) membacanya
    lagi. Cache disimpan di <APP_DATA_DIR>/cache/<nama>.pkl bersama mtime &
    ukuran file sumber; file yang berubah (db_updater menulis lewat
    os.replace, jadi mtime pasti berubah) otomatis dibaca ulang. Kegagalan apa
    pun di sisi cache jatuh ke pembacaan xlsx biasa.
    """
    from config import user_path

    try:
        st = os.stat(path)
        tanda = (st.st_mtime_ns, st.st_size)
        folder = user_path("cache")
        berkas = os.path.join(folder, os.path.basename(path) + ".pkl")
    except OSError:
        return _read_excel_auto(path)

    try:
        if os.path.exists(berkas):
            isi = pd.read_pickle(berkas)
            if isinstance(isi, dict) and isi.get("tanda") == tanda:
                return isi["df"]
    except Exception:  # noqa: BLE001 - cache rusak/versi pandas lain: baca ulang
        pass

    df = _read_excel_auto(path)
    try:
        os.makedirs(folder, exist_ok=True)
        tmp = berkas + ".tmp"
        pd.to_pickle({"tanda": tanda, "df": df}, tmp)
        os.replace(tmp, berkas)
    except Exception:  # noqa: BLE001 - cache hanya percepatan
        pass
    return df


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


# Skema database historis. Dipakai juga saat databasenya belum ada, supaya
# pipeline tetap jalan dengan DataFrame kosong berkolom benar.
KOLOM_DB = ["IDPEL", "BULAN", "STAND", "PEMAKAIAN", "DAYA", "KEY"]


def read_unitup(dpm_path):
    """Ambil unitup dari file DPM/DLPD - penentu database unit mana yang dipakai.

    File itu sendiri yang menyatakan miliknya siapa, jadi ini sumber paling
    otoritatif saat analisis (lebih tepat daripada unit token, yang bisa saja
    milik user lain di komputer yang sama).

    Return string unitup, atau None kalau kolomnya tidak ada ATAU memuat lebih
    dari satu unit. Nilai None disengaja untuk kasus banyak unit (mis. export
    milik user level UP3): lebih baik jatuh ke unit token sambil mencatat di
    log daripada diam-diam menebak satu unit dan menulis ke database yang salah.
    """
    try:
        df = pd.read_excel(dpm_path, usecols=["unitup"])
    except Exception:
        return None
    nilai = df["unitup"].dropna().astype(str).str.strip()
    nilai = nilai[nilai.ne("")]
    unik = nilai.unique()
    if len(unik) != 1:
        return None
    return str(unik[0])


# Tipe kolom WAJIB numerik untuk STAND/PEMAKAIAN/DAYA: kolom object yang
# kosong ikut terbawa merge, lalu analyzer.prepare gagal di .round() dengan
# "Expected numeric dtype" - analisa unit yang belum punya database langsung
# crash, padahal seharusnya semua baris jadi DATA BARU.
DTYPE_DB = {
    "IDPEL": "object",
    "BULAN": "int64",
    "STAND": "float64",
    "PEMAKAIAN": "float64",
    "DAYA": "float64",
    "KEY": "object",
}


def db_kosong():
    """DataFrame database kosong berkolom & bertipe lengkap (saat belum diunduh)."""
    return pd.DataFrame({k: pd.Series(dtype=DTYPE_DB[k]) for k in KOLOM_DB})


def load_data(dpm_path, db_path):
    """Load DPM + database, lakukan mapping & cleaning.

    Returns
    -------
    dpm : DataFrame dengan kolom IDPEL, STAND_KINI, PEMAKAIAN, DAYA, TARIF,
          KELAINAN, plus STAND_AWAL/STAND_CABUT/STAND_PASANG bila tersedia
          di file (lihat COL_MAP_OPSIONAL)
    db  : DataFrame database historis (IDPEL, BULAN, STAND, PEMAKAIAN, DAYA,
          KEY). Kosong kalau `db_path` None atau filenya belum ada.
    """

    dpm = _read_excel_auto(dpm_path)

    # Database belum ada bukan kondisi error: instalasi baru memang belum
    # mengunduh apa pun. Hasilnya semua baris jadi DATA BARU, dan dialog
    # verifikasi coverage sudah memperingatkan lebih dulu.
    if db_path and os.path.exists(db_path):
        db = baca_db_cache(db_path)
    else:
        db = db_kosong()

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


def load_stanbaca_data(path, dengan_kd_baca=False):
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
    memang berisi bulan rekening). Database yang diunduh aplikasi menyimpan
    bulan rekening itu langsung di kolom BLTH, dan kolom itu diutamakan.

    Kalau ada lebih dari satu baca dalam bulan rekening yang sama untuk 1
    IDPEL, ambil yang paling baru (by TGL BACA) supaya konsisten dengan
    cara database.xlsb menyimpan satu STAND per IDPEL per bulan.

    `dengan_kd_baca=True` ikut mengembalikan kolom KD BACA (dipakai riwayat
    Daftar Pagar Terkunci); default-nya False supaya pemanggil lama tidak
    berubah.

    Return None (bukan raise) kalau file tidak ada, atau kolom yang
    dibutuhkan tidak ditemukan, supaya pipeline bisa lanjut tanpa fitur ini
    (graceful degradation, sama seperti core/classifier.py dan
    core/reader.py).
    """
    if not path or not os.path.exists(path):
        return None

    try:
        sb = baca_db_cache(path)
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
        if dengan_kd_baca:
            out["KD BACA"] = (sb["kd baca"].fillna("").astype(str).str.strip()
                              if "kd baca" in sb.columns else "")
    except (ValueError, TypeError, KeyError):
        return None

    out = out.dropna(subset=["STAND", "_TGL"])
    if out.empty:
        return None

    # Bulan rekening = kolom BLTH (blth yang diminta ke ACMT saat unduh) kalau
    # terisi; baris lama tanpa BLTH memakai bulan baca + 1 (lihat catatan
    # siklus baca di atas). BLTH diutamakan karena tebakan dari tanggal salah
    # untuk baca susulan awal bulan.
    tebakan = (out["_TGL"] + pd.DateOffset(months=1)).dt.strftime("%Y%m").astype(int)
    if "blth" in sb.columns:
        blth = pd.to_numeric(sb.loc[out.index, "blth"], errors="coerce")
        out["BULAN"] = blth.fillna(tebakan).astype(int)
    else:
        out["BULAN"] = tebakan

    # Bulan rekening yang sama, IDPEL yang sama -> ambil baca paling baru
    out = out.sort_values(["IDPEL", "BULAN", "_TGL"])
    out = out.groupby(["IDPEL", "BULAN"], as_index=False).tail(1)

    kolom = ["IDPEL", "BULAN", "STAND"] + (["KD BACA"] if dengan_kd_baca else [])
    return out[kolom].reset_index(drop=True)
