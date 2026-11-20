import pandas as pd
from openpyxl import load_workbook
from openpyxl.drawing.image import Image
from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, TwoCellAnchor
from openpyxl.styles import PatternFill, Font, Border, Side, Alignment
from openpyxl.utils import column_index_from_string, get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.formatting.rule import FormulaRule

from core.analyzer import STATUS_JAM_TINGGI, STATUS_PASCA_NOL, STATUS_REKENING_MINIMUM
from core.cabut_pasang import (
    KOLOM_CABUT_PASANG,
    MASALAH_CABUT,
    MASALAH_PASANG,
    MASALAH_SELISIH,
)
from core.pagar_terkunci import KODE_PRIORITAS, huruf_kode_baca
from core.koreksi import (
    ALASAN_MAP,
    PILIHAN_BELUM_PDL,
    PILIHAN_BIARKAN,
    PILIHAN_BUTUH_KWH_MANUAL,
    PILIHAN_CAP720,
    PILIHAN_KURANG_TAGIH,
    PILIHAN_LEBIH_TAGIH,
    PILIHAN_MANUAL,
    PILIHAN_OPTIONS,
    PILIHAN_RATA2,
    PILIHAN_RUMAH_KOSONG,
    PILIHAN_SALAH_ENTRY,
    PILIHAN_SALAH_FOTO,
    PILIHAN_SALAH_PDL,
    SHEET_REKENING_PECAHAN,
    SHEET_RUMAH_KOSONG,
    sheet_tujuan,
)

# Sheet yang tidak diberi kolom koreksi: tidak ada yang perlu dikoreksi.
SHEET_TANPA_KOREKSI = ("Normal", "DATA BARU", STATUS_REKENING_MINIMUM)

# Sheet hasil pemetaan yang memuat baris dari beberapa STATUS sekaligus,
# jadi kolom STATUS perlu ditampilkan.
SHEET_CAMPURAN = (SHEET_REKENING_PECAHAN, SHEET_RUMAH_KOSONG)


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


# Blok kolom untuk pewarnaan visual (header + tint data), supaya pemeriksa
# langsung tahu sumber datanya: rekening billing vs baca meter fisik.
BLOK_REKENING = ("STAND_LALU", "STAND_KINI", "PEMAKAIAN_BULAN_LALU", "PEMAKAIAN")
BLOK_STAN_BACA = ("STAND_BACA_LALU", "PEMAKAIAN_ASLI", "SELISIH_STAN_BACA")
BLOK_RATA2 = ("RATA2",)
BLOK_CABUT_PASANG = KOLOM_CABUT_PASANG

# Teks penanda di kolom PILIHAN sheet status untuk baris yang koreksinya
# dipegang sheet CABUT_PASANG (lihat catatan kepemilikan di export_excel).
PILIHAN_LIHAT_CABUT_PASANG = "LIHAT CABUT_PASANG"

# Isi PILIHAN di KOREKSI_STAND kalau IDPEL-nya sudah hilang dari sheet sumber,
# supaya baris yang terhapus terlihat, bukan diam-diam menjadi "tidak dikoreksi".
PILIHAN_TIDAK_DITEMUKAN = "TIDAK DITEMUKAN"


# Ukuran foto di dalam sel. Baris 190 pt (253 px) dan kolom lebar 42 (299 px).
FOTO_LEBAR_PX = 250
FOTO_TINGGI_PX = 240
FOTO_MARGIN_PX = 4
EMU_PER_PX = 9525


def _jangkar_foto(kolom, baris):
    """Jangkar foto yang ikut baris saat sort dan filter.

    Foto wajib utuh di dalam satu sel dan bermode "Move and size with cells".
    Mode oneCell (bawaan add_image) tidak ikut mengecil saat baris difilter, jadi
    foto menumpuk di baris yang terlihat. Foto yang menempel di garis sel juga
    bisa salah ikut saat sort.
    """
    col = column_index_from_string(kolom) - 1
    row = baris - 1
    margin = FOTO_MARGIN_PX * EMU_PER_PX
    return TwoCellAnchor(
        editAs="twoCell",
        _from=AnchorMarker(col=col, colOff=margin, row=row, rowOff=margin),
        to=AnchorMarker(
            col=col, colOff=margin + FOTO_LEBAR_PX * EMU_PER_PX,
            row=row, rowOff=margin + FOTO_TINGGI_PX * EMU_PER_PX,
        ),
    )


