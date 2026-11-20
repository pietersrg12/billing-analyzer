import pandas as pd

# Nama STATUS sekaligus nama sheet Excel untuk pemakaian melewati batas jam
# nyala. Dipakai juga di core/excel.py (urutan RINGKASAN) - jangan diketik
# ulang sebagai literal supaya tidak lepas sinkron.
STATUS_JAM_TINGGI = ">720JN"

# Ditagih lagi setelah bulan lalu 0 kWh, tanpa dukungan stan ACMT. Lihat
# tandai_tagih_ulang_pasca_nol - rule ini jalan setelah ACMT ditempel.
STATUS_PASCA_NOL = "Tagih Ulang Pasca Nol"

# Rekening minimum: billing menagih minimal 40 jam nyala walau stand nyaris
# tidak bergerak, jadi selisih stand < pemakaian itu WAJAR. Dulu masuk "Stand
# Tidak Wajar" dan membanjirinya (662 dari 665 baris di 202611; user memilih
# BIARKAN untuk 637 dari 638 di 202610). Status sendiri, tanpa unduh foto.
STATUS_REKENING_MINIMUM = "Rekening Minimum"
JAM_REKENING_MINIMUM = 40

# =========================
# RULES
# =========================
# Setiap rule menerima (row, cfg) — cfg adalah dict rule settings (lihat
# core/settings.py DEFAULT_RULES untuk daftar & arti tiap key).

def rule_stand_minus(r, cfg):
    if r["STAND_KINI"] < r["STAND_LALU"]:
        return "Stand Minus",""
    return None

def rule_meter_macet(r, cfg):
    if r["PEMAKAIAN"] == 0 and r["RATA2"] > 0:
        return "Meter Macet",""
    return None

def rule_jam(r, cfg):
    # "Jam Tinggi" (>=720) dan "Jam Tidak Wajar" (>744) digabung 2026-08 atas
    # permintaan user - dua sheet terpisah tidak menambah nilai pemeriksaan,
    # keduanya sama-sama berarti pemakaian melewati batas fisik daya.
    if r["JAM_NYALA"] >= cfg["jam_nyala_tinggi_min"]:
        return STATUS_JAM_TINGGI,""
    return None

def rule_kenaikan(r, cfg):
    # NOTE: cabang kedua `max(..., RATA2 + kenaikan_tambahan)` dihapus 2026-08.
    # Dengan kenaikan_pemakaian_min = 150, cabang itu tidak pernah jadi
    # penentu: untuk RATA2 < 100 hasilnya selalu di bawah 150 (kalah oleh
    # batas pemakaian minimum), dan untuk RATA2 >= 100 selalu kalah oleh
    # batas persen. Diuji di data 202608: nilai 0 maupun 50 sama-sama
    # menghasilkan 319 baris Kenaikan.
    batas = (1 + cfg["kenaikan_persen_min"] / 100) * r["RATA2"]
    if r["PEMAKAIAN"] > cfg["kenaikan_pemakaian_min"] and r["PEMAKAIAN"] > batas:
        return "Kenaikan",""
    return None

def rule_penurunan(r, cfg):
    batas = (1 - cfg["penurunan_persen_min"] / 100) * r["RATA2"]
    if r["PEMAKAIAN"] > 0 and r["PEMAKAIAN"] < batas:
        return "Penurunan",""
    return None

def rule_trend_naik(r, cfg):
    if r["TREND_STATUS"] == "naik_konsisten":
        return "Trend Naik",""
    return None

def rule_stand_tidak_wajar(r, cfg):
    selisih = r["STAND_KINI"] - r["STAND_LALU"]
    if r["PEMAKAIAN"] > 0 and r["STAND_LALU"] > 0:
        if selisih != r["PEMAKAIAN"] and abs(selisih - r["PEMAKAIAN"]) > cfg["stand_tidak_wajar_toleransi"]:
            detail = f"Selisih={selisih:.0f}, Pakai={r['PEMAKAIAN']:.0f}"
            if r["JAM_NYALA"] <= JAM_REKENING_MINIMUM and 0 <= selisih < r["PEMAKAIAN"]:
                return STATUS_REKENING_MINIMUM, detail
            return "Stand Tidak Wajar", detail
    return None

