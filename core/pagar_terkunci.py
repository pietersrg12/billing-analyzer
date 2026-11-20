"""
Daftar Pagar Terkunci / meter tak terjangkau.

Meter yang tidak terjangkau petugas baca biasanya muncul dengan dua cara:

A. STAND 1 (sumber ACMT): petugas mengisi stan meter <= 1 karena tidak bisa
   membaca. Diambil dari laporan Detail Kode Baca Tunggal ACMT, kolom
   STAN METER (stan kini setelah dirubah) - BUKAN STAN BACA.
B. KODE BACA AKSES (sumber ACMT): KD BACA petugas berarti akses terhalang
   (1 KWH METER TINGGI, 3 ANJING GALAK, E RUMAH TUTUP, I DIDALAM BANGUNAN,
   W BENCANA). kelainan_bc_meter billing TIDAK dipakai - isinya bisa beda
   dari ACMT untuk pelanggan yang sama.

Hasilnya satu baris per IDPEL, dihitung berapa kali kejadian yang sama
berulang dalam 6 bulan sebelumnya, lalu ditulis ke Excel per biller.

Semua fungsi di sini murni (DataFrame masuk, DataFrame keluar) supaya bisa
dites tanpa UI dan tanpa jaringan; pengunduhan ada di core/pipeline.py.
"""

import io
import numbers
import os
import re
from datetime import datetime

import pandas as pd

from core.db_updater import KODE_BACA_HEADER_ROW, _idpel_teks, _kolom_lower

# Arti KD BACA di laporan Kode Baca Tunggal ACMT (dari operator, 2026-10).
# Aturan B mencocokkan NAMA-nya ke `kode_akses_pagar`, jadi daftar akses tetap
# ditulis dengan nama yang bisa dibaca orang, bukan huruf kode.
KODE_BACA_ACMT = {
    "A": "KWH METER MACET",
    "B": "KWH METER MUNDUR",
    "C": "KWH METER TIDAK ADA",
    "D": "PELANGGAN TIDAK SESUAI RBM",
    "E": "RUMAH TUTUP",
    "F": "RUMAH KOSONG",
    "H": "KWH METER BURAM/PECAH",
    "I": "KWH METER DIDALAM BANGUNAN",
    "J": "SEGEL TIDAK ADA",
    "K": "MCB PERLU DIPERIKSA",
    "L": "TARIF TIDAK SESUAI",
    "M": "KWH KURANG TAGIH",
    "N": "KWH LEBIH TAGIH",
    "U": "PEMADAMAN",
    "W": "BENCANA",
    "Z": "NORMAL",
    "1": "KWH METER TINGGI",
    "2": "GANTI KWH METER",
    "3": "ANJING GALAK",
    "7": "STAN DARI PELANGGAN",
}

# KD BACA yang masuk sheet PRIORITAS_KELAINAN di hasil analisa (core/excel.py).
# Daftar dari operator (2026-10); sengaja terpisah dari kode akses pagar
# terkunci karena tujuannya lain: semua kelainan baca yang perlu dicek, bukan
# hanya yang meternya tak terjangkau.
KODE_PRIORITAS = (
    "C",  # KWH METER TIDAK ADA
    "D",  # PELANGGAN TIDAK SESUAI RBM
    "E",  # RUMAH TUTUP
    "H",  # KWH METER BURAM/PECAH
    "I",  # KWH METER DIDALAM BANGUNAN
    "W",  # BENCANA
    "1",  # KWH METER TINGGI
    "3",  # ANJING GALAK
    "A",  # KWH METER MACET
    "B",  # KWH METER MUNDUR
)

# Kode yang dianggap "akses terhalang" (dicocokkan ke nama KD BACA ACMT). Disalin ke
# unduh_settings.json (`kode_akses_pagar`) supaya bisa ditambah tanpa ubah kode.
KODE_AKSES_DEFAULT = (
    "KWH METER TINGGI",
    "ANJING GALAK",
    "RUMAH TUTUP",
    "KWH METER DIDALAM BANGUNAN",
    "BENCANA",
)

