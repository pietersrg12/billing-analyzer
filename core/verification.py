"""
Verifikasi coverage database sebelum pipeline lanjut ke analyze/download.

Mengecek apakah sebuah database historis (stan rekening ATAU stan baca)
sudah terisi data untuk N bulan terakhir (N = cfg["jumlah_bulan_rata2"]),
baik secara global (bulan yang sama sekali tidak ada barisnya) maupun per
pelanggan (berapa banyak IDPEL di batch DPM yang riwayatnya masih kurang
dari N bulan). Hasilnya untuk warning saja — pipeline tetap boleh lanjut
kalau user memilih demikian.
"""

from core.photo import build_bulan_list

# Sebuah bulan baru dianggap "ada" kalau jumlah barisnya minimal sekian kali
# median jumlah baris per bulan di database itu. Tanpa ambang ini SATU baris
# nyasar sudah cukup: 2026-09 satu baca susulan tanggal 1/08 membuat bulan
# 202609 stan baca tampak lengkap, sehingga tombol Update tidak muncul dan
# analisa 202610 memakai baca dua bulan lalu.
RASIO_BULAN_MIN = 0.5


def check_coverage(db_df, blth, n_bulan, idpel_list=None):
    """Return dict ringkasan coverage. db_df boleh None (db tidak tersedia).

    Database historis (rekening maupun stan baca) tidak pernah memuat
    periode `blth` yang sedang dianalisis - baris blth baru masuk ke
    database setelah proses billing periode itu selesai. Jadi window yang
    diverifikasi adalah n_bulan sebelum blth (blth-1 s.d. blth-n_bulan),
    bukan termasuk blth sendiri. Reuse build_bulan_list(blth, n+1) lalu buang
    elemen pertama (blth) supaya tidak duplikasi logika tanggal.
    """
    bulan_list = build_bulan_list(blth, n_bulan + 1)[1:]

    if db_df is None or db_df.empty:
        return {
            "available": False,
            "bulan_list": bulan_list,
            "missing_bulan": bulan_list,
            "n_bulan_efektif": 0,
            "n_idpel_checked": len(idpel_list) if idpel_list else 0,
            "n_idpel_incomplete": len(idpel_list) if idpel_list else 0,
            "sample_incomplete": [],
        }

    bulan_int = [int(b) for b in bulan_list]
    hitung = db_df["BULAN"].astype(int).value_counts()
    ambang = hitung.median() * RASIO_BULAN_MIN
    present = set(hitung[hitung >= ambang].index)
    missing_bulan = [b for b, bi in zip(bulan_list, bulan_int) if bi not in present]

    # Bulan yang hilang DB-WIDE dilaporkan lewat missing_bulan; hitungan
    # per-pelanggan hanya dibanding bulan yang benar-benar ada di database.
    # Tanpa ini, satu bulan kosong db-wide membuat SEMUA pelanggan diflag
    # "belum lengkap" - noise yang tidak actionable.
    bulan_efektif = [bi for bi in bulan_int if bi in present]
    n_bulan_efektif = len(bulan_efektif)

    incomplete = []
    if idpel_list and n_bulan_efektif > 0:
        scoped = db_df[db_df["BULAN"].astype(int).isin(bulan_efektif)]
        counts = scoped.groupby("IDPEL")["BULAN"].nunique()
        for idpel in idpel_list:
            n = int(counts.get(idpel, 0))
            if n < n_bulan_efektif:
                incomplete.append((idpel, n))

    return {
        "available": True,
        "bulan_list": bulan_list,
        "missing_bulan": missing_bulan,
        "n_bulan_efektif": n_bulan_efektif,
        "n_idpel_checked": len(idpel_list) if idpel_list else 0,
        "n_idpel_incomplete": len(incomplete),
        "sample_incomplete": incomplete[:20],
    }
