"""
Baca sheet KOREKSI_STAND dari file hasil analisa dan pilah jenis koreksinya.

Modul ini murni: tanpa jaringan dan tanpa UI, supaya aturan pemilahnya bisa
diuji langsung terhadap batch koreksi nyata.

Aturan pemilah, diuji pada 1.172 baris batch 202610-202611:
- JAM_NYALA >= 720 -> jalur 720. CAP-720 = MURNI, pilihan lain = ANOMALI.
- JAM_NYALA <  720 -> Koreksi Billing.
Jalurnya cocok di semua baris. Kategorinya cocok 1.169 baris: 3 baris CAP-720
dulu dikirim sebagai ANOMALI, dan di sini menjadi MURNI.

Batas 720 sengaja konstanta, bukan `jam_nyala_tinggi_min`: ini aturan portal
("Pemakaian 720 Jam Nyala ke atas, silahkan melakukan koreksi pada menu Koreksi
Billing 720"), jadi tidak boleh ikut berubah saat ambang analisa disetel.

Nilai yang dipakai adalah nilai cache Excel, bukan hasil hitung ulang: logika
perbandingan Excel berbeda dari Python ('rata2' sama dengan 'RATA2' di Excel,
N("REQ BU") = 0), jadi menghitung ulang bisa menghasilkan stan yang lain dari
yang dilihat operator di layar.
"""

import os
import re

import pandas as pd
from openpyxl import load_workbook

from core.koreksi import (
    PILIHAN_BIARKAN,
    PILIHAN_CAP720,
    PILIHAN_BUTUH_KWH_MANUAL,
    PILIHAN_OPTIONS,
)

SHEET_KOREKSI = "KOREKSI_STAND"
STATUS_CABUT_PASANG = "CABUT_PASANG"

BATAS_JAM_NYALA_720 = 720

JENIS_MURNI = "720 MURNI"
JENIS_ANOMALI = "720 ANOMALI"
JENIS_BILLING = "KOREKSI BILLING"
JENIS_PERLU_DICEK = "PERLU DICEK"
JENIS_TIDAK = "TIDAK DIKOREKSI"

JALUR_720 = "720"
JALUR_BILLING = "BILLING"

KOLOM_WAJIB = (
    "IDPEL", "STATUS", "STAND_LALU", "STAND_KINI", "JAM_NYALA", "PILIHAN",
    "KWH_MANUAL", "STAN_MANUAL", "STAN BARU", "ALASAN KOREKSI",
)

# ='>720JN'!V2 atau =Penurunan!V37 (nama sheet dikutip hanya kalau perlu).
_POLA_REFERENSI = re.compile(
    r"^=\s*(?:'((?:[^']|'')+)'|([^'!]+))!\$?([A-Z]+)\$?(\d+)$"
)
_POLA_BLTH = re.compile(r"^20\d{2}(0[1-9]|1[0-2])$")


class KoreksiFileError(Exception):
    """File tidak bisa dipakai. Pesannya langsung ditampilkan ke operator."""


def blth_dari_path(path):
    """BLTH dari folder `hasil/<blth>/`. None kalau file ada di tempat lain."""
    folder = os.path.basename(os.path.dirname(os.path.abspath(path)))
    return folder if _POLA_BLTH.match(folder) else None


def _teks(nilai):
    """Nilai sel sebagai teks bersih; 123.0 menjadi "123", kosong menjadi ""."""
    if nilai is None:
        return ""
    if isinstance(nilai, bool):
        return str(nilai)
    if isinstance(nilai, float) and nilai.is_integer():
        return str(int(nilai))
    return str(nilai).strip()


def _angka(nilai):
    """float dari sel, atau None. Teks dan nilai error Excel menjadi None."""
    if nilai is None or isinstance(nilai, bool):
        return None
    if isinstance(nilai, (int, float)):
        return float(nilai)
    try:
        return float(str(nilai).strip())
    except ValueError:
        return None


def _baca_baris(ws):
    """(header, baris) dari sheet; baris menyimpan nomor baris Excel-nya."""
    rows = ws.iter_rows(values_only=True)
    try:
        header = [_teks(h) for h in next(rows)]
    except StopIteration:
        return [], []
    data = []
    for nomor, row in enumerate(rows, start=2):
        if any(v is not None and v != "" for v in row):
            data.append((nomor, dict(zip(header, row))))
    return header, data