# NOTE: rule "Anomali vs Sejawat" (peer median) dihapus 2026-07 atas
# permintaan user - tidak pernah menghasilkan temuan riil di lapangan.
# NOTE: rule "Perlu Perhatian" (pemakaian 1.2-1.5x RATA2) dihapus 2026-08 atas
# permintaan user - sheetnya nyaris tidak pernah diperiksa. Baris yang dulu
# masuk ke sana kini jatuh ke rule berikutnya, umumnya jadi "Normal" sehingga
# ikut hemat kuota download foto.
# NOTE: rule "Anomali Daya" (PEMAKAIAN > DAYA * 2) dihapus 2026-08 - tidak
# pernah tercapai. rule_jam berjalan lebih dulu dan sudah menangkap semua yang
# jam nyalanya >= 720; supaya rule ini sempat kena, pengalinya harus < 0.72.
# Terbukti di data 202608: 0 baris.
RULES = [
    rule_stand_minus,
    rule_stand_tidak_wajar,
    rule_meter_macet,
    rule_jam,
    rule_kenaikan,
    rule_trend_naik,
    rule_penurunan,
]

# =========================
# PROCESS
# =========================

def prepare(df, db, cfg):

    n_bulan = cfg["jumlah_bulan_rata2"]

    # Semua agregat di bawah per-IDPEL lalu di-merge kiri ke df, jadi baris DB
    # pelanggan lain tidak pernah terpakai. Disaring dulu supaya tidak ikut
    # dihitung (hasil identik, diuji assert_frame_equal pada 9.168 baris).
    db = db[db["IDPEL"].isin(df["IDPEL"])]

    db_sorted = db.sort_values(["IDPEL","BULAN"])
    last = db_sorted.groupby("IDPEL").tail(1)

    rata = (
        db_sorted.groupby("IDPEL")
        .tail(n_bulan)
        .groupby("IDPEL")["PEMAKAIAN"]
        .median()
        .reset_index()
    )

    df = df.merge(last[["IDPEL","STAND"]], on="IDPEL", how="left")
    df = df.merge(rata, on="IDPEL", how="left")

    df.rename(columns={
        "STAND":"STAND_LALU",
        "PEMAKAIAN_x":"PEMAKAIAN",
        "PEMAKAIAN_y":"RATA2"
    }, inplace=True)

    # --- Previous month usage (bulan lalu) ---
    # BULAN_DB_TERAKHIR ikut disimpan supaya rule pasca-nol bisa memastikan
    # "bulan lalu" memang blth-1, bukan bulan tua dari database yang tertinggal.
    prev = db_sorted.groupby("IDPEL")[["PEMAKAIAN", "BULAN"]].last().reset_index()
    prev = prev.rename(columns={"PEMAKAIAN": "PEMAKAIAN_BULAN_LALU",
                                "BULAN": "BULAN_DB_TERAKHIR"})
    df = df.merge(prev, on="IDPEL", how="left")
    df["PEMAKAIAN_BULAN_LALU"] = df["PEMAKAIAN_BULAN_LALU"].fillna(0).astype(int)

    # --- Sparkline: unicode text bar N bulan terakhir ---
    _sp_chars = "▁▂▃▄▅▆▇█"

    def _sparkline(vals):
        if not isinstance(vals, (list, pd.Series)) or len(vals) < 2:
            return ""
        mn, mx = min(vals), max(vals)
        if mx == mn:
            return _sp_chars[4] * len(vals)
        return "".join(_sp_chars[min(int((v - mn) / (mx - mn) * 7), 7)] for v in vals)

    # NOTE: window ini dipakai bareng untuk sparkline & trend analysis di
    # bawah (satu setting jumlah_bulan_rata2, disatukan dengan window RATA2).
    last6 = db_sorted.groupby("IDPEL").tail(n_bulan).sort_values(["IDPEL","BULAN"])
    spark_map = last6.groupby("IDPEL")["PEMAKAIAN"].apply(_sparkline)
    spark_df = spark_map.reset_index()
    spark_df.rename(columns={"PEMAKAIAN": "SPARKLINE"}, inplace=True)
    df = df.merge(spark_df, on="IDPEL", how="left")
    df["SPARKLINE"] = df["SPARKLINE"].fillna("")

    df["JAM_NYALA"] = df["PEMAKAIAN"] / (df["DAYA"]/1000)
    df["JAM_NYALA"] = df["JAM_NYALA"].replace([float("inf")], 0).round(0).astype(int)

    df["STAND_RATA2"] = (df["STAND_LALU"] + df["RATA2"]).round(0).astype("Int64")
    df["STAND_P1"] = (df["STAND_LALU"] + (cfg["stand_p1_jam_konstan"] * (df["DAYA"]/1000))).round(0).astype("Int64")
    df["STAND_RUMAH_KOSONG"] = df["STAND_LALU"].round(0).astype("Int64")

    mask = df["RATA2"] > 0
    df.loc[mask, "%PERUBAHAN"] = (((df.loc[mask, "PEMAKAIAN"] - df.loc[mask, "RATA2"]) / df.loc[mask, "RATA2"]) * 100).round(1)

    # --- Trend analysis (vectorized) ---
    df["TREND_STATUS"] = ""
    last6 = last6.copy()
    last6["PEM_SHIFT"] = last6.groupby("IDPEL")["PEMAKAIAN"].shift(1)
    last6["IS_UP"] = (last6["PEMAKAIAN"] > last6["PEM_SHIFT"]).astype(int)

    trend_agg = last6.groupby("IDPEL").agg(
        n=("PEMAKAIAN","size"),
        ups=("IS_UP","sum"),
        first_val=("PEMAKAIAN","first"),
        last_val=("PEMAKAIAN","last"),
    )

    trend_mask = (
        (trend_agg["n"] >= cfg["trend_min_bulan"]) &
        (trend_agg["ups"] >= trend_agg["n"] - 1) &
        (trend_agg["last_val"] > trend_agg["first_val"] * (1 + cfg["trend_persen_min"] / 100))
    )
    trend_idpels = trend_agg[trend_mask].index.tolist()

    if trend_idpels:
        df.loc[df["IDPEL"].isin(trend_idpels), "TREND_STATUS"] = "naik_konsisten"

    return df


