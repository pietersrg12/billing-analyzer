import pandas as pd
from openpyxl import load_workbook
from openpyxl.drawing.image import Image
from openpyxl.styles import PatternFill, Font, Border, Side, Alignment
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from core.koreksi import (
    ALASAN_MAP,
    PILIHAN_BELUM_PDL,
    PILIHAN_CAP720,
    PILIHAN_MANUAL,
    PILIHAN_OPTIONS,
    PILIHAN_RATA2,
    PILIHAN_RUMAH_KOSONG,
    PILIHAN_SALAH_ENTRY,
    PILIHAN_SALAH_PDL,
)


def warna_perubahan(val):
    if val is None:
        return None
    try:
        v = float(val)
    except (TypeError, ValueError):
        return None
    if v > 0:
        if v > 200: return PatternFill(start_color="006100", fill_type="solid")
        if v > 100: return PatternFill(start_color="548235", fill_type="solid")
        if v > 50:  return PatternFill(start_color="92D050", fill_type="solid")
        return PatternFill(start_color="C6EFCE", fill_type="solid")
    else:
        v = abs(v)
        if v > 70: return PatternFill(start_color="9C0006", fill_type="solid")
        if v > 50: return PatternFill(start_color="C00000", fill_type="solid")
        if v > 30: return PatternFill(start_color="FF6666", fill_type="solid")
        return PatternFill(start_color="FFC7CE", fill_type="solid")


def font_perubahan(val):
    if val is None:
        return None
    try:
        v = float(val)
    except (TypeError, ValueError):
        return None
    if abs(v) > 100:
        return Font(bold=True, color="FFFFFF")
    if abs(v) > 50:
        return Font(bold=True)
    return None


# Urutan prioritas kemunculan di sheet INDIKASI_STAN_BACA (paling mendesak duluan)
INDIKASI_PRIORITAS = [
    "Kemungkinan Meter Macet",
    "Stan Baca Tidak Pernah Dibaca",
    "Riwayat Sering Kena Batas Jam Nyala",
    "Kemungkinan Rumah Kosong",
]


# Blok kolom untuk pewarnaan visual (header + tint data), supaya pemeriksa
# langsung tahu sumber datanya: rekening billing vs baca meter fisik.
BLOK_REKENING = ("STAND_LALU", "STAND_KINI", "PEMAKAIAN_BULAN_LALU", "PEMAKAIAN")
BLOK_STAN_BACA = ("STAND_BACA_LALU", "PEMAKAIAN_ASLI", "SELISIH_STAN_BACA", "INDIKASI_STAN_BACA")
BLOK_RATA2 = ("RATA2",)


def _build_sheet_data(source, bulan_list, include_status=False, include_koreksi=False):
    """Susun kolom output untuk satu sheet.

    Urutan: identitas -> blok stan rekening -> blok stan baca -> pola/kelainan
    -> (STATUS utk sheet campuran) -> foto -> proyeksi stand.
    DETAIL digabung ke KELAINAN. STATUS hanya diikutkan untuk sheet campuran
    (PRIORITAS_KELAINAN, BUKAN_KWH) - di sheet per-status sudah tercermin
    dari nama sheet. KETERANGAN_STAN_BACA tidak diekspor (label INDIKASI cukup).
    """
    data_out = source[[
        "IDPEL", "TARIF", "DAYA",
        "STAND_LALU", "STAND_KINI", "PEMAKAIAN_BULAN_LALU", "PEMAKAIAN",
    ]].copy()

    for col in BLOK_STAN_BACA:
        if col in source.columns:
            data_out[col] = source[col]

    data_out["RATA2"] = source["RATA2"]

    data_out["SPARKLINE"] = source["SPARKLINE"]
    data_out["JAM_NYALA"] = source["JAM_NYALA"]
    data_out["%PERUBAHAN"] = source["%PERUBAHAN"]

    # Gabung DETAIL ke KELAINAN
    kelainan = source["KELAINAN"].fillna("").astype(str).str.strip()
    if "DETAIL" in source.columns:
        detail = source["DETAIL"].fillna("").astype(str).str.strip()
        kelainan = kelainan.where(detail == "", (kelainan + " | " + detail).str.strip(" |"))
    data_out["KELAINAN"] = kelainan

    if include_status:
        data_out["STATUS"] = source["STATUS"]

    # FOTO
    for b in bulan_list:
        data_out[b] = ""

    # Proyeksi stand paling akhir
    data_out["STAND_RATA2"] = source["STAND_RATA2"]
    data_out["STAND_P1"] = source["STAND_P1"]
    data_out["STAND_RUMAH_KOSONG"] = source["STAND_RUMAH_KOSONG"]

    # Kolom koreksi (dropdown di Excel): PILIHAN pre-filled saran otomatis,
    # KWH_MANUAL diisi user hanya jika PILIHAN = MANUAL (ditambah ke
    # STAND_LALU). STAN_MANUAL diisi user kalau PILIHAN = SALAH ENTRY (stand
    # baru langsung, wajib) atau SALAH PDL/BELUM PDL (opsional, fallback
    # STAND_RATA2 kalau kosong).
    if include_koreksi and "PILIHAN" in source.columns:
        data_out["PILIHAN"] = source["PILIHAN"]
        data_out["KWH_MANUAL"] = ""
        data_out["STAN_MANUAL"] = ""

    return data_out


