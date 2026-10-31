"""
Parsing hasil download + append ke database historis.

Dua alur, satu untuk tiap database:

1. REKENING (`database.xlsx`) <- export Monitoring_Billing_Detail dari portal
   billing. Diambil: idpel, thblrek, sahlwbp, pemkwh_real (+ daya kalau ada).
2. STAN BACA (`database_stand_baca.xlsx`) <- laporan Detail Kode Baca Tunggal
   dari SIMBA/ACMT, tiga kategori kode baca yang digabung jadi satu.

Kenapa hasilnya .xlsx, bukan .xlsb seperti file lama: pyxlsb read-only, tidak
ada pustaka Python yang bisa MENULIS .xlsb. Pembacanya (loader._read_excel_auto)
menerima dua-duanya, jadi peralihan format ini tidak terlihat oleh pipeline.

Semua penulisan lewat berkas .tmp lalu os.replace, dan file lama selalu
di-backup dulu - satu update yang salah bulan tidak boleh menghancurkan
riwayat berbulan-bulan yang dikumpulkan manual.
"""

import io
import os
import shutil
from datetime import datetime

import pandas as pd

from config import (
    DB_BACKUP_DIR,
    db_path,
    db_path_baru,
    stanbaca_db_path,
    stanbaca_db_path_baru,
)
from core.loader import _read_excel_auto

# Skema database rekening - urutannya dipertahankan supaya file hasil update
# tetap terbaca sama persis seperti database.xlsb yang lama.
KOLOM_REKENING = ["IDPEL", "BULAN", "STAND", "PEMAKAIAN", "DAYA", "KEY"]

# Skema database stan baca. Nama kolomnya sengaja dipertahankan apa adanya
# (mengandung spasi) karena loader.load_stanbaca_data mencarinya lewat nama
# yang di-lowercase: "stan meter", "tgl baca".
# BLTH = bulan rekening yang diminta ke ACMT saat mengunduh (blth=202608
# mengembalikan baca Juli). Itulah bulan rekening yang sebenarnya; menebaknya
# dari TGL BACA + 1 salah untuk baca susulan awal bulan (baca 01/08 siklus
# Juli jadi 202609). Baris lama tanpa BLTH tetap memakai tebakan itu.
KOLOM_STAN_BACA = ["IDPEL", "STAN METER", "STAN BACA", "TGL BACA", "KD BACA", "BLTH"]

# Baris header laporan Kode Baca Tunggal ada di baris ke-8 (index 7); di
# atasnya blok judul berhias (nama wilayah, unit, periode).
KODE_BACA_HEADER_ROW = 7


class DbUpdateError(Exception):
    """Gagal parsing hasil download atau gagal menulis database."""


# =========================
# PARSING
# =========================

def _kolom_lower(df):
    """Peta {nama_lower: nama_asli} untuk pencocokan kolom tanpa peduli kapital."""
    return {str(c).strip().lower(): c for c in df.columns}


def _idpel_teks(seri):
    """IDPEL -> string digit murni.

    Kolom IDPEL datang sebagai angka, dan satu sel kosong saja sudah cukup
    membuat pandas menjadikan kolomnya float - astype(str) lalu menghasilkan
    "443200000197.0". IDPEL berekor ".0" tidak akan cocok dengan IDPEL mana pun
    di DPM, jadi seluruh database hasil unduhan jadi tidak berguna tanpa
    diketahui. Lewat Int64 dulu supaya ekornya tidak pernah muncul.
    """
    angka = pd.to_numeric(seri, errors="coerce")
    if angka.notna().any():
        teks = angka.astype("Int64").astype(str)
        # Sel yang memang bukan angka dikembalikan ke teks aslinya.
        return teks.where(angka.notna(), seri.astype(str)).str.strip()
    return seri.astype(str).str.strip()


def _cari_baris_header(path, kolom_kunci, batas=12):
    """Baca ulang file dengan header digeser sampai `kolom_kunci` ketemu.

    Return (DataFrame, peta_kolom) atau None kalau tetap tidak ketemu.
    """
    for baris in range(1, batas + 1):
        try:
            ulang = _read_excel_auto_header(path, baris)
        except Exception:
            continue
        peta = _kolom_lower(ulang)
        if kolom_kunci in peta:
            return ulang, peta
    return None