def _idpel_per_baris(wb_nilai, cache, sheet):
    """{nomor baris: IDPEL} satu sheet status. None kalau sheet tidak ada."""
    if sheet not in cache:
        if sheet not in wb_nilai.sheetnames:
            cache[sheet] = None
        else:
            _, data = _baca_baris(wb_nilai[sheet])
            cache[sheet] = {n: _teks(r.get("IDPEL")) for n, r in data}
    return cache[sheet]


def _sumber_cocok(formula, idpel, wb_nilai, cache):
    """True kalau formula PILIHAN menunjuk baris milik IDPEL yang sama.

    Kolom IDPEL statis sedangkan formulanya menunjuk baris tetap. Kalau sheet
    status diurutkan di Excel, IDPEL bisa berpasangan dengan pilihan pelanggan
    lain tanpa tanda apa pun di KOREKSI_STAND.

    File baru mencari lewat IDPEL (INDEX/MATCH), jadi selalu sejajar. Pemeriksaan
    nomor baris tetap ada untuk file lama.
    """
    if "MATCH(" in str(formula or "").upper():
        return True
    cocok = _POLA_REFERENSI.match(str(formula or "").strip())
    if not cocok:
        return False
    sheet = (cocok.group(1) or cocok.group(2)).replace("''", "'")
    peta = _idpel_per_baris(wb_nilai, cache, sheet)
    return bool(peta) and peta.get(int(cocok.group(4))) == idpel


def _periksa_koreksi(baris, sejajar, ganda):
    """Daftar masalah yang memblokir satu baris koreksi."""
    masalah = []
    idpel = baris["IDPEL"]
    pilihan = baris["PILIHAN"]
    jam = baris["JAM_NYALA"]
    stan = baris["STAN_BARU_MENTAH"]

    if not idpel.isdigit():
        masalah.append("IDPEL tidak valid")
    if ganda:
        masalah.append("IDPEL muncul lebih dari sekali")
    if not sejajar:
        masalah.append(
            "Baris tidak sejajar dengan sheet status, kemungkinan sheet "
            "diurutkan setelah file dibuat"
        )
    if pilihan not in PILIHAN_OPTIONS:
        masalah.append(f"PILIHAN tidak dikenal: {pilihan or '(kosong)'}")
    if pilihan in PILIHAN_BUTUH_KWH_MANUAL and _angka(baris["KWH_MANUAL"]) is None:
        masalah.append(f"KWH_MANUAL harus berisi angka untuk pilihan {pilihan}")

    nilai_stan = _angka(stan)
    if _teks(stan) == "":
        masalah.append("STAN BARU kosong")
    elif nilai_stan is None:
        masalah.append(f"STAN BARU bukan angka: {_teks(stan)}")
    elif nilai_stan < 0:
        masalah.append("STAN BARU negatif")
    elif not nilai_stan.is_integer():
        masalah.append("STAN BARU harus bilangan bulat")
    elif nilai_stan == _angka(baris["STAND_KINI"]):
        masalah.append("STAN BARU sama dengan stand sekarang")

    if not baris["ALASAN"]:
        masalah.append("ALASAN KOREKSI kosong")
    if jam is None:
        masalah.append("JAM_NYALA bukan angka")
    elif pilihan == PILIHAN_CAP720 and jam < BATAS_JAM_NYALA_720:
        masalah.append("CAP-720 dipilih padahal jam nyala di bawah 720")
    return masalah


def pilah_jenis(jam_nyala, pilihan):
    """(jenis, jalur, kategori) untuk baris koreksi yang sudah lolos validasi."""
    if jam_nyala >= BATAS_JAM_NYALA_720:
        if pilihan == PILIHAN_CAP720:
            return JENIS_MURNI, JALUR_720, "MURNI"
        return JENIS_ANOMALI, JALUR_720, "ANOMALI"
    return JENIS_BILLING, JALUR_BILLING, ""