# Label pendek untuk kolom BULAN SEBELUMNYA ("202608(TINGGI)").
SINGKATAN = {
    "KWH METER TINGGI": "TINGGI",
    "ANJING GALAK": "ANJING",
    "RUMAH TUTUP": "TUTUP",
    "KWH METER DIDALAM BANGUNAN": "DLM BANGUNAN",
    "BENCANA": "BENCANA",
}
TANDA_STAND1 = "S1"
ALASAN_STAND1 = "STAND 1"

JENDELA_RIWAYAT = 6        # bulan sebelum BLTH yang dihitung sebagai riwayat
BATAS_STAND1 = 1           # STAN METER <= ini dianggap stand 1
BATAS_METER_BARU = 15      # STAN LALU < ini = meter baru, tidak dilaporkan

RIWAYAT_LABEL = {1: "PERTAMA KALI", 2: "2 KALI", 3: "3 KALI"}
RIWAYAT_LEBIH = "LEBIH DARI 3 KALI"
URUTAN_RIWAYAT = ["PERTAMA KALI", "2 KALI", "3 KALI", RIWAYAT_LEBIH]
LANGKAH = {
    "PERTAMA KALI": "Minta baca ulang / cek foto",
    "2 KALI": "Pantau, konfirmasi ke petugas baca",
    "3 KALI": "Jadwalkan cek lapangan",
    RIWAYAT_LEBIH: "Usulkan pindah meter ke luar pagar / ganti meter / koordinasi pelanggan",
}

KOLOM_ACMT = [
    "IDPEL", "NAMA", "ALAMAT", "TARIF", "DAYA", "KD BACA", "KODE RBM",
    "TGL BACA", "STAN LALU", "STAN METER", "LATITUDE", "LONGITUDE",
    "KATEGORI", "BLTH",
]
_ANGKA_ACMT = ("DAYA", "STAN LALU", "STAN METER", "LATITUDE", "LONGITUDE")
_ALIAS_ACMT = {"KODE RBM": ("kode rbm", "kd rbm", "rbm")}
FORMAT_TGL_ACMT = "%d/%m/%Y %H:%M:%S"

KOLOM_DETAIL = [
    "NO", "IDPEL", "NAMA", "ALAMAT", "TARIF", "DAYA", "BILLER", "HARI BACA",
    "RUTE BACA", "URUT BACA", "GARDU", "TGL BACA", "ALASAN", "KD BACA ACMT",
    "STAND LALU", "STAND METER", "RIWAYAT", "KALI (TERMASUK BULAN INI)",
    "BULAN SEBELUMNYA", "LANGKAH", "LATITUDE", "LONGITUDE",
    "HASIL CEK LAPANGAN", "TINDAK LANJUT",
]
_KOLOM_TEKS = {"IDPEL", "RUTE BACA", "URUT BACA", "HARI BACA", "BILLER"}
_LEBAR = {
    "NO": 6, "IDPEL": 14, "NAMA": 26, "ALAMAT": 32, "TARIF": 7, "DAYA": 9,
    "BILLER": 8, "HARI BACA": 6, "RUTE BACA": 10, "URUT BACA": 7, "GARDU": 14,
    "TGL BACA": 19, "ALASAN": 30, "KD BACA ACMT": 22, "STAND LALU": 10,
    "STAND METER": 10, "RIWAYAT": 18, "KALI (TERMASUK BULAN INI)": 10,
    "BULAN SEBELUMNYA": 34, "LANGKAH": 40, "LATITUDE": 11, "LONGITUDE": 11,
    "HASIL CEK LAPANGAN": 24, "TINDAK LANJUT": 24,
}
_WARNA_RIWAYAT = {
    "PERTAMA KALI": "#E2EFDA",
    "2 KALI": "#FFF2CC",
    "3 KALI": "#FFC7CE",
    RIWAYAT_LEBIH: "#FFC7CE",
}
TANPA_RUTE = "-"


# =========================
# UTIL
# =========================

def _norm(teks):
    """Upper + spasi ganda dirapatkan."""
    if teks is None or (isinstance(teks, float) and pd.isna(teks)):
        return ""
    return re.sub(r"\s+", " ", str(teks)).strip().upper()


def _idpel12(seri):
    """IDPEL -> teks 12 digit (nol di depan dipertahankan)."""
    teks = _idpel_teks(seri.astype(object))
    return teks.where(~teks.str.fullmatch(r"\d{1,12}"), teks.str.zfill(12))


