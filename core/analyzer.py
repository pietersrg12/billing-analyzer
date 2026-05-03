import pandas as pd

# =========================
# RULES
# =========================

def rule_stand_minus(r):
    if r["STAND_KINI"] < r["STAND_LALU"]:
        return "Stand Minus",""
    return None

def rule_meter_macet(r):
    if r["PEMAKAIAN"] == 0 and r["RATA2"] > 0:
        return "Meter Macet",""
    return None

def rule_jam(r):
    if r["JAM_NYALA"] > 744:
        return "Jam Tidak Wajar",""
    if r["JAM_NYALA"] >= 720:
        return "Jam Tinggi",""
    return None

def rule_kenaikan(r):
    if r["PEMAKAIAN"] > 150 and r["PEMAKAIAN"] > max(1.5*r["RATA2"], r["RATA2"]+50):
        return "Kenaikan",""
    return None

def rule_perlu_perhatian(r):
    if r["RATA2"] > 0 and r["PEMAKAIAN"] > 0:
        ratio = r["PEMAKAIAN"] / r["RATA2"]
        if 1.2 <= ratio < 1.5 and r["PEMAKAIAN"] > 100:
            return "Perlu Perhatian",""
    return None

def rule_penurunan(r):
    if r["PEMAKAIAN"] > 0 and r["PEMAKAIAN"] < 0.5*r["RATA2"]:
        return "Penurunan",""
    return None

def rule_anomali(r):
    if r["PEMAKAIAN"] > r["DAYA"]*2:
        return "Anomali Daya",""
    return None

def rule_trend_naik(r):
    if r["TREND_STATUS"] == "naik_konsisten":
        return "Trend Naik",""
    return None

def rule_peer_anomali(r):
    if r["RATA2"] > 0 and r["PEER_MEDIAN"] > 0:
        ratio = r["PEMAKAIAN"] / r["PEER_MEDIAN"]
        if ratio > 3:
            return "Anomali vs Sejawat",""
    return None

def rule_stand_tidak_wajar(r):
    selisih = r["STAND_KINI"] - r["STAND_LALU"]
    if r["PEMAKAIAN"] > 0 and r["STAND_LALU"] > 0:
        if selisih != r["PEMAKAIAN"] and abs(selisih - r["PEMAKAIAN"]) > 1:
            return "Stand Tidak Wajar",f"Selisih={selisih:.0f}, Pakai={r['PEMAKAIAN']:.0f}"
    return None

RULES = [
    rule_stand_minus,
    rule_stand_tidak_wajar,
    rule_meter_macet,
    rule_jam,
    rule_kenaikan,
    rule_perlu_perhatian,
    rule_trend_naik,
    rule_peer_anomali,
    rule_penurunan,
    rule_anomali
]

# =========================
# PROCESS
# =========================

def prepare(df, db):

    db_sorted = db.sort_values(["IDPEL","BULAN"])
    last = db_sorted.groupby("IDPEL").tail(1)

    rata = (
        db_sorted.groupby("IDPEL")
        .tail(6)
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
    # SESUDAH (benar)
    prev = db_sorted.groupby("IDPEL")["PEMAKAIAN"].last().reset_index()
    prev.rename(columns={"PEMAKAIAN": "PEMAKAIAN_BULAN_LALU"}, inplace=True)
    df = df.merge(prev, on="IDPEL", how="left")
    df["PEMAKAIAN_BULAN_LALU"] = df["PEMAKAIAN_BULAN_LALU"].fillna(0).astype(int)

    # --- Sparkline: unicode text bar 6 bulan terakhir ---
    _sp_chars = "▁▂▃▄▅▆▇█"

    def _sparkline(vals):
        if not isinstance(vals, (list, pd.Series)) or len(vals) < 2:
            return ""
        mn, mx = min(vals), max(vals)
        if mx == mn:
            return _sp_chars[4] * len(vals)
        return "".join(_sp_chars[min(int((v - mn) / (mx - mn) * 7), 7)] for v in vals)

    last6 = db_sorted.groupby("IDPEL").tail(6).sort_values(["IDPEL","BULAN"])
    spark_map = last6.groupby("IDPEL")["PEMAKAIAN"].apply(_sparkline)
    spark_df = spark_map.reset_index()
    spark_df.rename(columns={"PEMAKAIAN": "SPARKLINE"}, inplace=True)
    df = df.merge(spark_df, on="IDPEL", how="left")
    df["SPARKLINE"] = df["SPARKLINE"].fillna("")

    df["JAM_NYALA"] = df["PEMAKAIAN"] / (df["DAYA"]/1000)
    df["JAM_NYALA"] = df["JAM_NYALA"].replace([float("inf")], 0).round(0).astype(int)

    df["STAND_RATA2"] = (df["STAND_LALU"] + df["RATA2"]).round(0).astype("Int64")
    df["STAND_P1"] = (df["STAND_LALU"] + (718 * (df["DAYA"]/1000))).round(0).astype("Int64")
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
        (trend_agg["n"] >= 3) &
        (trend_agg["ups"] >= trend_agg["n"] - 1) &
        (trend_agg["last_val"] > trend_agg["first_val"] * 1.3)
    )
    trend_idpels = trend_agg[trend_mask].index.tolist()

    if trend_idpels:
        df.loc[df["IDPEL"].isin(trend_idpels), "TREND_STATUS"] = "naik_konsisten"

    # --- Peer comparison ---
    df["PEER_MEDIAN"] = 0
    if "TARIF" in df.columns and df["TARIF"].notna().any():
        peer = df.groupby(["DAYA","TARIF"])["PEMAKAIAN"].transform("median")
        df["PEER_MEDIAN"] = peer.fillna(0)

    return df


def run_analysis(row):

    if pd.isna(row["STAND_LALU"]):
        return "DATA BARU",""

    for rule in RULES:
        res = rule(row)
        if res:
            return res

    return "Normal",""


def apply_analysis(df):
    df[["STATUS","DETAIL"]] = df.apply(lambda x: pd.Series(run_analysis(x)), axis=1)
    return df