def run_analysis(row, cfg):

    if pd.isna(row["STAND_LALU"]):
        return "DATA BARU",""

    for rule in RULES:
        res = rule(row, cfg)
        if res:
            return res

    return "Normal",""


def apply_analysis(df, cfg):
    df[["STATUS","DETAIL"]] = df.apply(lambda x: pd.Series(run_analysis(x, cfg)), axis=1)
    return df


# Status yang keputusannya bersandar pada RATA2 - boleh ditimpa rule pasca
# nol, karena RATA2 justru tercemar bulan estimasi. Status berbasis stand
# (Stand Minus, Stand Tidak Wajar, Meter Macet, >720JN) tetap menang.
STATUS_BOLEH_PASCA_NOL = ("Normal", "Kenaikan", "Penurunan", "Trend Naik")


def tandai_tagih_ulang_pasca_nol(df, blth, cfg):
    """Tandai baris yang ditagih lagi setelah bulan lalu dinolkan, padahal
    stand tagihannya tidak didukung bacaan ACMT bulan ini.

    Pola (IDPEL 443200000806, 202610): ACMT terbaca 1 sejak Juli, 202608
    ditagih estimasi, 202609 dinolkan (lebih tagih), 202610 ditagih rata2 lagi
    - lebih tagihnya terulang. RATA2 sudah tercemar bulan estimasi, jadi rule
    lain melihatnya Normal.

    Harus dipanggil SETELAH STAN_METER_ACMT ditempel (pipeline._tempel_kd_baca),
    makanya tidak masuk RULES. Tanpa ACMT -> df apa adanya (billing tidak
    dipakai sebagai cadangan). Return (df, jumlah_ditandai).
    """
    if "STAN_METER_ACMT" not in df.columns:
        return df, 0

    bulan_lalu = int((pd.Period(str(blth), freq="M") - 1).strftime("%Y%m"))
    acmt = pd.to_numeric(df["STAN_METER_ACMT"], errors="coerce")
    tol = cfg["pasca_nol_toleransi_acmt"]

    mask = (
        (df["BULAN_DB_TERAKHIR"] == bulan_lalu)
        & (df["PEMAKAIAN_BULAN_LALU"] == 0)
        & (df["STAND_KINI"] > df["STAND_LALU"])
        & acmt.notna()
        & ((acmt <= 1) | (df["STAND_KINI"] - acmt > tol))
        & df["STATUS"].isin(STATUS_BOLEH_PASCA_NOL)
    )
    if not mask.any():
        return df, 0

    df = df.copy()
    df.loc[mask, "STATUS"] = STATUS_PASCA_NOL
    df.loc[mask, "DETAIL"] = df.loc[mask].apply(
        lambda r: (f"Bln lalu 0 kWh, kini {r['PEMAKAIAN']:.0f} | "
                   f"stand {r['STAND_KINI']:.0f} vs ACMT {r['STAN_METER_ACMT']:.0f}"),
        axis=1,
    )
    return df, int(mask.sum())