def _angka(seri):
    """Angka berformat Indonesia (koma desimal) -> float."""
    if pd.api.types.is_numeric_dtype(seri):
        return pd.to_numeric(seri, errors="coerce")
    teks = seri.astype(str).str.strip().str.replace(",", ".", regex=False)
    return pd.to_numeric(teks, errors="coerce")


def bulan_sebelumnya(blth, n=JENDELA_RIWAYAT):
    """'202609' -> ['202608', '202607', ...] sebanyak n."""
    p = pd.Period(str(blth), freq="M")
    return [(p - i).strftime("%Y%m") for i in range(1, n + 1)]


def singkat(kode):
    return SINGKATAN.get(kode, kode)


def cocok_akses(kode, daftar):
    """Kode daftar yang cocok dengan `kode` (toleran spasi), atau None."""
    n = _norm(kode)
    if not n:
        return None
    rapat = n.replace(" ", "")
    for k in daftar:
        kn = _norm(k)
        if not kn:
            continue
        if n.startswith(kn) or kn in n or kn.replace(" ", "") in rapat:
            return k
    return None


# =========================
# ACMT
# =========================

def rapikan_acmt(df):
    """Samakan tipe kolom ACMT (dipakai setelah parse maupun baca cache CSV)."""
    out = pd.DataFrame(index=df.index)
    for k in KOLOM_ACMT:
        out[k] = df[k] if k in df.columns else pd.NA
    out["IDPEL"] = _idpel12(out["IDPEL"])
    for k in _ANGKA_ACMT:
        out[k] = _angka(out[k])
    for k in ("NAMA", "ALAMAT", "TARIF", "KD BACA", "KODE RBM", "TGL BACA", "KATEGORI"):
        out[k] = out[k].fillna("").astype(str).str.strip().replace("nan", "")
    out["BLTH"] = out["BLTH"].map(
        lambda v: str(int(float(v))) if pd.notna(v) and str(v).strip() not in ("", "nan") else ""
    )
    out = out[out["IDPEL"].str.fullmatch(r"\d+")]
    return out.reset_index(drop=True)


def parse_acmt_lengkap(xlsx_bytes, kategori=None, blth=None):
    """Laporan Detail Kode Baca Tunggal -> DataFrame KOLOM_ACMT lengkap.

    Beda dari db_updater.parse_kode_baca_export yang hanya menyimpan kolom
    untuk database stan baca: di sini NAMA/ALAMAT/KODE RBM/koordinat ikut.
    """
    raw = pd.read_excel(io.BytesIO(xlsx_bytes), header=KODE_BACA_HEADER_ROW)
    kol = _kolom_lower(raw)
    hilang = [k for k in ("idpel", "stan meter") if k not in kol]
    if hilang:
        raise ValueError(
            f"Laporan ACMT ({kategori}) tidak memuat kolom: {', '.join(hilang)}. "
            f"Kolom yang ada: {', '.join(sorted(kol))}"
        )
    raw = raw[pd.to_numeric(raw[kol["idpel"]], errors="coerce").notna()]
    data = {}
    for k in KOLOM_ACMT:
        for alias in _ALIAS_ACMT.get(k, (k.lower(),)):
            if alias in kol:
                data[k] = raw[kol[alias]]
                break
    df = pd.DataFrame(data, index=raw.index)
    if kategori is not None:
        df["KATEGORI"] = kategori
    if blth is not None:
        df["BLTH"] = str(blth)
    return rapikan_acmt(df)


def huruf_kode_baca(kd):
    """'1', '1.0', '1-KWH METER TINGGI', ' z ' -> '1' / 'Z'."""
    k = _norm(kd).split("-", 1)[0].strip()
    return k[:-2] if k.endswith(".0") else k


def nama_kode_baca(kd):
    """KD BACA ACMT -> nama ('I' -> 'KWH METER DIDALAM BANGUNAN'), '' kalau tak dikenal."""
    return KODE_BACA_ACMT.get(huruf_kode_baca(kd), "")


def label_kode_baca(kd):
    """'I' -> 'I-KWH METER DIDALAM BANGUNAN' untuk ditampilkan."""
    h = huruf_kode_baca(kd)
    nama = KODE_BACA_ACMT.get(h)
    return f"{h}-{nama}" if nama else h