def export_excel(df, output_file, bulan_list, klasifikasi=None, ocr_results=None):

    writer = pd.ExcelWriter(output_file, engine="openpyxl")
    sheet_map = {}
    koreksi_rows = []   # meta per baris untuk sheet KOREKSI_STAND

    for status, data in df.groupby("STATUS"):

        # Sort berdasarkan tipe status
        if status == "Kenaikan":
            data = data.sort_values(by="%PERUBAHAN", ascending=False)
        elif status == "Penurunan":
            data = data.sort_values(by="%PERUBAHAN", ascending=True)
        else:
            data = data.sort_values(by="JAM_NYALA", ascending=False)

        include_koreksi = (
            status not in ("Normal", "DATA BARU") and "PILIHAN" in data.columns
        )
        data_out = _build_sheet_data(data, bulan_list, include_koreksi=include_koreksi)

        sheet_name = status[:30]
        data_out.to_excel(writer, sheet_name=sheet_name, index=False)

        sheet_map[sheet_name] = data_out

        if include_koreksi:
            ws = writer.sheets[sheet_name]
            pil_letter = get_column_letter(data_out.columns.get_loc("PILIHAN") + 1)
            kwh_letter = get_column_letter(data_out.columns.get_loc("KWH_MANUAL") + 1)
            stanm_letter = get_column_letter(data_out.columns.get_loc("STAN_MANUAL") + 1)

            dv = DataValidation(
                type="list",
                formula1='"' + ",".join(PILIHAN_OPTIONS) + '"',
                allow_blank=True,
                showDropDown=False,
            )
            ws.add_data_validation(dv)
            dv.add(f"{pil_letter}2:{pil_letter}{len(data_out) + 1}")

            for i, (_, r) in enumerate(data_out.iterrows()):
                koreksi_rows.append({
                    "IDPEL": r["IDPEL"], "STATUS": status,
                    "STAND_LALU": r["STAND_LALU"], "STAND_KINI": r["STAND_KINI"],
                    "JAM_NYALA": r["JAM_NYALA"],
                    "STAND_RATA2": r["STAND_RATA2"], "STAND_P1": r["STAND_P1"],
                    "STAND_RUMAH_KOSONG": r["STAND_RUMAH_KOSONG"],
                    "_sheet": sheet_name, "_row": i + 2,
                    "_pil": pil_letter, "_kwh": kwh_letter, "_stanm": stanm_letter,
                })

    # =========================
    # SHEET PRIORITAS KELAINAN
    # =========================
    kel_filter = [
        "ANJING GALAK","STAN DARI PELANGGAN","KWH METER TIDAK ADA",
        "RUMAH KOSONG","PEMADAMAN","BENCANA","KWH METER MACET",
        "KWH METER BURAM/PECAH","KWH METER DIDALAM BANGUNAN",
        "KWH METER TINGGI"
    ]

    df_kel = df[df["KELAINAN"].isin(kel_filter)]

    if not df_kel.empty:

        df_kel = df_kel.sort_values(by="JAM_NYALA", ascending=False)

        data_out = _build_sheet_data(df_kel, bulan_list, include_status=True)

        data_out.to_excel(writer, sheet_name="PRIORITAS_KELAINAN", index=False)
        sheet_map["PRIORITAS_KELAINAN"] = data_out

    # =========================
    # SHEET BUKAN_KWH (klasifikasi YOLO)
    # =========================
    if klasifikasi:
        df_bk = df.copy()
        df_bk["IDPEL"] = df_bk["IDPEL"].astype(str)
        df_bk["KLASIFIKASI"] = df_bk["IDPEL"].map(klasifikasi).fillna("unknown")

        df_bukan = df_bk[
            (df_bk["STATUS"] != "Normal")
            & (df_bk["KLASIFIKASI"] == "bukan_kwh")
        ]

        if not df_bukan.empty:
            df_bukan = df_bukan.sort_values(by="JAM_NYALA", ascending=False)

            data_out = _build_sheet_data(df_bukan, bulan_list, include_status=True)

            data_out.to_excel(writer, sheet_name="BUKAN_KWH", index=False)
            sheet_map["BUKAN_KWH"] = data_out

    # =========================
    # SHEET KOREKSI_STAND (siap upload)
    # =========================
    # PILIHAN & KWH_MANUAL berupa formula referensi ke dropdown di sheet
    # status masing-masing, jadi begitu user mengubah pilihan di sana,
    # STAN BARU + ALASAN KOREKSI di sini ikut berubah otomatis.
    if koreksi_rows:
        df_kor = pd.DataFrame([{
            "IDPEL": m["IDPEL"], "STATUS": m["STATUS"],
            "STAND_LALU": m["STAND_LALU"], "STAND_KINI": m["STAND_KINI"],
            "JAM_NYALA": m["JAM_NYALA"],
            "PILIHAN": "", "KWH_MANUAL": "", "STAN_MANUAL": "",
            "STAND_RATA2": m["STAND_RATA2"], "STAND_P1": m["STAND_P1"],
            "STAND_RUMAH_KOSONG": m["STAND_RUMAH_KOSONG"],
            "STAN BARU": "", "ALASAN KOREKSI": "",
        } for m in koreksi_rows])

        df_kor.to_excel(writer, sheet_name="KOREKSI_STAND", index=False)
        ws_kor = writer.sheets["KOREKSI_STAND"]

        # Kolom (1-based): A IDPEL, B STATUS, C STAND_LALU, D STAND_KINI,
        # E JAM_NYALA, F PILIHAN, G KWH_MANUAL, H STAN_MANUAL, I STAND_RATA2,
        # J STAND_P1, K STAND_RUMAH_KOSONG, L STAN BARU, M ALASAN KOREKSI
        for i, m in enumerate(koreksi_rows):
            r = i + 2
            sn = m["_sheet"].replace("'", "''")
            ws_kor.cell(row=r, column=6).value = f"='{sn}'!{m['_pil']}{m['_row']}"
            ws_kor.cell(row=r, column=7).value = (
                f"=IF('{sn}'!{m['_kwh']}{m['_row']}=\"\",\"\",'{sn}'!{m['_kwh']}{m['_row']})"
            )
            ws_kor.cell(row=r, column=8).value = (
                f"=IF('{sn}'!{m['_stanm']}{m['_row']}=\"\",\"\",'{sn}'!{m['_stanm']}{m['_row']})"
            )
            # STAN BARU: RATA2/CAP-720/RUMAH KOSONG pakai kolom proyeksi;
            # MANUAL = STAND_LALU + KWH_MANUAL; SALAH ENTRY = STAN_MANUAL
            # langsung (wajib diisi, tidak ada fallback); SALAH PDL/BELUM PDL
            # = STAN_MANUAL kalau diisi, else fallback STAND_RATA2.
            ws_kor.cell(row=r, column=12).value = (
                f'=IF(F{r}="{PILIHAN_RATA2}",I{r},'
                f'IF(F{r}="{PILIHAN_CAP720}",J{r},'
                f'IF(F{r}="{PILIHAN_RUMAH_KOSONG}",K{r},'
                f'IF(F{r}="{PILIHAN_MANUAL}",C{r}+N(G{r}),'
                f'IF(F{r}="{PILIHAN_SALAH_ENTRY}",IF(H{r}="","",H{r}),'
                f'IF(OR(F{r}="{PILIHAN_SALAH_PDL}",F{r}="{PILIHAN_BELUM_PDL}"),'
                f'IF(H{r}="",I{r},H{r}),""))))))'
            )
            ws_kor.cell(row=r, column=13).value = (
                f'=IF(F{r}="{PILIHAN_RATA2}","{ALASAN_MAP[PILIHAN_RATA2]}",'
                f'IF(F{r}="{PILIHAN_CAP720}","{ALASAN_MAP[PILIHAN_CAP720]}",'
                f'IF(F{r}="{PILIHAN_RUMAH_KOSONG}","{ALASAN_MAP[PILIHAN_RUMAH_KOSONG]}",'
                f'IF(F{r}="{PILIHAN_MANUAL}","{ALASAN_MAP[PILIHAN_MANUAL]}",'
                f'IF(F{r}="{PILIHAN_SALAH_ENTRY}","{ALASAN_MAP[PILIHAN_SALAH_ENTRY]}",'
                f'IF(F{r}="{PILIHAN_SALAH_PDL}","{ALASAN_MAP[PILIHAN_SALAH_PDL]}",'
                f'IF(F{r}="{PILIHAN_BELUM_PDL}","{ALASAN_MAP[PILIHAN_BELUM_PDL]}","")))))))'
            )

        sheet_map["KOREKSI_STAND"] = df_kor

    # =========================
    # SHEET RINGKASAN
    # =========================
    summary_data = []

    status_counts = df["STATUS"].value_counts()
    total = len(df)
    summary_data.append(["Total Dianalisis", total])
    summary_data.append([""])
    summary_data.append(["STATUS", "JUMLAH", "%"])
    for status_name in ["Normal","Stand Minus","Meter Macet","Kenaikan","Perlu Perhatian",
                        "Penurunan","Jam Tinggi","Jam Tidak Wajar","Anomali Daya",
                        "Trend Naik","Stand Tidak Wajar","DATA BARU"]:
        cnt = status_counts.get(status_name, 0)
        pct = round(cnt / total * 100, 1) if total > 0 else 0
        summary_data.append([status_name, cnt, pct])

    # Klasifikasi summary
    if klasifikasi:
        n_kwh = sum(1 for v in klasifikasi.values() if v == "kwh_meter")
        n_bukan = sum(1 for v in klasifikasi.values() if v == "bukan_kwh")
        n_unknown = sum(1 for v in klasifikasi.values()
                        if v not in ("kwh_meter", "bukan_kwh"))
        n_total_klasif = len(klasifikasi)

        summary_data.append([""])
        summary_data.append(["KLASIFIKASI FOTO (BULAN TERBARU)"])
        summary_data.append(["LABEL", "JUMLAH", "%"])
        for label, count in [
            ("KWH Meter", n_kwh),
            ("Bukan KWH", n_bukan),
            ("Unknown / Error", n_unknown),
        ]:
            pct = round(count / n_total_klasif * 100, 1) if n_total_klasif > 0 else 0
            summary_data.append([label, count, pct])

    if "INDIKASI_STAN_BACA" in df.columns:
        ind_counts = df[df["INDIKASI_STAN_BACA"] != ""]["INDIKASI_STAN_BACA"].value_counts()
        if not ind_counts.empty:
            summary_data.append([""])
            summary_data.append(["INDIKASI STAN BACA (kolom INDIKASI di tiap sheet)"])
            summary_data.append(["INDIKASI", "JUMLAH"])
            for label in INDIKASI_PRIORITAS:
                cnt = ind_counts.get(label, 0)
                if cnt:
                    summary_data.append([label, cnt])

    summary_data.append([""])
    summary_data.append(["Top 10 Jam Nyala Tertinggi:"])
    summary_data.append(["IDPEL","TARIF","DAYA","PEMAKAIAN","RATA2","JAM_NYALA","STATUS"])
    top10 = df.nlargest(10, "JAM_NYALA")
    for _, row in top10.iterrows():
        summary_data.append([
            row["IDPEL"], row["TARIF"], row["DAYA"],
            row["PEMAKAIAN"], row.get("RATA2",""), row["JAM_NYALA"], row["STATUS"]
        ])

    summary_data.append([""])
    summary_data.append(["Top 10 Kenaikan Tertinggi:"])
    summary_data.append(["IDPEL","TARIF","DAYA","PEMAKAIAN","RATA2","%PERUBAHAN","STATUS"])
    top_knk = df[df["%PERUBAHAN"].fillna(0) > 0].nlargest(10, "%PERUBAHAN")
    for _, row in top_knk.iterrows():
        summary_data.append([
            row["IDPEL"], row["TARIF"], row["DAYA"],
            row["PEMAKAIAN"], row.get("RATA2",""), row.get("%PERUBAHAN",""), row["STATUS"]
        ])

    summary_data.append([""])
    summary_data.append(["Top 10 Penurunan Tertinggi:"])
    summary_data.append(["IDPEL","TARIF","DAYA","PEMAKAIAN","RATA2","%PERUBAHAN","STATUS"])
    top_pnr = df[df["%PERUBAHAN"].fillna(0) < 0].nsmallest(10, "%PERUBAHAN")
    for _, row in top_pnr.iterrows():
        summary_data.append([
            row["IDPEL"], row["TARIF"], row["DAYA"],
            row["PEMAKAIAN"], row.get("RATA2",""), row.get("%PERUBAHAN",""), row["STATUS"]
        ])

    summary_df = pd.DataFrame(summary_data)
    summary_df.to_excel(writer, sheet_name="RINGKASAN", index=False, header=False)
    sheet_map["RINGKASAN"] = summary_df

    writer.close()
    return sheet_map