def _read_excel_auto_header(path, header):
    """_read_excel_auto tapi dengan baris header eksplisit."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".xlsb":
        return pd.read_excel(path, engine="pyxlsb", header=header)
    return pd.read_excel(path, header=header)


def parse_billing_export(path, thblrek):
    """Export Monitoring_Billing_Detail -> DataFrame skema database rekening.

    `thblrek` dipakai sebagai BULAN kalau file tidak membawa kolomnya sendiri.
    """
    try:
        raw = _read_excel_auto(path)
    except Exception as e:
        raise DbUpdateError(f"Tidak bisa membaca file export {os.path.basename(path)}: {e}")

    kol = _kolom_lower(raw)

    # Sebagian laporan PLN menaruh blok judul di atas header (laporan kode baca
    # header-nya di baris ke-8). Layout export billing belum pernah terverifikasi,
    # jadi kalau baris pertama bukan header, cari header-nya beberapa baris ke
    # bawah alih-alih langsung menyerah.
    if "idpel" not in kol:
        raw, kol = _cari_baris_header(path, "idpel", batas=12) or (raw, kol)

    # sahlwbp = stand akhir periode, pemkwh_real = pemakaian riil (bukan
    # pemkwh yang sudah kena penyesuaian billing).
    wajib = {"idpel": "IDPEL", "sahlwbp": "STAND", "pemkwh_real": "PEMAKAIAN"}
    hilang = [k for k in wajib if k not in kol]
    if hilang:
        raise DbUpdateError(
            "Export billing tidak memuat kolom yang dibutuhkan: "
            + ", ".join(hilang)
            + ".\nKolom yang ditemukan di file: "
            + ", ".join(sorted(kol.keys()))
        )

    out = pd.DataFrame()
    out["IDPEL"] = _idpel_teks(raw[kol["idpel"]])

    if "thblrek" in kol:
        bulan = pd.to_numeric(raw[kol["thblrek"]], errors="coerce")
        bulan = bulan.fillna(int(thblrek))
    else:
        bulan = pd.Series(int(thblrek), index=raw.index)
    out["BULAN"] = bulan.astype("int64")

    out["STAND"] = pd.to_numeric(raw[kol["sahlwbp"]], errors="coerce")
    out["PEMAKAIAN"] = pd.to_numeric(raw[kol["pemkwh_real"]], errors="coerce")

    # DAYA tidak dipakai analyzer (JAM_NYALA mengambil DAYA dari DPM), tapi
    # kolomnya ada di skema lama jadi tetap diisi kalau tersedia.
    if "daya" in kol:
        out["DAYA"] = pd.to_numeric(raw[kol["daya"]], errors="coerce")
    else:
        out["DAYA"] = pd.NA

    # astype(str) mengubah sel kosong jadi string "nan", bukan NaN, jadi
    # dropna saja tidak cukup untuk membuang baris tanpa IDPEL.
    out = out.dropna(subset=["STAND"])
    out = out[out["IDPEL"].str.strip().ne("") & out["IDPEL"].str.lower().ne("nan")]
    if out.empty:
        raise DbUpdateError(f"Export billing {thblrek} tidak memuat baris data yang valid")

    out["KEY"] = out["IDPEL"] + "_" + out["BULAN"].astype(str)
    return out[KOLOM_REKENING].reset_index(drop=True)


def parse_kode_baca_export(xlsx_bytes, kdbaca=None, blth=None):
    """Laporan Detail Kode Baca Tunggal (bytes .xlsx) -> DataFrame stan baca.

    Membuang blok judul di atas header serta baris ekor "TOTAL: n DATA" dan
    "Diakses oleh ..." - keduanya tidak punya IDPEL, jadi satu filter cukup.
    `blth` = bulan rekening yang diminta, disimpan di kolom BLTH.
    """
    label = f" ({kdbaca})" if kdbaca else ""
    try:
        raw = pd.read_excel(io.BytesIO(xlsx_bytes), header=KODE_BACA_HEADER_ROW)
    except Exception as e:
        raise DbUpdateError(f"Tidak bisa membaca laporan kode baca{label}: {e}")

    kol = _kolom_lower(raw)
    hilang = [k for k in ("idpel", "stan meter", "tgl baca") if k not in kol]
    if hilang:
        raise DbUpdateError(
            f"Laporan kode baca{label} tidak memuat kolom: " + ", ".join(hilang)
            + ".\nKolom yang ditemukan: " + ", ".join(sorted(kol.keys()))
        )

    idpel_num = pd.to_numeric(raw[kol["idpel"]], errors="coerce")
    raw = raw[idpel_num.notna()].copy()
    if raw.empty:
        # Kategori tanpa pelanggan itu wajar (mis. GANGGUAN METER sering kosong).
        return pd.DataFrame(columns=KOLOM_STAN_BACA)

    out = pd.DataFrame(index=raw.index)
    out["IDPEL"] = _idpel_teks(raw[kol["idpel"]])
    out["STAN METER"] = pd.to_numeric(raw[kol["stan meter"]], errors="coerce")
    out["STAN BACA"] = (
        pd.to_numeric(raw[kol["stan baca"]], errors="coerce")
        if "stan baca" in kol
        else pd.NA
    )
    # TGL BACA dibiarkan string "DD/MM/YYYY HH:MM:SS" apa adanya supaya
    # loader.load_stanbaca_data yang mem-parsing dengan dayfirst=True tetap
    # mendapat bentuk yang sama seperti database lama.
    out["TGL BACA"] = raw[kol["tgl baca"]].astype(str).str.strip()
    out["KD BACA"] = (
        raw[kol["kd baca"]].astype(str).str.strip() if "kd baca" in kol else ""
    )
    out["BLTH"] = str(blth) if blth else pd.NA

    out = out.dropna(subset=["STAN METER"])
    out = out[out["TGL BACA"].str.lower().ne("nan") & out["TGL BACA"].ne("")]
    return out[KOLOM_STAN_BACA].reset_index(drop=True)


# =========================
# APPEND
# =========================

def _cek_terkunci(path):
    """Raise kalau file sedang dibuka Excel (ada sibling ~$nama)."""
    folder = os.path.dirname(os.path.abspath(path))
    nama = os.path.basename(path)
    if os.path.exists(os.path.join(folder, "~$" + nama)):
        raise DbUpdateError(
            f"File '{nama}' sedang dibuka di Excel. Tutup dulu, lalu ulangi update."
        )


def _backup(path):
    """Salin database lama ke folder backup. Return path backup, atau None."""
    if not os.path.exists(path):
        return None
    os.makedirs(DB_BACKUP_DIR, exist_ok=True)
    nama, ext = os.path.splitext(os.path.basename(path))
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    tujuan = os.path.join(DB_BACKUP_DIR, f"{nama}_{stamp}{ext}")
    shutil.copy2(path, tujuan)
    return tujuan


def _tulis_xlsx(df, path):
    """Tulis DataFrame ke .xlsx secara atomik (tmp -> os.replace)."""
    _cek_terkunci(path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    # Ekstensi tmp harus tetap .xlsx: pandas.to_excel memilih writer dari
    # ekstensi file dan menolak apa pun selain format yang dikenal.
    tmp = path + ".tmp.xlsx"
    try:
        df.to_excel(tmp, index=False, engine="xlsxwriter")
        os.replace(tmp, path)
    except PermissionError:
        _hapus_diam(tmp)
        raise DbUpdateError(
            f"Tidak bisa menulis '{os.path.basename(path)}' - kemungkinan "
            f"filenya sedang dibuka di Excel. Tutup dulu, lalu ulangi update."
        )
    except Exception as e:
        _hapus_diam(tmp)
        raise DbUpdateError(f"Gagal menulis {os.path.basename(path)}: {e}")


def _hapus_diam(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _baca_db_lama(path):
    """Baca database yang berlaku sekarang. None kalau belum ada / tidak terbaca."""
    if not path or not os.path.exists(path):
        return None
    try:
        return _read_excel_auto(path)
    except Exception:
        return None


def append_rekening(df_baru, unitup):
    """Gabungkan baris baru ke database rekening UNIT tsb. Return dict statistik.

    `unitup` menentukan file tujuan. Wajib: tanpa itu, data unit berbeda bisa
    menyatu di satu file tanpa penanda apa pun - database ini tidak punya kolom
    unit, jadi percampurannya tidak akan pernah ketahuan.
    """
    if df_baru is None or df_baru.empty:
        raise DbUpdateError("Tidak ada baris rekening untuk ditambahkan")
    if not unitup:
        raise DbUpdateError("Unit tidak diketahui - database tidak bisa ditulis")

    sumber = db_path(unitup)
    tujuan = db_path_baru(unitup)
    lama = _baca_db_lama(sumber)

    if lama is not None and not lama.empty:
        kurang = [k for k in ("IDPEL", "BULAN") if k not in lama.columns]
        if kurang:
            raise DbUpdateError(
                f"Database rekening lama ({os.path.basename(sumber)}) tidak punya "
                f"kolom {', '.join(kurang)} - file ini bukan database rekening."
            )
        lama = lama.copy()
        lama["IDPEL"] = lama["IDPEL"].astype(str).str.strip()
        lama["BULAN"] = pd.to_numeric(lama["BULAN"], errors="coerce").astype("int64")
        # KEY di file lama kadang kosong/berbeda format; bangun ulang supaya
        # dedupe memakai kunci yang sama persis di kedua sisi.
        lama["KEY"] = lama["IDPEL"] + "_" + lama["BULAN"].astype(str)
        for k in KOLOM_REKENING:
            if k not in lama.columns:
                lama[k] = pd.NA
        lama = lama[KOLOM_REKENING]
        n_lama = len(lama)
        gabung = pd.concat([lama, df_baru], ignore_index=True)
    else:
        n_lama = 0
        gabung = df_baru.copy()

    # keep="last": baris hasil download menang atas baris lama dengan KEY sama,
    # jadi menarik ulang satu bulan berfungsi sebagai koreksi, bukan duplikasi.
    gabung = gabung.drop_duplicates(subset=["KEY"], keep="last")
    gabung = gabung.sort_values(["BULAN", "IDPEL"]).reset_index(drop=True)

    backup = _backup(sumber) if sumber and os.path.exists(sumber) else None
    _tulis_xlsx(gabung, tujuan)

    return {
        "path": tujuan,
        "unitup": unitup,
        "backup": backup,
        "n_lama": n_lama,
        "n_diunduh": len(df_baru),
        "n_baru": len(gabung) - n_lama,
        "n_total": len(gabung),
        "bulan": sorted(gabung["BULAN"].unique().tolist()),
    }


def _bulan_baca(seri_tgl):
    """Kunci bulan dari TGL BACA ('MM/YYYY'), untuk dedupe stan baca."""
    tgl = pd.to_datetime(seri_tgl, dayfirst=True, errors="coerce")
    return tgl.dt.strftime("%Y%m")


def _bulan_rekening(seri_bulan_baca):
    """'YYYYMM' bulan baca -> 'YYYYMM' bulan rekening (bulan baca + 1)."""
    tgl = pd.to_datetime(seri_bulan_baca, format="%Y%m", errors="coerce")
    return (tgl + pd.DateOffset(months=1)).dt.strftime("%Y%m")


def _blth_teks(seri):
    """Kolom BLTH -> 'YYYYMM' atau NA (dibaca dari Excel bisa jadi float)."""
    angka = pd.to_numeric(seri, errors="coerce")
    return angka.map(lambda v: str(int(v)) if pd.notna(v) else pd.NA)


def append_stanbaca(df_baru, unitup):
    """Gabungkan baris baru ke database stan baca UNIT tsb. Return dict statistik."""
    if df_baru is None or df_baru.empty:
        raise DbUpdateError("Tidak ada baris stan baca untuk ditambahkan")
    if not unitup:
        raise DbUpdateError("Unit tidak diketahui - database tidak bisa ditulis")

    sumber = stanbaca_db_path(unitup)
    tujuan = stanbaca_db_path_baru(unitup)
    lama = _baca_db_lama(sumber)

    if lama is not None and not lama.empty:
        lama = lama.copy()
        kol = _kolom_lower(lama)
        # Samakan nama kolom ke skema kanonik sebelum digabung.
        rename = {kol[k.lower()]: k for k in KOLOM_STAN_BACA if k.lower() in kol}
        lama = lama.rename(columns=rename)
        for k in KOLOM_STAN_BACA:
            if k not in lama.columns:
                lama[k] = pd.NA
        lama = lama[KOLOM_STAN_BACA]
        if lama["IDPEL"].isna().all():
            raise DbUpdateError(
                f"Database stan baca lama ({os.path.basename(sumber)}) tidak punya "
                f"kolom IDPEL - file ini bukan database stan baca."
            )
        lama["IDPEL"] = lama["IDPEL"].astype(str).str.strip()
        lama["TGL BACA"] = lama["TGL BACA"].astype(str).str.strip()
        lama["BLTH"] = _blth_teks(lama["BLTH"])
        n_lama = len(lama)
        gabung = pd.concat([lama, df_baru], ignore_index=True)
    else:
        n_lama = 0
        gabung = df_baru.copy()

    # Satu pelanggan boleh punya banyak baris (satu per bulan baca), tapi tidak
    # boleh dua baris untuk bulan baca yang sama - itulah yang dianggap ulangan.
    # Cerminan dari groupby(["IDPEL","BULAN"]).tail(1) di loader.
    # Kunci bulan = BULAN REKENING: BLTH kalau ada, selain itu tebakan dari
    # TGL BACA + 1 (baris lama). Seluruh UI - termasuk cek coverage - juga
    # berbicara dalam bulan rekening.
    gabung["BLTH"] = _blth_teks(gabung["BLTH"])
    gabung["_BLN"] = gabung["BLTH"].fillna(
        _bulan_rekening(_bulan_baca(gabung["TGL BACA"]))
    )
    gabung = gabung.dropna(subset=["_BLN"])
    gabung = gabung.drop_duplicates(subset=["IDPEL", "_BLN"], keep="last")
    gabung = gabung.sort_values(["_BLN", "IDPEL"])
    bulan = sorted(gabung["_BLN"].unique().tolist())
    gabung = gabung.drop(columns=["_BLN"]).reset_index(drop=True)

    backup = _backup(sumber) if sumber and os.path.exists(sumber) else None
    _tulis_xlsx(gabung, tujuan)

    return {
        "path": tujuan,
        "unitup": unitup,
        "backup": backup,
        "n_lama": n_lama,
        "n_diunduh": len(df_baru),
        "n_baru": len(gabung) - n_lama,
        "n_total": len(gabung),
        "bulan": bulan,
    }