def kode_akses_acmt(df_acmt, daftar=KODE_AKSES_DEFAULT):
    """Aturan B dari KD BACA ACMT. Return (df[IDPEL, KODE, KODE_ASLI], hitungan).

    hitungan = jumlah pelanggan per kode berlabel ('I-KWH METER ...': n),
    termasuk kode yang tidak dikenal, supaya ejaan/kode baru kelihatan di log.
    """
    if df_acmt is None or df_acmt.empty:
        return pd.DataFrame(columns=["IDPEL", "KODE", "KODE_ASLI"]), pd.Series(dtype="int64")
    d = df_acmt.drop_duplicates(subset=["IDPEL"], keep="first")
    label = d["KD BACA"].map(label_kode_baca)
    hitung = label[label.ne("")].value_counts()
    df = pd.DataFrame({"IDPEL": d["IDPEL"].values, "KODE_ASLI": label.values})
    df["KODE"] = d["KD BACA"].map(lambda k: cocok_akses(nama_kode_baca(k), daftar)).values
    df = df[df["KODE"].notna()]
    return df[["IDPEL", "KODE", "KODE_ASLI"]].reset_index(drop=True), hitung


def stand1_acmt(df_acmt, batas_meter_baru=BATAS_METER_BARU):
    """Pelanggan stand 1 dari ACMT. Return (df_stand1, n_meter_baru).

    Stand 1 = STAN METER <= 1 dan BUKAN (STAN LALU < batas_meter_baru).
    STAN LALU di bawah batas berarti meter baru (wajar stand kecil) - tidak
    dilaporkan, hanya dihitung. STAN LALU kosong tetap dilaporkan. Batasnya
    diatur di Pengaturan Rule (`pagar_stan_lalu_meter_baru`).
    """
    if df_acmt is None or df_acmt.empty:
        return pd.DataFrame(columns=KOLOM_ACMT), 0
    d = df_acmt.drop_duplicates(subset=["IDPEL"], keep="first")
    s1 = d["STAN METER"] <= BATAS_STAND1
    baru = d["STAN LALU"] < batas_meter_baru   # NaN -> False
    return d[s1 & ~baru].reset_index(drop=True), int((s1 & baru).sum())


# =========================
# RIWAYAT + GABUNG
# =========================

def riwayat(blth, db_rek=None, db_sb=None, acmt_lalu=None,
            n=JENDELA_RIWAYAT, daftar_acmt=None):
    """Kejadian bulan-bulan sebelum BLTH. Return df long [IDPEL, BULAN, TANDA].

    Stand 1 (TANDA "S1") bila STAND <= 1 di database rekening (IDPEL, BULAN,
    STAND), database stan baca (IDPEL, BULAN, STAND), atau ACMT bulan lalu
    (STAN METER). Kode akses (TANDA = singkatan) dari KD BACA ACMT bulan lalu
    - database stan baca dan unduhan ACMT - bila `daftar_acmt` diberikan.
    Hanya `n` bulan terakhir sebelum BLTH yang dihitung, untuk semua sumber.
    """
    bulan = set(bulan_sebelumnya(blth, n))
    frames = []

    # KD BACA di database stan baca = kode baca ACMT yang sudah tersimpan.
    if daftar_acmt and db_sb is not None and "KD BACA" in db_sb.columns:
        d = db_sb[db_sb["BULAN"].astype(str).isin(bulan)]
        nama = d["KD BACA"].map(lambda k: cocok_akses(nama_kode_baca(k), daftar_acmt))
        d = d[nama.notna()]
        frames.append(pd.DataFrame({
            "IDPEL": _idpel12(d["IDPEL"]).values, "BULAN": d["BULAN"].astype(str).values,
            "TANDA": nama[nama.notna()].map(singkat).values,
        }))

    for db in (db_rek, db_sb):
        if db is None or db.empty:
            continue
        d = pd.DataFrame({
            "IDPEL": _idpel12(db["IDPEL"]),
            "BULAN": pd.to_numeric(db["BULAN"], errors="coerce"),
            "STAND": pd.to_numeric(db["STAND"], errors="coerce"),
        }).dropna(subset=["BULAN"])
        d["BULAN"] = d["BULAN"].astype("int64").astype(str)
        d = d[d["BULAN"].isin(bulan) & (d["STAND"] <= BATAS_STAND1)]
        frames.append(d.assign(TANDA=TANDA_STAND1)[["IDPEL", "BULAN", "TANDA"]])

    for bln, df in (acmt_lalu or {}).items():
        if df is None or df.empty or str(bln) not in bulan:
            continue
        d = df[df["STAN METER"] <= BATAS_STAND1]
        frames.append(pd.DataFrame({
            "IDPEL": d["IDPEL"].values, "BULAN": str(bln), "TANDA": TANDA_STAND1,
        }))
        if daftar_acmt:
            k = kode_akses_acmt(df, daftar_acmt)[0]
            frames.append(pd.DataFrame({
                "IDPEL": k["IDPEL"].values, "BULAN": str(bln),
                "TANDA": k["KODE"].map(singkat).values,
            }))

    if not frames:
        return pd.DataFrame(columns=["IDPEL", "BULAN", "TANDA"])
    out = pd.concat(frames, ignore_index=True)
    return out.drop_duplicates().reset_index(drop=True)