def compute_stanbaca_comparison(df, stanbaca_db, blth, cfg):
    """Bandingkan pemakaian rekening vs pemakaian asli dari stan baca meter.

    Menambah kolom STAND_BACA_LALU, PEMAKAIAN_ASLI, SELISIH_STAN_BACA ke df
    (informasi tambahan, tidak mempengaruhi STATUS).

    PEMAKAIAN_ASLI = STAND_KINI (stan akhir yang ditagihkan di DPM blth ini)
    dikurangi STAND_BACA_LALU (bacaan fisik terakhir yang tersedia di
    database stan baca). Bacaan fisik untuk blth itu sendiri (STAND_BACA_KINI)
    tidak dipakai karena secara siklus baca PLN nyaris tidak pernah tersedia
    saat blth baru diproses - bacaan fisik blth baru masuk database stan baca
    sebagai data blth+1.

    STAND_BACA_LALU diambil HANYA dari BULAN = blth-1. Kalau bulan itu tidak
    ada untuk IDPEL tsb hasilnya NaN - jangan pernah jatuh ke bulan yang lebih
    tua: PEMAKAIAN_ASLI lalu mencakup dua bulan dan SELISIH_STAN_BACA tampak
    seperti temuan, padahal databasenya saja yang belum di-update (2026-09:
    blth 202610 diam-diam memakai baca Juli).
    """
    if stanbaca_db is None or stanbaca_db.empty:
        return df

    bulan_lalu = int((pd.Period(str(blth), freq="M") - 1).strftime("%Y%m"))

    sb_sorted = stanbaca_db.sort_values(["IDPEL", "BULAN"])
    lalu = sb_sorted[sb_sorted["BULAN"] == bulan_lalu].groupby("IDPEL").tail(1)[["IDPEL", "STAND"]]
    lalu = lalu.rename(columns={"STAND": "STAND_BACA_LALU"})

    df = df.merge(lalu, on="IDPEL", how="left")

    df["PEMAKAIAN_ASLI"] = df["STAND_KINI"] - df["STAND_BACA_LALU"]
    df["SELISIH_STAN_BACA"] = df["PEMAKAIAN_ASLI"] - df["PEMAKAIAN"]

    return df