def _rumus_cari(sheet, kolom, kolom_idpel, baris, gagal):
    """Rumus ambil nilai `kolom` di sheet sumber untuk IDPEL di baris ini.

    Dicari lewat IDPEL, bukan nomor baris: sheet status sering diurutkan, dan
    rujukan nomor baris akan membaca pilihan milik pelanggan lain tanpa tanda.
    INDEX pada sel kosong menghasilkan 0, karena itu kosong dicek dulu.
    """
    sn = sheet.replace("'", "''")
    nilai = (
        f"INDEX('{sn}'!${kolom}:${kolom},"
        f"MATCH($A{baris},'{sn}'!${kolom_idpel}:${kolom_idpel},0))"
    )
    return f'=IFERROR(IF({nilai}="","",{nilai}),"{gagal}")'


def _pasang_dropdown_koreksi(ws, data_out):
    """Pasang dropdown PILIHAN + highlight sel wajib isi di satu sheet.

    Dropdown selalu seluruh kolom: rentang validasi tidak ikut berpindah saat
    sheet diurutkan, jadi dropdown per baris akan salah tempat. Mengubah sel
    `LIHAT CABUT_PASANG` tetap tidak berpengaruh karena baris itu tidak punya
    pasangan di KOREKSI_STAND.

    Return (pil_letter, kwh_letter, stanm_letter).
    """
    pil_letter = get_column_letter(data_out.columns.get_loc("PILIHAN") + 1)
    kwh_letter = get_column_letter(data_out.columns.get_loc("KWH_MANUAL") + 1)
    stanm_letter = get_column_letter(data_out.columns.get_loc("STAN_MANUAL") + 1)

    last_row = len(data_out) + 1

    if last_row >= 2:
        dv = DataValidation(
            type="list",
            formula1='"' + ",".join(PILIHAN_OPTIONS) + '"',
            allow_blank=True,
            showDropDown=False,
        )
        ws.add_data_validation(dv)
        dv.add(f"{pil_letter}2:{pil_letter}{last_row}")

    # Pengingat visual: highlight sel yang WAJIB diisi user selama masih
    # kosong, supaya tidak lupa - hilang otomatis begitu diisi.
    # MANUAL/KURANG TAGIH -> KWH_MANUAL wajib; SALAH ENTRY -> STAN_MANUAL wajib.
    #
    # NOTE: fill utk conditional formatting (dxf) WAJIB set start_color DAN
    # end_color sama-sama - beda dari fill cell biasa yang cukup start_color
    # saja. Kalau cuma start_color, Excel diam-diam tidak merender fill-nya
    # sama sekali (dxf fgColor tanpa bgColor).
    for letter, pilihan_list, warna in (
        (kwh_letter, PILIHAN_BUTUH_KWH_MANUAL, "FFFF00"),
        (stanm_letter, (PILIHAN_SALAH_ENTRY,), "FFC000"),
    ):
        cocok = ",".join(f'${pil_letter}2="{p}"' for p in pilihan_list)
        ws.conditional_formatting.add(
            f"{letter}2:{letter}{last_row}",
            FormulaRule(
                formula=[f'AND(OR({cocok}),${letter}2="")'],
                fill=PatternFill(start_color=warna, end_color=warna, fill_type="solid"),
            ),
        )

    return pil_letter, kwh_letter, stanm_letter