def label_riwayat(kali):
    return RIWAYAT_LABEL.get(int(kali), RIWAYAT_LEBIH)


def _tgl_dlpd(v):
    """tglbacaakhir 20260927 -> '27/09/2026'."""
    try:
        return datetime.strptime(str(int(float(v))), "%Y%m%d").strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return ""


def info_dlpd(df_dlpd):
    """Kolom pendukung dari DLPD gabungan: TARIF, DAYA, stand, tgl baca."""
    kol = _kolom_lower(df_dlpd)
    ambil = lambda k: df_dlpd[kol[k]] if k in kol else pd.Series(pd.NA, index=df_dlpd.index)
    out = pd.DataFrame({
        "IDPEL": _idpel12(ambil("idpel")),
        "TARIF_D": ambil("tarif").fillna("").astype(str).str.strip(),
        "DAYA_D": pd.to_numeric(ambil("daya"), errors="coerce"),
        "SLALWBP_D": pd.to_numeric(ambil("slalwbp"), errors="coerce"),
        "SAHLWBP_D": pd.to_numeric(ambil("sahlwbp"), errors="coerce"),
        "TGL_D": ambil("tglbacaakhir").map(_tgl_dlpd),
    })
    return out.drop_duplicates(subset=["IDPEL"], keep="last")


def rapikan_master(df):
    """Monitoring_Billing_Detail -> IDPEL, NAMA_M, ALAMAT_M, TARIF_M, DAYA_M, KDDK, GARDU."""
    kol = _kolom_lower(df)
    ambil = lambda k: df[kol[k]] if k in kol else pd.Series(pd.NA, index=df.index)
    teks = lambda k: ambil(k).fillna("").astype(str).str.strip().replace("nan", "")
    gardu = teks("namagardu")
    out = pd.DataFrame({
        "IDPEL": _idpel12(ambil("idpel")),
        "NAMA_M": teks("nama"),
        "ALAMAT_M": teks("alamat"),
        "TARIF_M": teks("tarif"),
        "DAYA_M": pd.to_numeric(ambil("daya"), errors="coerce"),
        "KDDK": teks("kddk"),
        "GARDU": gardu.where(gardu.ne(""), teks("kdgardu")),
    })
    return out.drop_duplicates(subset=["IDPEL"], keep="last")


def _isi(utama, cadangan):
    """Kolom `utama`, sel kosong diisi `cadangan`."""
    kosong = utama.isna() | utama.astype(str).str.strip().isin(["", "nan", "<NA>"])
    return utama.where(~kosong, cadangan)


