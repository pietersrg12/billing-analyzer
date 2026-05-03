import pandas as pd

def detect_mode(columns):

    cols = set(columns)

    if {"SAHLWBP","LWBPPAKAI"}.issubset(cols):
        return "resmi"

    if {"STAN_METER","PEMKWH","KDBACA"}.issubset(cols):
        return "belum"

    raise ValueError("Format DPM tidak dikenali")


def load_data(dpm_path, db_path):

    dpm = pd.read_excel(dpm_path)
    db  = pd.read_excel(db_path)

    # =========================
    # AUTO DETECT
    # =========================
    mode = detect_mode(dpm.columns)
    print(f"MODE TERDETEKSI: {mode.upper()}")

    # =========================
    # MAPPING
    # =========================
    if mode == "resmi":

        dpm = dpm.rename(columns={
            "IDPEL": "IDPEL",
            "SAHLWBP": "STAND_KINI",
            "LWBPPAKAI": "PEMAKAIAN",
            "DAYA": "DAYA",
            "TARIF": "TARIF",
            "KELAINAN_BC_METER": "KELAINAN"
        })

    elif mode == "belum":

        dpm = dpm.rename(columns={
            "IDPEL": "IDPEL",
            "STAN_METER": "STAND_KINI",
            "PEMKWH": "PEMAKAIAN",
            "DAYA": "DAYA",
            "TARIF": "TARIF",
            "KDBACA": "KELAINAN"
        })

        kode_map = {
            "A": "KWH METER MACET",
            "B": "KWH METER MUNDUR",
            "C": "KWH METER TIDAK ADA",
            "D": "PELANGGAN TIDAK SESUAI RBM",
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
            "7": "STAN DARI PELANGGAN"
        }

        dpm["KELAINAN"] = dpm["KELAINAN"].map(kode_map).fillna("")

    # =========================
    # CLEANING
    # =========================

    dpm["IDPEL"] = dpm["IDPEL"].astype(str)

    for col in ["STAND_KINI","PEMAKAIAN","DAYA"]:
        dpm[col] = pd.to_numeric(dpm[col], errors="coerce").fillna(0)

    db["IDPEL"] = db["IDPEL"].astype(str)
    db["BULAN"] = db["BULAN"].astype(int)

    return dpm, db, mode