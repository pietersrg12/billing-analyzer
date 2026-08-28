import pandas as pd

# Nama STATUS sekaligus nama sheet Excel untuk pemakaian melewati batas jam
# nyala. Dipakai juga di core/excel.py (urutan RINGKASAN) - jangan diketik
# ulang sebagai literal supaya tidak lepas sinkron.
STATUS_JAM_TINGGI = ">720JN"

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
            return "Stand Tidak Wajar",f"Selisih={selisih:.0f}, Pakai={r['PEMAKAIAN']:.0f}"
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
    prev = db_sorted.groupby("IDPEL")["PEMAKAIAN"].last().reset_index()
    prev.rename(columns={"PEMAKAIAN": "PEMAKAIAN_BULAN_LALU"}, inplace=True)
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


def compute_stanbaca_comparison(df, stanbaca_db, blth, cfg):
    """Bandingkan pemakaian rekening vs pemakaian asli dari stan baca meter.

    Menambah kolom STAND_BACA_LALU, PEMAKAIAN_ASLI, SELISIH_STAN_BACA ke df
    (informasi tambahan, tidak mempengaruhi STATUS).

    PEMAKAIAN_ASLI = STAND_KINI (stan akhir yang ditagihkan di DPM blth ini)
    dikurangi STAND_BACA_LALU (bacaan fisik terakhir yang tersedia di
    database stan baca). Bacaan fisik untuk blth itu sendiri (STAND_BACA_KINI)
    tidak dipakai karena secara siklus baca PLN nyaris tidak pernah tersedia
    saat blth baru diproses - bacaan fisik blth baru masuk database stan baca
    sebagai data blth+1. NaN kalau STAND_BACA_LALU belum ada sama sekali
    untuk IDPEL tsb.
    """
    if stanbaca_db is None or stanbaca_db.empty:
        return df

    sb_sorted = stanbaca_db.sort_values(["IDPEL", "BULAN"])
    blth_int = int(blth)

    lalu = sb_sorted[sb_sorted["BULAN"] < blth_int].groupby("IDPEL").tail(1)[["IDPEL", "STAND"]]
    lalu = lalu.rename(columns={"STAND": "STAND_BACA_LALU"})

    df = df.merge(lalu, on="IDPEL", how="left")

    df["PEMAKAIAN_ASLI"] = df["STAND_KINI"] - df["STAND_BACA_LALU"]
    df["SELISIH_STAN_BACA"] = df["PEMAKAIAN_ASLI"] - df["PEMAKAIAN"]

    return df