def gabung(df_s1, df_kode, df_acmt=None, df_dlpd=None, master=None, df_riwayat=None):
    """Satu baris per IDPEL yang stand 1 (A) ATAU berkode akses (B)."""
    s1 = set(df_s1["IDPEL"]) if df_s1 is not None and not df_s1.empty else set()
    kode = (df_kode.set_index("IDPEL")["KODE"]
            if df_kode is not None and not df_kode.empty else pd.Series(dtype=object))
    idpel = sorted(s1 | set(kode.index))
    out = pd.DataFrame({"IDPEL": pd.Series(idpel, dtype=object)})
    if out.empty:
        return pd.DataFrame(columns=KOLOM_DETAIL + ["_STAND1", "_KODE"])

    out["_STAND1"] = out["IDPEL"].isin(s1)
    out["_KODE"] = out["IDPEL"].map(kode).fillna("")
    out["ALASAN"] = [
        " + ".join(x for x in ((ALASAN_STAND1 if a else ""), k) if x)
        for a, k in zip(out["_STAND1"], out["_KODE"])
    ]

    # Riwayat bulan sebelumnya
    riw = df_riwayat if df_riwayat is not None else pd.DataFrame(columns=["IDPEL", "BULAN", "TANDA"])
    riw = riw[riw["IDPEL"].isin(out["IDPEL"])]
    if not riw.empty:
        per_bulan = (riw.sort_values(["IDPEL", "BULAN", "TANDA"])
                     .groupby(["IDPEL", "BULAN"])["TANDA"]
                     .agg(lambda t: "+".join(dict.fromkeys(t))).reset_index())
        per_bulan["_TXT"] = per_bulan["BULAN"] + "(" + per_bulan["TANDA"] + ")"
        teks = per_bulan.groupby("IDPEL")["_TXT"].agg(",".join)
        jumlah = per_bulan.groupby("IDPEL")["BULAN"].nunique()
    else:
        teks, jumlah = pd.Series(dtype=object), pd.Series(dtype="int64")
    out["BULAN SEBELUMNYA"] = out["IDPEL"].map(teks).fillna("")
    out["KALI (TERMASUK BULAN INI)"] = out["IDPEL"].map(jumlah).fillna(0).astype(int) + 1
    out["RIWAYAT"] = out["KALI (TERMASUK BULAN INI)"].map(label_riwayat)
    out["LANGKAH"] = out["RIWAYAT"].map(LANGKAH)

    # Data pelanggan: ACMT -> DLPD -> master
    if df_acmt is not None and not df_acmt.empty:
        a = df_acmt.drop_duplicates(subset=["IDPEL"], keep="first").set_index("IDPEL")
        for k in ("NAMA", "ALAMAT", "TARIF", "DAYA", "KODE RBM", "TGL BACA",
                  "STAN LALU", "STAN METER", "LATITUDE", "LONGITUDE", "KD BACA"):
            out[k] = out["IDPEL"].map(a[k])
    else:
        for k in ("NAMA", "ALAMAT", "TARIF", "DAYA", "KODE RBM", "TGL BACA",
                  "STAN LALU", "STAN METER", "LATITUDE", "LONGITUDE", "KD BACA"):
            out[k] = pd.NA

    if df_dlpd is not None and not df_dlpd.empty:
        d = info_dlpd(df_dlpd).set_index("IDPEL")
        out["TARIF"] = _isi(out["TARIF"], out["IDPEL"].map(d["TARIF_D"]))
        out["DAYA"] = _isi(out["DAYA"], out["IDPEL"].map(d["DAYA_D"]))
        out["STAN LALU"] = _isi(out["STAN LALU"], out["IDPEL"].map(d["SLALWBP_D"]))
        out["STAN METER"] = _isi(out["STAN METER"], out["IDPEL"].map(d["SAHLWBP_D"]))
        out["TGL BACA"] = _isi(out["TGL BACA"], out["IDPEL"].map(d["TGL_D"]))

    kddk = pd.Series("", index=out.index)
    out["GARDU"] = ""
    if master is not None and not master.empty:
        m = master.set_index("IDPEL")
        out["NAMA"] = _isi(out["NAMA"], out["IDPEL"].map(m["NAMA_M"]))
        out["ALAMAT"] = _isi(out["ALAMAT"], out["IDPEL"].map(m["ALAMAT_M"]))
        out["TARIF"] = _isi(out["TARIF"], out["IDPEL"].map(m["TARIF_M"]))
        out["DAYA"] = _isi(out["DAYA"], out["IDPEL"].map(m["DAYA_M"]))
        kddk = out["IDPEL"].map(m["KDDK"]).fillna("")
        out["GARDU"] = out["IDPEL"].map(m["GARDU"]).fillna("")

    rute = _isi(out["KODE RBM"], kddk.str[:7]).fillna("").astype(str).str.strip().str[:7]
    out["RUTE BACA"] = rute
    out["BILLER"] = rute.str[3:6].where(rute.str.len() >= 6, TANPA_RUTE)
    out["HARI BACA"] = rute.str[6:7]
    out["URUT BACA"] = kddk.str[7:10]
    out["KD BACA ACMT"] = out["KD BACA"].map(
        lambda k: label_kode_baca(k) if pd.notna(k) and str(k).strip() else "")
    out["STAND LALU"] = pd.to_numeric(out["STAN LALU"], errors="coerce")
    out["STAND METER"] = pd.to_numeric(out["STAN METER"], errors="coerce")
    out["DAYA"] = pd.to_numeric(out["DAYA"], errors="coerce")
    for k in ("NAMA", "ALAMAT", "TARIF", "TGL BACA", "KD BACA ACMT", "GARDU"):
        out[k] = out[k].fillna("").astype(str).replace({"nan": "", "<NA>": ""})
    out["HASIL CEK LAPANGAN"] = ""
    out["TINDAK LANJUT"] = ""

    out = urutkan(out)
    out["NO"] = range(1, len(out) + 1)
    return out[KOLOM_DETAIL + ["_STAND1", "_KODE"]].reset_index(drop=True)


