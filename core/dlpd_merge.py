"""
Penggabung export DLPD + DPM jadi satu file input aplikasi.

Export DLPD sudah memuat semua kolom yang dibutuhkan loader, KECUALI
`kelainan_bc_meter` (jenis kelainan hasil baca meter di lapangan) yang hanya
ada di export DPM. Modul ini melookup `idpel` DLPD ke DPM lalu menulis hasil
gabungannya ke kolom `keterangan_dlpd`:

    "GANTI KWH METER | M KWH MAXIMUM"
     ^ kelainan_bc_meter  ^ keterangan_dlpd asli

Baris DLPD yang idpel-nya tidak ada di DPM dibiarkan apa adanya (tanpa awalan),
bukan diberi penanda - jumlahnya dilaporkan lewat statistik supaya ketahuan
kalau ternyata banyak yang tidak cocok.

Bentuk gabungan inilah yang menghidupkan dua aturan yang selama ini diam:
filter sheet PRIORITAS_KELAINAN di core/excel.py dan kata kunci "meter tidak
terbaca" di core/koreksi.py - keduanya ditulis memakai kosakata
`kelainan_bc_meter` yang sebelumnya tidak pernah masuk ke data.
"""

import os

import pandas as pd

from core.db_updater import DbUpdateError, _idpel_teks, _tulis_xlsx
from core.loader import SEPARATOR_KELAINAN, _read_excel_auto


def _kolom_lower(df):
    return {str(c).strip().lower(): c for c in df.columns}


def _wajib(kol, nama_file, dibutuhkan):
    hilang = [k for k in dibutuhkan if k not in kol]
    if hilang:
        raise DbUpdateError(
            f"File {nama_file} tidak memuat kolom: {', '.join(hilang)}."
            f"\nKolom yang ditemukan: {', '.join(sorted(kol.keys()))}"
        )


def gabung_dlpd_dpm(path_dlpd, path_dpm, path_keluar):
    """Gabungkan kelainan_bc_meter DPM ke keterangan_dlpd DLPD.

    Return dict statistik: n_dlpd, n_dpm, n_cocok, n_tak_cocok, path.
    """
    try:
        dlpd = _read_excel_auto(path_dlpd)
    except Exception as e:
        raise DbUpdateError(f"Tidak bisa membaca export DLPD: {e}")
    try:
        dpm = _read_excel_auto(path_dpm)
    except Exception as e:
        raise DbUpdateError(f"Tidak bisa membaca export DPM: {e}")

    kol_dlpd = _kolom_lower(dlpd)
    kol_dpm = _kolom_lower(dpm)
    _wajib(kol_dlpd, os.path.basename(path_dlpd), ("idpel", "keterangan_dlpd"))
    _wajib(kol_dpm, os.path.basename(path_dpm), ("idpel", "kelainan_bc_meter"))

    # IDPEL WAJIB lewat _idpel_teks di kedua sisi. Kolom idpel datang sebagai
    # angka, dan satu sel kosong saja sudah membuat pandas menjadikannya float -
    # astype(str) lalu menghasilkan "443200000197.0" dan SELURUH lookup meleset
    # tanpa gejala apa pun (hasilnya cuma "tidak ada yang cocok").
    idpel_dlpd = _idpel_teks(dlpd[kol_dlpd["idpel"]])
    idpel_dpm = _idpel_teks(dpm[kol_dpm["idpel"]])

    bc = dpm[kol_dpm["kelainan_bc_meter"]].fillna("").astype(str).str.strip()
    peta = pd.DataFrame({"_ID": idpel_dpm, "_BC": bc})
    peta = peta[peta["_ID"].str.strip().ne("") & peta["_ID"].str.lower().ne("nan")]
    # Satu idpel bisa muncul lebih dari sekali kalau beberapa kd proses ditarik;
    # ambil yang terakhir, konsisten dengan dedupe di db_updater.
    peta = peta.drop_duplicates(subset=["_ID"], keep="last").set_index("_ID")["_BC"]

    ket = dlpd[kol_dlpd["keterangan_dlpd"]].fillna("").astype(str).str.strip()
    cocok = idpel_dlpd.map(peta)
    ada = cocok.notna() & cocok.fillna("").str.strip().ne("")

    # Jangan tempel awalan dua kali kalau filenya ternyata sudah pernah
    # digabung - hasilnya akan jadi "NORMAL | NORMAL | N KWH ..." dan
    # kelainan_meter() tetap membaca segmen pertama, jadi kerusakannya diam.
    sudah = ket.str.contains(SEPARATOR_KELAINAN, regex=False)
    ada = ada & ~sudah

    hasil = dlpd.copy()
    hasil[kol_dlpd["keterangan_dlpd"]] = ket.where(
        ~ada, cocok.fillna("").str.strip() + SEPARATOR_KELAINAN + ket
    )

    _tulis_xlsx(hasil, path_keluar)

    return {
        "path": path_keluar,
        "n_dlpd": len(dlpd),
        "n_dpm": len(dpm),
        "n_cocok": int(ada.sum()),
        # Baris yang memang sudah bergabung tidak dihitung "tidak cocok" -
        # itu bukan kegagalan lookup.
        "n_tak_cocok": int(len(dlpd) - ada.sum() - sudah.sum()),
        "n_sudah_gabung": int(sudah.sum()),
    }
