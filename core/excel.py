import pandas as pd
from openpyxl import load_workbook
from openpyxl.drawing.image import Image
from openpyxl.styles import PatternFill, Font, Border, Side, Alignment


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


def export_excel(df, output_file, bulan_list):

    writer = pd.ExcelWriter(output_file, engine="openpyxl")
    sheet_map = {}

    for status, data in df.groupby("STATUS"):

        # Sort berdasarkan tipe status
        if status == "Kenaikan":
            data = data.sort_values(by="%PERUBAHAN", ascending=False)
        elif status == "Penurunan":
            data = data.sort_values(by="%PERUBAHAN", ascending=True)
        else:
            data = data.sort_values(by="JAM_NYALA", ascending=False)

        data_out = data[[
            "IDPEL","TARIF","DAYA",
            "STAND_LALU","STAND_KINI","PEMAKAIAN_BULAN_LALU","PEMAKAIAN",
            "RATA2","SPARKLINE","JAM_NYALA",
            "STATUS","%PERUBAHAN","DETAIL","KELAINAN"
        ]].copy()

        # FOTO
        for b in bulan_list:
            data_out[b] = ""

        # STAND DI KANAN
        data_out["STAND_RATA2"] = data["STAND_RATA2"]
        data_out["STAND_P1"] = data["STAND_P1"]
        data_out["STAND_RUMAH_KOSONG"] = data["STAND_RUMAH_KOSONG"]

        sheet_name = status[:30]
        data_out.to_excel(writer, sheet_name=sheet_name, index=False)

        sheet_map[sheet_name] = data_out

    # =========================
    # SHEET PRIORITAS KELAINAN
    # =========================
    kel_filter = [
        "ANJING GALAK","STAN DARI PELANGGAN","KWH METER TIDAK ADA",
        "RUMAH TUTUP","PEMADAMAN","BENCANA","KWH METER MACET",
        "KWH METER BURAM/PECAH","KWH METER DIDALAM BANGUNAN",
        "KWH METER TINGGI"
    ]

    df_kel = df[df["KELAINAN"].isin(kel_filter)]

    if not df_kel.empty:

        df_kel = df_kel.sort_values(by="JAM_NYALA", ascending=False)

        data_out = df_kel[[
            "IDPEL","TARIF","DAYA",
            "STAND_LALU","STAND_KINI","PEMAKAIAN_BULAN_LALU","PEMAKAIAN",
            "RATA2","SPARKLINE","JAM_NYALA",
            "STATUS","%PERUBAHAN","DETAIL","KELAINAN"
        ]].copy()

        for b in bulan_list:
            data_out[b] = ""

        data_out["STAND_RATA2"] = df_kel["STAND_RATA2"]
        data_out["STAND_P1"] = df_kel["STAND_P1"]
        data_out["STAND_RUMAH_KOSONG"] = df_kel["STAND_RUMAH_KOSONG"]

        data_out.to_excel(writer, sheet_name="PRIORITAS_KELAINAN", index=False)
        sheet_map["PRIORITAS_KELAINAN"] = data_out

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
                        "Trend Naik","Anomali vs Sejawat","Stand Tidak Wajar","DATA BARU"]:
        cnt = status_counts.get(status_name, 0)
        pct = round(cnt / total * 100, 1) if total > 0 else 0
        summary_data.append([status_name, cnt, pct])

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
    top_pnr = df[df["%PERUBAHAN"].fillna(0) < 0].nlargest(10, "%PERUBAHAN", keep="last")
    top_pnr = top_pnr.nsmallest(10, "%PERUBAHAN")
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


def format_excel(output_file, sheet_map, results, bulan_list):

    thin = Side(border_style="thin", color="000000")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    header_fill = PatternFill(start_color="4F81BD", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")

    center = Alignment(horizontal="center", vertical="center")

    warna_status = {
        "Stand Minus": PatternFill(start_color="FF9999", fill_type="solid"),
        "Meter Macet": PatternFill(start_color="FFCC99", fill_type="solid"),
        "Kenaikan": PatternFill(start_color="99CCFF", fill_type="solid"),
        "Penurunan": PatternFill(start_color="CCCCFF", fill_type="solid"),
    }

    wb = load_workbook(output_file)

    for sheet_name, data in sheet_map.items():

        ws = wb[sheet_name]
        ws.freeze_panes = "A2"

        # =========================
        # HEADER
        # =========================
        for col in range(1, ws.max_column+1):
            c = ws.cell(row=1, column=col)
            c.fill = header_fill
            c.font = header_font
            c.border = border
            c.alignment = center

        # =========================
        # MAP KOLOM
        # =========================
        col_map = {}
        pct_col = None
        status_col = None
        jam_col = None
        spark_col = None
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
                if val in ("STATUS","IDPEL"):
                    for c in range(1, ws.max_column + 1):
                        cell = ws.cell(row=row_num, column=c)
                        cell.fill = header_fill
                        cell.font = header_font
                        cell.border = border
                        cell.alignment = center
                elif val and isinstance(val, str) and ("Top 10" in val or "Total" in val):
                    ws.cell(row=row_num, column=1).font = bold_font
                    if "Top 10" in val:
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

            ws.row_dimensions[row_idx].height = 190

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
        for col in ws.columns:
            max_len = 0
            col_letter = col[0].column_letter

            for cell in col:
                if cell.value:
                    max_len = max(max_len, len(str(cell.value)))

            ws.column_dimensions[col_letter].width = min(max_len+2, 40)

        # =========================
        # FIX KOLOM FOTO (WAJIB)
        # =========================
        for b in bulan_list:
            if b in col_map:
                ws.column_dimensions[col_map[b]].width = 42

        # Sparkline column width
        if spark_col:
            from openpyxl.utils import get_column_letter
            ws.column_dimensions[get_column_letter(spark_col)].width = 14

    wb.save(output_file)