def urutkan(df):
    """HARI BACA -> RUTE -> URUT; baris tanpa rute di belakang."""
    kunci = df.assign(_tanpa=df["RUTE BACA"].eq(""))
    return kunci.sort_values(["_tanpa", "HARI BACA", "RUTE BACA", "URUT BACA", "IDPEL"]) \
        .drop(columns="_tanpa")


def rekap_biller(df, daftar_kode, semua_biller=()):
    """Rekap per biller. Return DataFrame berbaris TOTAL di akhir."""
    kolom_alasan = [ALASAN_STAND1] + list(daftar_kode)
    biller = sorted(set(semua_biller) | set(df["BILLER"])) if not df.empty else sorted(set(semua_biller))
    baris = []
    for b in biller:
        d = df[df["BILLER"] == b]
        r = {"BILLER": b, ALASAN_STAND1: int(d["_STAND1"].sum())}
        for k in daftar_kode:
            r[k] = int((d["_KODE"] == k).sum())
        for lbl in URUTAN_RIWAYAT:
            r[lbl] = int((d["RIWAYAT"] == lbl).sum())
        r["TOTAL"] = len(d)
        baris.append(r)
    rek = pd.DataFrame(baris, columns=["BILLER"] + kolom_alasan + URUTAN_RIWAYAT + ["TOTAL"])
    rek["_tanpa"] = rek["BILLER"].eq(TANPA_RUTE)
    rek = rek.sort_values(["_tanpa", "TOTAL", "BILLER"], ascending=[True, False, True]) \
        .drop(columns="_tanpa").reset_index(drop=True)
    rek.insert(0, "NO", range(1, len(rek) + 1))
    total = {"NO": "", "BILLER": "TOTAL"}
    for k in kolom_alasan + URUTAN_RIWAYAT + ["TOTAL"]:
        total[k] = int(rek[k].sum())
    return pd.concat([rek, pd.DataFrame([total])], ignore_index=True)


# =========================
# EXCEL
# =========================

def _nama_sheet(nama, dipakai):
    nama = re.sub(r"[\[\]:*?/\\]", "_", str(nama) or TANPA_RUTE)[:31] or "_"
    if nama == TANPA_RUTE:
        nama = "TANPA RUTE"
    asli, i = nama, 2
    while nama.upper() in dipakai:
        nama = f"{asli[:28]}_{i}"
        i += 1
    dipakai.add(nama.upper())
    return nama