def baca_koreksi(path):
    """Baca dan pilah KOREKSI_STAND menjadi satu DataFrame.

    `df.attrs["tidak_sejajar_tanpa_koreksi"]` menghitung baris tidak sejajar
    yang tidak membawa koreksi. Baris itu tidak bisa dikirim, tetapi menandakan
    sheet status pernah diurutkan, jadi UI perlu memperingatkannya.
    """
    try:
        wb_nilai = load_workbook(path, read_only=True, data_only=True)
        wb_formula = load_workbook(path, read_only=True, data_only=False)
    except PermissionError:
        raise KoreksiFileError(
            "File tidak bisa dibuka. Tutup file ini di Excel lalu coba lagi."
        )
    except OSError as e:
        raise KoreksiFileError(f"File tidak bisa dibuka: {e}")
    except Exception as e:
        raise KoreksiFileError(f"File bukan workbook Excel yang valid: {e}")

    try:
        if SHEET_KOREKSI not in wb_nilai.sheetnames:
            raise KoreksiFileError(
                f"Sheet {SHEET_KOREKSI} tidak ada. Pilih file hasil analisa "
                "SIMBA yang memiliki baris untuk dikoreksi."
            )
        header, data = _baca_baris(wb_nilai[SHEET_KOREKSI])
        kurang = [k for k in KOLOM_WAJIB if k not in header]
        if kurang:
            raise KoreksiFileError(
                f"Kolom berikut tidak ada di {SHEET_KOREKSI}: {', '.join(kurang)}"
            )
        if not data:
            raise KoreksiFileError(f"Sheet {SHEET_KOREKSI} tidak berisi data.")
        # Keluaran aplikasi belum menyimpan hasil formula sampai dibuka di Excel.
        if not any(_teks(r.get("PILIHAN")) for _, r in data):
            raise KoreksiFileError(
                "Nilai koreksi di file ini belum tersimpan. Buka file di Excel, "
                "isi pilihan koreksi, simpan, tutup, lalu pilih file ini lagi."
            )

        kolom_pilihan = header.index("PILIHAN")
        rows_formula = wb_formula[SHEET_KOREKSI].iter_rows(values_only=True)
        next(rows_formula)
        formula_per_baris = {
            nomor: row[kolom_pilihan] if len(row) > kolom_pilihan else None
            for nomor, row in enumerate(rows_formula, start=2)
        }

        jumlah_idpel = {}
        for _, r in data:
            idpel = _teks(r.get("IDPEL"))
            jumlah_idpel[idpel] = jumlah_idpel.get(idpel, 0) + 1

        cache_sheet = {}
        hasil = []
        tidak_sejajar_tanpa_koreksi = 0
        for nomor, r in data:
            baris = {
                "BARIS": nomor,
                "IDPEL": _teks(r.get("IDPEL")),
                "STATUS": _teks(r.get("STATUS")),
                "STAND_LALU": _angka(r.get("STAND_LALU")),
                "STAND_KINI": _angka(r.get("STAND_KINI")),
                "JAM_NYALA": _angka(r.get("JAM_NYALA")),
                "PILIHAN": _teks(r.get("PILIHAN")).upper(),
                "KWH_MANUAL": r.get("KWH_MANUAL"),
                "STAN_MANUAL": r.get("STAN_MANUAL"),
                "STAN_BARU_MENTAH": r.get("STAN BARU"),
                "ALASAN": _teks(r.get("ALASAN KOREKSI")),
            }
            sejajar = _sumber_cocok(
                formula_per_baris.get(nomor), baris["IDPEL"], wb_nilai, cache_sheet,
            )
            tanpa_koreksi = (
                baris["PILIHAN"] in ("", PILIHAN_BIARKAN)
                and _teks(baris["STAN_BARU_MENTAH"]) == ""
            )
            jenis = jalur = kategori = perhatian = ""
            masalah = []
            if tanpa_koreksi:
                jenis = JENIS_TIDAK
                if not sejajar:
                    tidak_sejajar_tanpa_koreksi += 1
            else:
                masalah = _periksa_koreksi(
                    baris, sejajar, jumlah_idpel[baris["IDPEL"]] > 1,
                )
                if masalah:
                    jenis = JENIS_PERLU_DICEK
                else:
                    jenis, jalur, kategori = pilah_jenis(
                        baris["JAM_NYALA"], baris["PILIHAN"],
                    )
                    if baris["STATUS"] == STATUS_CABUT_PASANG:
                        perhatian = (
                            "Baris cabut/pasang: koreksi stand akhir tidak "
                            "memperbaiki stand cabut atau pasang"
                        )

            kirimkan = not masalah and not tanpa_koreksi
            baris.update({
                "STAN_BARU": (
                    int(_angka(baris["STAN_BARU_MENTAH"])) if kirimkan else None
                ),
                "JENIS": jenis,
                "JALUR": jalur,
                "KATEGORI": kategori,
                "MASALAH": "; ".join(masalah),
                "PERHATIAN": perhatian,
            })
            del baris["STAN_BARU_MENTAH"]
            hasil.append(baris)
    finally:
        wb_nilai.close()
        wb_formula.close()

    df = pd.DataFrame(hasil)
    df["STAN_BARU"] = df["STAN_BARU"].astype("Int64")
    df.attrs["tidak_sejajar_tanpa_koreksi"] = tidak_sejajar_tanpa_koreksi
    return df