def format_excel(output_file, sheet_map, results, bulan_list, ocr_results=None, cfg=None):
    stan_baca_toleransi = (cfg or {}).get("stand_tidak_wajar_toleransi", 1)

    thin = Side(border_style="thin", color="000000")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    header_fill = PatternFill(start_color="4F81BD", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")

    center = Alignment(horizontal="center", vertical="center")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

    warna_status = {
        "Stand Minus": PatternFill(start_color="FF9999", fill_type="solid"),
        "Meter Macet": PatternFill(start_color="FFCC99", fill_type="solid"),
        "Kenaikan": PatternFill(start_color="99CCFF", fill_type="solid"),
        "Penurunan": PatternFill(start_color="CCCCFF", fill_type="solid"),
    }

    warna_indikasi = {
        "Kemungkinan Meter Macet": PatternFill(start_color="FFC7CE", fill_type="solid"),
        "Stan Baca Tidak Pernah Dibaca": PatternFill(start_color="E4DFEC", fill_type="solid"),
        "Kemungkinan Rumah Kosong": PatternFill(start_color="FFEB9C", fill_type="solid"),
        "Riwayat Sering Kena Batas Jam Nyala": PatternFill(start_color="BDD7EE", fill_type="solid"),
    }

    # Blok kolom berwarna: header lebih gelap + tint tipis di data,
    # supaya pemeriksa langsung tahu sumber data tiap kolom.
    blok_style = {
        "rekening": {
            "cols": BLOK_REKENING,
            "header": PatternFill(start_color="305496", fill_type="solid"),
            "tint": PatternFill(start_color="DCE6F1", fill_type="solid"),
        },
        "stanbaca": {
            "cols": BLOK_STAN_BACA,
            "header": PatternFill(start_color="548235", fill_type="solid"),
            "tint": PatternFill(start_color="E2EFDA", fill_type="solid"),
        },
        "rata2": {
            "cols": BLOK_RATA2,
            "header": PatternFill(start_color="7030A0", fill_type="solid"),
            "tint": PatternFill(start_color="E5DFF3", fill_type="solid"),
        },
        # Kuning = sel yang boleh diisi/diubah user (dropdown & kWh manual).
        # Tidak dipakai di KOREKSI_STAND (di sana isinya formula, bukan input).
        "koreksi": {
            "cols": ("PILIHAN", "KWH_MANUAL", "STAN_MANUAL"),
            "header": PatternFill(start_color="BF8F00", fill_type="solid"),
            "tint": PatternFill(start_color="FFF2CC", fill_type="solid"),
        },
    }

    wb = load_workbook(output_file)

    for sheet_name, data in sheet_map.items():

        ws = wb[sheet_name]
        # Freeze header + kolom IDPEL: saat scroll ke kanan (lihat foto),
        # identitas baris tetap terlihat. RINGKASAN cukup freeze header.
        ws.freeze_panes = "A2" if sheet_name == "RINGKASAN" else "B2"

        # =========================
        # HEADER
        # =========================
        for col in range(1, ws.max_column+1):
            c = ws.cell(row=1, column=col)
            c.fill = header_fill
            c.font = header_font
            c.border = border
            c.alignment = header_align
        if sheet_name != "RINGKASAN":
            ws.row_dimensions[1].height = 100.5

        # =========================
        # MAP KOLOM
        # =========================
        col_map = {}
        pct_col = None
        status_col = None
        jam_col = None
        spark_col = None
        selisih_stanbaca_col = None
        indikasi_col = None
        blok_col_fills = {}   # col_idx -> tint fill (untuk data cells)
        for col in range(1, ws.max_column+1):
            val = ws.cell(row=1, column=col).value
            if val in bulan_list:
                col_map[val] = ws.cell(row=1, column=col).column_letter
            if val == "%PERUBAHAN":
                pct_col = col
            if val == "STATUS":
                status_col = col
            if val == "JAM_NYALA":
                jam_col = col
            if val == "SPARKLINE":
                spark_col = col
            if val == "SELISIH_STAN_BACA":
                selisih_stanbaca_col = col
            if val == "INDIKASI_STAN_BACA":
                indikasi_col = col
            for blok_name, blok in blok_style.items():
                if blok_name == "koreksi" and sheet_name == "KOREKSI_STAND":
                    continue
                if val in blok["cols"]:
                    ws.cell(row=1, column=col).fill = blok["header"]
                    blok_col_fills[col] = blok["tint"]

        has_foto_cols = bool(col_map)

        # =========================
        # RINGKASAN (format khusus)
        # =========================
        if sheet_name == "RINGKASAN":
            ws.column_dimensions["A"].width = 30
            ws.column_dimensions["B"].width = 15
            ws.column_dimensions["C"].width = 15
            ws.column_dimensions["D"].width = 15
            ws.column_dimensions["E"].width = 15
            ws.column_dimensions["F"].width = 15
            ws.column_dimensions["G"].width = 20

            bold_font = Font(bold=True)
            section_fill = PatternFill(start_color="D9E1F2", fill_type="solid")

            for row_num in range(1, ws.max_row + 1):
                val = ws.cell(row=row_num, column=1).value
                if val in ("STATUS","IDPEL","LABEL","INDIKASI"):
                    for c in range(1, ws.max_column + 1):
                        cell = ws.cell(row=row_num, column=c)
                        cell.fill = header_fill
                        cell.font = header_font
                        cell.border = border
                        cell.alignment = center
                elif val and isinstance(val, str) and (
                    "Top 10" in val or "Total" in val or "KLASIFIKASI" in val
                    or "INDIKASI STAN BACA" in val
                ):
                    ws.cell(row=row_num, column=1).font = bold_font
                    if "Top 10" in val or "KLASIFIKASI" in val or "INDIKASI STAN BACA" in val:
                        ws.cell(row=row_num, column=1).fill = section_fill

                # warna %PERUBAHAN di ringkasan
                if pct_col:
                    cell = ws.cell(row=row_num, column=pct_col)
                    fill = warna_perubahan(cell.value)
                    fnt = font_perubahan(cell.value)
                    if fill:
                        cell.fill = fill
                    if fnt:
                        cell.font = fnt

            continue

        # =========================
        # ROW LOOP
        # =========================
        idpels = list(data["IDPEL"])
        for i, idpel in enumerate(idpels):

            row_idx = i + 2

            ws.row_dimensions[row_idx].height = 190 if has_foto_cols else 22

            # Tint blok (dipasang duluan; highlight kondisional di bawah menang)
            for col_idx, tint in blok_col_fills.items():
                ws.cell(row=row_idx, column=col_idx).fill = tint

            # STATUS COLOR
            if status_col:
                status_cell = ws.cell(row=row_idx, column=status_col)
                if status_cell.value in warna_status:
                    status_cell.fill = warna_status[status_cell.value]
                status_cell.font = Font(bold=True)

            # JAM NYALA
            if jam_col:
                jam_cell = ws.cell(row=row_idx, column=jam_col)

                try:
                    jam = float(jam_cell.value)
                except:
                    jam = 0

                if jam > 1000:
                    jam_cell.fill = PatternFill(start_color="FF3333", fill_type="solid")
                    jam_cell.font = Font(bold=True)
                elif jam > 720:
                    jam_cell.fill = PatternFill(start_color="FF9999", fill_type="solid")
                    jam_cell.font = Font(bold=True)

            # %PERUBAHAN warna gradient
            if pct_col:
                pct_cell = ws.cell(row=row_idx, column=pct_col)
                fill = warna_perubahan(pct_cell.value)
                fnt = font_perubahan(pct_cell.value)
                if fill:
                    pct_cell.fill = fill
                if fnt:
                    pct_cell.font = fnt

            # SELISIH STAN BACA vs REKENING (highlight kalau beda > toleransi)
            if selisih_stanbaca_col:
                sel_cell = ws.cell(row=row_idx, column=selisih_stanbaca_col)
                try:
                    sel_val = abs(float(sel_cell.value))
                except (TypeError, ValueError):
                    sel_val = None
                if sel_val is not None and sel_val > stan_baca_toleransi:
                    sel_cell.fill = PatternFill(start_color="FFD966", fill_type="solid")
                    sel_cell.font = Font(bold=True)

            # INDIKASI STAN BACA warna sesuai kategori
            if indikasi_col:
                ind_cell = ws.cell(row=row_idx, column=indikasi_col)
                fill = warna_indikasi.get(ind_cell.value)
                if fill:
                    ind_cell.fill = fill
                    ind_cell.font = Font(bold=True)

            # BORDER + ALIGN
            for col in range(1, ws.max_column+1):
                c = ws.cell(row=row_idx, column=col)
                c.border = border
                c.alignment = center

            # SPARKLINE font styling
            if spark_col:
                sp_cell = ws.cell(row=row_idx, column=spark_col)
                sp_cell.font = Font(name="Consolas", size=14)

            # =========================
            # FOTO
            # =========================
            if sheet_name != "Normal":
                for idx, blth in enumerate(bulan_list, start=1):

                    if idpel in results and idx in results[idpel]:

                        img = Image(results[idpel][idx])
                        img.width = 260
                        img.height = 250

                        if blth in col_map:
                            ws.add_image(img, f"{col_map[blth]}{row_idx}")

        # =========================
        # AUTOFIT
        # =========================
        # Lebar dihitung dari ISI DATA saja (header dikecualikan) - header
        # dipendekkan lewat wrap_text di atas, bukan dengan melebarkan kolom.
        # Tanpa ini nama kolom panjang (mis. PEMAKAIAN_BULAN_LALU) memaksa
        # kolom lebar walau isinya cuma angka pendek, dan seluruh sheet
        # jadi tidak muat 1 layar.
        MIN_COL_WIDTH = 6
        for col in ws.columns:
            max_len = 0
            col_letter = col[0].column_letter

            for cell in col[1:]:
                if cell.value:
                    max_len = max(max_len, len(str(cell.value)))

            ws.column_dimensions[col_letter].width = max(min(max_len+2, 40), MIN_COL_WIDTH)

        # =========================
        # FIX KOLOM FOTO (WAJIB)
        # =========================
        for b in bulan_list:
            if b in col_map:
                ws.column_dimensions[col_map[b]].width = 42

        # Sparkline column width
        if spark_col:
            ws.column_dimensions[get_column_letter(spark_col)].width = 14

        # Kolom koreksi/formula: lebar tetap, bukan hasil autofit dari isi
        # (blank di sheet status / berisi formula di KOREKSI_STAND, jadi
        # panjang isinya tidak mencerminkan lebar yang wajar).
        for col in range(1, ws.max_column + 1):
            val = ws.cell(row=1, column=col).value
            letter = get_column_letter(col)
            if val == "PILIHAN":
                ws.column_dimensions[letter].width = 15
            elif val in ("KWH_MANUAL", "STAN_MANUAL"):
                ws.column_dimensions[letter].width = 12
            elif val == "STAN BARU":
                ws.column_dimensions[letter].width = 12
            elif val == "ALASAN KOREKSI":
                ws.column_dimensions[letter].width = 55

        # =========================
        # HIDE KOLOM PROYEKSI STAND
        # =========================
        # STAND_RATA2/STAND_P1/STAND_RUMAH_KOSONG cuma sumber formula
        # KOREKSI_STAND - tidak perlu dilihat manual di sheet status.
        # Dibiarkan tampil di KOREKSI_STAND sendiri (referensi user).
        if sheet_name != "KOREKSI_STAND":
            for col in range(1, ws.max_column + 1):
                val = ws.cell(row=1, column=col).value
                if val in ("STAND_RATA2", "STAND_P1", "STAND_RUMAH_KOSONG"):
                    ws.column_dimensions[get_column_letter(col)].hidden = True

    wb.save(output_file)