def tulis_excel(df, path, meta):
    """Tulis daftar ke `path` (xlsxwriter). `meta`: unit, blth, tgl_baca,
    catatan (list str), daftar_kode, semua_biller."""
    import xlsxwriter

    tmp = path + ".tmp.xlsx"
    wb = xlsxwriter.Workbook(tmp, {"nan_inf_to_errors": True})
    f_judul = wb.add_format({"bold": True, "font_size": 14})
    f_sub = wb.add_format({"italic": True, "font_color": "#555555"})
    f_head = wb.add_format({"bold": True, "bg_color": "#1F4E78", "font_color": "white",
                            "border": 1, "text_wrap": True, "valign": "vcenter",
                            "align": "center"})
    f_sel = wb.add_format({"border": 1})
    f_teks = wb.add_format({"border": 1, "num_format": "@"})
    f_total = wb.add_format({"bold": True, "border": 1, "bg_color": "#D9E1F2"})
    f_riw = {k: wb.add_format({"border": 1, "bg_color": v}) for k, v in _WARNA_RIWAYAT.items()}

    dipakai = set()

    # ---- REKAP_BILLER ----
    rek = rekap_biller(df, meta.get("daftar_kode", KODE_AKSES_DEFAULT),
                       meta.get("semua_biller", ()))
    ws = wb.add_worksheet(_nama_sheet("REKAP_BILLER", dipakai))
    ws.write(0, 0, f"DAFTAR PAGAR TERKUNCI / METER TAK TERJANGKAU - REKENING {meta['blth']}", f_judul)
    ws.write(1, 0, f"Unit {meta.get('unit') or '-'}  |  Tgl baca terakhir: "
                   f"{meta.get('tgl_baca') or '-'}  |  Dicetak: "
                   f"{datetime.now().strftime('%d/%m/%Y %H:%M')}", f_sub)
    baris = 2
    for c in meta.get("catatan", []):
        ws.write(baris, 0, c, f_sub)
        baris += 1
    ws.write(baris, 0, "Satu pelanggan bisa terhitung di kolom STAND 1 dan kolom kode "
                       "sekaligus; TOTAL = jumlah pelanggan.", f_sub)
    h = baris + 2
    for j, k in enumerate(rek.columns):
        ws.write(h, j, k, f_head)
        ws.set_column(j, j, 8 if j else 5)
    ws.set_column(1, 1, 12)
    for i, r in enumerate(rek.itertuples(index=False), start=h + 1):
        total = r[1] == "TOTAL"
        for j, v in enumerate(r):
            fmt = f_total if total else f_sel
            if j == 1:
                ws.write_string(i, j, str(v), fmt)
            elif v == "":
                ws.write_blank(i, j, None, fmt)
            else:
                ws.write_number(i, j, int(v), fmt)
    ws.set_row(h, 45)
    ws.freeze_panes(h + 1, 2)
    ws.autofilter(h, 0, h + len(rek) - 1, len(rek.columns) - 1)

    def detail(nama, d):
        ws = wb.add_worksheet(_nama_sheet(nama, dipakai))
        for j, k in enumerate(KOLOM_DETAIL):
            ws.write(0, j, k, f_head)
            ws.set_column(j, j, _LEBAR.get(k, 12))
        ws.set_row(0, 30)
        d = d.reset_index(drop=True)
        j_riw = KOLOM_DETAIL.index("RIWAYAT")
        for i, r in enumerate(d[KOLOM_DETAIL].itertuples(index=False), start=1):
            for j, (k, v) in enumerate(zip(KOLOM_DETAIL, r)):
                if k == "NO":
                    ws.write_number(i, j, i, f_sel)
                elif j == j_riw:
                    ws.write_string(i, j, str(v), f_riw.get(v, f_sel))
                elif k in _KOLOM_TEKS:
                    ws.write_string(i, j, "" if pd.isna(v) else str(v), f_teks)
                elif isinstance(v, numbers.Number) and not isinstance(v, bool):
                    if pd.isna(v):
                        ws.write_blank(i, j, None, f_sel)
                    else:
                        ws.write_number(i, j, float(v), f_sel)
                else:
                    ws.write_string(i, j, "" if pd.isna(v) else str(v), f_sel)
        ws.freeze_panes(1, 2)
        ws.autofilter(0, 0, max(len(d), 1), len(KOLOM_DETAIL) - 1)

    detail("SEMUA", df)
    urut_biller = df["BILLER"].value_counts()
    urut_biller = sorted(urut_biller.index, key=lambda b: (-urut_biller[b], b))
    for b in urut_biller:
        detail(b, df[df["BILLER"] == b])
    kronis = df[df["KALI (TERMASUK BULAN INI)"] >= 3]
    kronis = kronis.sort_values("KALI (TERMASUK BULAN INI)", ascending=False, kind="stable")
    detail("KRONIS", kronis)

    wb.close()
    os.replace(tmp, path)
    return rek