def _build_sheet_data(source, bulan_list, include_status=False, include_koreksi=False,
                      include_cabut_pasang=False):
    """Susun kolom output untuk satu sheet.

    Urutan: identitas -> blok stan rekening -> blok stan baca -> blok cabut/
    pasang -> pola/kelainan -> (STATUS utk sheet campuran) -> foto ->
    proyeksi stand.
    DETAIL digabung ke KELAINAN. STATUS hanya diikutkan untuk sheet campuran
    (PRIORITAS_KELAINAN, BUKAN_KWH, CABUT_PASANG) - di sheet per-status sudah
    tercermin dari nama sheet.
    """
    data_out = source[[
        "IDPEL", "TARIF", "DAYA",
        "STAND_LALU", "STAND_KINI", "PEMAKAIAN_BULAN_LALU", "PEMAKAIAN",
    ]].copy()

    for col in BLOK_STAN_BACA:
        if col in source.columns:
            data_out[col] = source[col]

    # Blok cabut/pasang hanya di sheet CABUT_PASANG - di sheet lain kolomnya
    # kosong untuk hampir semua baris, cuma bikin lebar sia-sia.
    if include_cabut_pasang:
        for col in BLOK_CABUT_PASANG:
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
        # DASAR_SARAN: kenapa PILIHAN itu yang disarankan (hanya dibaca).
        if "DASAR_SARAN" in source.columns:
            data_out["DASAR_SARAN"] = source["DASAR_SARAN"].fillna("")
        data_out["PILIHAN"] = source["PILIHAN"]
        data_out["KWH_MANUAL"] = ""
        data_out["STAN_MANUAL"] = ""

    return data_out


def export_excel(df, output_file, bulan_list, klasifikasi=None, ocr_results=None):

    writer = pd.ExcelWriter(output_file, engine="openpyxl")
    sheet_map = {}
    koreksi_rows = []   # meta per baris untuk sheet KOREKSI_STAND

    # Sheet CABUT_PASANG hanya memuat baris yang BERMASALAH - baris cabut/
    # pasang yang standnya sehat tidak perlu diperiksa manual dan tetap
    # dikoreksi dari sheet STATUS-nya seperti biasa.
    # Baris bermasalah dikoreksi HANYA dari sheet CABUT_PASANG - lihat
    # catatan kepemilikan di blok sheet tersebut.
    if "MASALAH_CABUT_PASANG" in df.columns:
        masalah_cp = (
            df["ADA_CABUT_PASANG"].fillna(False).astype(bool)
            & (df["MASALAH_CABUT_PASANG"].fillna("") != "")
        )
    else:
        masalah_cp = pd.Series(False, index=df.index)

    # Satu baris = satu sheet (core/koreksi.sheet_tujuan): REKENING PECAHAN dari
    # status apa pun ke sheet sendiri, Stand Minus bersaran RUMAH KOSONG/LEBIH
    # TAGIH ke "Rumah Kosong-Lebih Tagih", sisanya ke sheet STATUS-nya.
    tujuan = sheet_tujuan(df)

    for status, data in df.groupby(tujuan):

        # Sort berdasarkan tipe status
        if status == "Kenaikan":
            data = data.sort_values(by="%PERUBAHAN", ascending=False)
        elif status == "Penurunan":
            data = data.sort_values(by="%PERUBAHAN", ascending=True)
        elif status in ("Stand Minus", SHEET_RUMAH_KOSONG) and "PILIHAN" in data.columns:
            # Kelompokkan per saran, supaya satu jenis koreksi berurutan.
            data = data.sort_values(by=["PILIHAN", "JAM_NYALA"], ascending=[True, False])
        else:
            data = data.sort_values(by="JAM_NYALA", ascending=False)

        include_koreksi = (
            status not in SHEET_TANPA_KOREKSI and "PILIHAN" in data.columns
        )
        data_out = _build_sheet_data(
            data, bulan_list,
            include_status=status in SHEET_CAMPURAN,
            include_koreksi=include_koreksi,
        )

        # Baris cabut/pasang: tandai bahwa koreksinya dilakukan di sheet
        # CABUT_PASANG, jangan biarkan dropdown kosong yang menyesatkan.
        cp_mask = masalah_cp.reindex(data.index).fillna(False).to_numpy()
        if include_koreksi and cp_mask.any():
            data_out.loc[cp_mask, "PILIHAN"] = PILIHAN_LIHAT_CABUT_PASANG

        sheet_name = status[:30]
        data_out.to_excel(writer, sheet_name=sheet_name, index=False)

        sheet_map[sheet_name] = data_out

        if include_koreksi:
            ws = writer.sheets[sheet_name]
            pil_letter, kwh_letter, stanm_letter = _pasang_dropdown_koreksi(ws, data_out)
            id_letter = get_column_letter(data_out.columns.get_loc("IDPEL") + 1)

            status_asli = data["STATUS"].to_numpy()
            for i, (_, r) in enumerate(data_out.iterrows()):
                if cp_mask[i]:
                    continue   # dipegang sheet CABUT_PASANG
                koreksi_rows.append({
                    "IDPEL": r["IDPEL"], "STATUS": status_asli[i],
                    "STAND_LALU": r["STAND_LALU"], "STAND_KINI": r["STAND_KINI"],
                    "JAM_NYALA": r["JAM_NYALA"],
                    "STAND_RATA2": r["STAND_RATA2"], "STAND_P1": r["STAND_P1"],
                    "STAND_RUMAH_KOSONG": r["STAND_RUMAH_KOSONG"],
                    "_sheet": sheet_name, "_id": id_letter,
                    "_pil": pil_letter, "_kwh": kwh_letter, "_stanm": stanm_letter,
                })

    # =========================
    # SHEET PRIORITAS KELAINAN
    # =========================
    # Anggota sheet ditentukan KD BACA ACMT (kode yang diinput petugas baca),
    # bukan kelainan_bc_meter billing - dua sumber itu bisa berbeda untuk
    # pelanggan yang sama. Kolom KELAINAN (billing) tetap tampil apa adanya;
    # KD BACA ACMT ditaruh di sebelahnya supaya keduanya terlihat. Tanpa kolom
    # KD_BACA_ACMT (ACMT tidak tersedia) sheet ini tidak dibuat.
    if "KD_BACA_ACMT" in df.columns:
        huruf = df["KD_BACA_ACMT"].fillna("").map(huruf_kode_baca)
        df_kel = df[huruf.isin(KODE_PRIORITAS)]
    else:
        df_kel = df.iloc[0:0]

    if not df_kel.empty:

        df_kel = df_kel.sort_values(by="JAM_NYALA", ascending=False)

        data_out = _build_sheet_data(df_kel, bulan_list, include_status=True)
        data_out.insert(data_out.columns.get_loc("KELAINAN") + 1,
                        "KD BACA ACMT", df_kel["KD_BACA_ACMT"].values)

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
    # SHEET CABUT_PASANG (validasi stand bongkar/pasang meter)
    # =========================
    # Sheet ini PEMILIK TUNGGAL koreksi untuk baris cabut/pasang. Baris yang
    # sama juga tampil di sheet STATUS asalnya (umumnya "Stand Minus"), tapi
    # di sana dropdown-nya sengaja dimatikan: kalau kedua sheet sama-sama
    # mendaftar ke koreksi_rows, satu IDPEL akan punya DUA baris STAN BARU
    # yang bisa saling bertentangan di file upload billing.
    if masalah_cp.any() and "PILIHAN" in df.columns:
        df_cp = df[masalah_cp].copy()

        # Selisih terbesar dulu - baris dengan tagihan rollover katastrofik
        # (mis. 100.000 kWh) muncul paling awal.
        df_cp = df_cp.reindex(
            pd.to_numeric(df_cp["SELISIH_CABUT_PASANG"], errors="coerce")
            .abs().fillna(0).sort_values(ascending=False).index
        )

        data_out = _build_sheet_data(
            df_cp, bulan_list,
            include_status=True, include_koreksi=True, include_cabut_pasang=True,
        )
        # Semua baris di sheet ini boleh dikoreksi manual; tidak ada saran
        # otomatis karena penyebabnya (salah entry stand cabut vs stand
        # pasang vs meter memang diganti) hanya bisa dipastikan dari foto.
        data_out["PILIHAN"] = PILIHAN_BIARKAN
        if "DASAR_SARAN" in data_out.columns:
            data_out["DASAR_SARAN"] = "CEK STAND CABUT/PASANG"

        data_out.to_excel(writer, sheet_name="CABUT_PASANG", index=False)
        sheet_map["CABUT_PASANG"] = data_out

        ws_cp = writer.sheets["CABUT_PASANG"]
        pil_letter, kwh_letter, stanm_letter = _pasang_dropdown_koreksi(ws_cp, data_out)
        id_letter = get_column_letter(data_out.columns.get_loc("IDPEL") + 1)

        for _, r in data_out.iterrows():
            koreksi_rows.append({
                "IDPEL": r["IDPEL"], "STATUS": "CABUT_PASANG",
                "STAND_LALU": r["STAND_LALU"], "STAND_KINI": r["STAND_KINI"],
                "JAM_NYALA": r["JAM_NYALA"],
                "STAND_RATA2": r["STAND_RATA2"], "STAND_P1": r["STAND_P1"],
                "STAND_RUMAH_KOSONG": r["STAND_RUMAH_KOSONG"],
                "_sheet": "CABUT_PASANG", "_id": id_letter,
                "_pil": pil_letter, "_kwh": kwh_letter, "_stanm": stanm_letter,
            })

    # =========================
    # SHEET KOREKSI_STAND (siap upload)
    # =========================
    # PILIHAN, KWH_MANUAL & STAN_MANUAL dicari lewat IDPEL ke sheet status
    # masing-masing, jadi begitu user mengubah pilihan di sana, STAN BARU +
    # ALASAN KOREKSI di sini ikut berubah, apa pun urutan sheet-nya.
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
            ws_kor.cell(row=r, column=6).value = _rumus_cari(
                m["_sheet"], m["_pil"], m["_id"], r, PILIHAN_TIDAK_DITEMUKAN,
            )
            ws_kor.cell(row=r, column=7).value = _rumus_cari(
                m["_sheet"], m["_kwh"], m["_id"], r, "",
            )
            ws_kor.cell(row=r, column=8).value = _rumus_cari(
                m["_sheet"], m["_stanm"], m["_id"], r, "",
            )
            # STAN BARU: RATA2/SALAH FOTO/CAP-720/RUMAH KOSONG/LEBIH TAGIH
            # pakai kolom proyeksi (LEBIH TAGIH = stand lalu, sama dengan
            # RUMAH KOSONG); MANUAL/KURANG TAGIH = STAND_LALU + KWH_MANUAL;
            # SALAH ENTRY = STAN_MANUAL langsung (wajib diisi, tidak ada
            # fallback); SALAH PDL/BELUM PDL = STAN_MANUAL kalau diisi, else
            # fallback STAND_RATA2.
            ws_kor.cell(row=r, column=12).value = (
                f'=IF(OR(F{r}="{PILIHAN_RATA2}",F{r}="{PILIHAN_SALAH_FOTO}"),I{r},'
                f'IF(F{r}="{PILIHAN_CAP720}",J{r},'
                f'IF(OR(F{r}="{PILIHAN_RUMAH_KOSONG}",F{r}="{PILIHAN_LEBIH_TAGIH}"),K{r},'
                f'IF(OR(F{r}="{PILIHAN_MANUAL}",F{r}="{PILIHAN_KURANG_TAGIH}"),C{r}+N(G{r}),'
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
                f'IF(F{r}="{PILIHAN_SALAH_FOTO}","{ALASAN_MAP[PILIHAN_SALAH_FOTO]}",'
                f'IF(F{r}="{PILIHAN_SALAH_PDL}","{ALASAN_MAP[PILIHAN_SALAH_PDL]}",'
                f'IF(F{r}="{PILIHAN_BELUM_PDL}","{ALASAN_MAP[PILIHAN_BELUM_PDL]}",'
                f'IF(F{r}="{PILIHAN_LEBIH_TAGIH}","{ALASAN_MAP[PILIHAN_LEBIH_TAGIH]}",'
                f'IF(F{r}="{PILIHAN_KURANG_TAGIH}","{ALASAN_MAP[PILIHAN_KURANG_TAGIH]}",'
                f'""))))))))))'
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
    for status_name in ["Normal","Stand Minus","Meter Macet","Kenaikan",
                        "Penurunan",STATUS_JAM_TINGGI,
                        "Trend Naik","Stand Tidak Wajar",STATUS_REKENING_MINIMUM,
                        STATUS_PASCA_NOL,"DATA BARU"]:
        cnt = status_counts.get(status_name, 0)
        pct = round(cnt / total * 100, 1) if total > 0 else 0
        summary_data.append([status_name, cnt, pct])

    # Pemetaan sheet: berapa baris dipindah dari sheet STATUS-nya, dan saran
    # otomatis di sheet koreksi Stand Minus.
    summary_data.append([""])
    summary_data.append(["PEMETAAN SHEET"])
    summary_data.append(["SHEET", "JUMLAH"])
    jumlah_sheet = tujuan.value_counts()
    for nama in (SHEET_REKENING_PECAHAN, SHEET_RUMAH_KOSONG, "Stand Minus"):
        summary_data.append([nama, int(jumlah_sheet.get(nama, 0))])
    if "PILIHAN" in df.columns:
        sm_rk = tujuan.isin(["Stand Minus", SHEET_RUMAH_KOSONG])
        for pilihan, cnt in df.loc[sm_rk, "PILIHAN"].value_counts().items():
            summary_data.append([f"  saran {pilihan}", int(cnt)])

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

    # Cabut/pasang meter summary
    if "ADA_CABUT_PASANG" in df.columns:
        n_cp = int(df["ADA_CABUT_PASANG"].fillna(False).astype(bool).sum())
        n_cp_masalah = int(masalah_cp.sum())

        summary_data.append([""])
        summary_data.append(["CABUT/PASANG METER"])
        summary_data.append(["INDIKASI", "JUMLAH"])
        summary_data.append(["Ada aktivitas cabut/pasang", n_cp])
        summary_data.append(["Stand cabut/pasang bermasalah", n_cp_masalah])

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

    # =========================
    # URUTAN SHEET
    # =========================
    # Sheet per-status lahir dalam urutan groupby (alfabetis), sisanya
    # menyusul di belakang. CABUT_PASANG ditarik ke sebelah kanan "Stand
    # Minus" karena mayoritas temuannya memang berasal dari sana - pemeriksa
    # bisa langsung lompat dari satu sheet ke sheet lanjutannya.
    # Rumah Kosong-Lebih Tagih dan REKENING_PECAHAN ikut ditarik ke sana: isinya
    # dulu bagian dari Stand Minus, jadi urutannya Stand Minus -> Rumah
    # Kosong-Lebih Tagih -> REKENING_PECAHAN -> CABUT_PASANG.
    wb = writer.book
    jangkar = "Stand Minus"
    for nama in (SHEET_RUMAH_KOSONG, SHEET_REKENING_PECAHAN, "CABUT_PASANG"):
        if nama not in wb.sheetnames:
            continue
        if jangkar not in wb.sheetnames:
            jangkar = nama
            continue
        ws_pindah = wb[nama]
        wb._sheets.remove(ws_pindah)
        wb._sheets.insert(wb.sheetnames.index(jangkar) + 1, ws_pindah)
        jangkar = nama

    writer.close()
    return sheet_map


def format_excel(output_file, sheet_map, results, bulan_list, ocr_results=None, cfg=None):
    stan_baca_toleransi = (cfg or {}).get("stand_tidak_wajar_toleransi", 1)

    thin = Side(border_style="thin", color="000000")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    header_fill = PatternFill(start_color="4F81BD", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")

    center = Alignment(horizontal="center", vertical="center")
    wrap_left = Alignment(horizontal="left", vertical="center", wrap_text=True)
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

    warna_status = {
        "Stand Minus": PatternFill(start_color="FF9999", fill_type="solid"),
        "Meter Macet": PatternFill(start_color="FFCC99", fill_type="solid"),
        "Kenaikan": PatternFill(start_color="99CCFF", fill_type="solid"),
        "Penurunan": PatternFill(start_color="CCCCFF", fill_type="solid"),
        STATUS_PASCA_NOL: PatternFill(start_color="FFE699", fill_type="solid"),
        STATUS_REKENING_MINIMUM: PatternFill(start_color="D9D9D9", fill_type="solid"),
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
        # Teal = stand bongkar/pasang meter (hanya muncul di CABUT_PASANG).
        "cabutpasang": {
            "cols": BLOK_CABUT_PASANG,
            "header": PatternFill(start_color="1F7A7A", fill_type="solid"),
            "tint": PatternFill(start_color="DAF0F0", fill_type="solid"),
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
        masalah_cp_col = None
        cp_cols = {}          # nama kolom cabut/pasang -> col_idx
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
            if val == "MASALAH_CABUT_PASANG":
                masalah_cp_col = col
            if val in ("STAND_CABUT", "STAND_PASANG", "SELISIH_CABUT_PASANG"):
                cp_cols[val] = col
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
                if val in ("STATUS","IDPEL","LABEL","INDIKASI","SHEET"):
                    for c in range(1, ws.max_column + 1):
                        cell = ws.cell(row=row_num, column=c)
                        cell.fill = header_fill
                        cell.font = header_font
                        cell.border = border
                        cell.alignment = center
                elif val and isinstance(val, str) and (
                    "Top 10" in val or "Total" in val or "KLASIFIKASI" in val
                    or "CABUT/PASANG METER" in val or val == "PEMETAAN SHEET"
                ):
                    ws.cell(row=row_num, column=1).font = bold_font
                    if "Total" not in val:
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

            # PELANGGARAN CABUT/PASANG - warnai kolom stand yang jadi
            # penyebabnya, dibaca dari teks MASALAH_CABUT_PASANG supaya
            # sumber kebenarannya tetap satu (core/cabut_pasang.py).
            if masalah_cp_col:
                masalah_cell = ws.cell(row=row_idx, column=masalah_cp_col)
                masalah = str(masalah_cell.value or "")
                if masalah:
                    masalah_cell.fill = PatternFill(start_color="FFC7CE", fill_type="solid")
                    masalah_cell.font = Font(bold=True, color="9C0006")

                    for teks, nama_kolom in (
                        (MASALAH_CABUT, "STAND_CABUT"),
                        (MASALAH_PASANG, "STAND_PASANG"),
                        (MASALAH_SELISIH, "SELISIH_CABUT_PASANG"),
                    ):
                        if teks in masalah and nama_kolom in cp_cols:
                            bad = ws.cell(row=row_idx, column=cp_cols[nama_kolom])
                            bad.fill = PatternFill(start_color="FF9999", fill_type="solid")
                            bad.font = Font(bold=True)

            # BORDER + ALIGN
            for col in range(1, ws.max_column+1):
                c = ws.cell(row=row_idx, column=col)
                c.border = border
                # Teks masalah panjang: rata kiri + wrap supaya terbaca utuh,
                # sisanya rata tengah seperti kolom angka lain.
                c.alignment = wrap_left if col == masalah_cp_col else center

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

                        try:
                            img = Image(results[idpel][idx])
                        except (OSError, ValueError):
                            # File rusak/bukan gambar: lewati sel ini saja,
                            # jangan gagalkan seluruh laporan.
                            img = None

                        if img is not None and blth in col_map:
                            img.anchor = _jangkar_foto(col_map[blth], row_idx)
                            ws.add_image(img)

        # Filter header membuat Excel mengurutkan seluruh tabel. Sort satu kolom
        # saja memisahkan IDPEL dari datanya, dan itu tidak bisa dideteksi rumus.
        ws.auto_filter.ref = ws.dimensions

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
            elif val == "MASALAH_CABUT_PASANG":
                ws.column_dimensions[letter].width = 34
            elif val == "DASAR_SARAN":
                ws.column_dimensions[letter].width = 28

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
