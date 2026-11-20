"""
Halaman Koreksi: pilih file hasil analisa, Load, Simulasi, Kirim.

Modul terpisah dari ui.py karena PyArmor trial menolak code object besar. Pekerjaan
jaringan ada di core/koreksi_alur.py dan berjalan di thread; hasilnya kembali lewat
`App.queue` dengan pesan `koreksi_*`, seperti semua pesan pipeline lain.
"""

import os
import threading
from tkinter import filedialog, messagebox
import tkinter as tk

import ttkbootstrap as tb
from ttkbootstrap.constants import *
from ttkbootstrap.scrolled import ScrolledText

from config import ENABLE_KOREKSI_KIRIM
from core.billing_client import BillingAuthError, BillingError
from core.koreksi_alur import (
    KoreksiBerhenti,
    PERINGATAN_KUNING,
    PERINGATAN_MERAH,
    TAHAP_BELUM,
    TAHAP_BELUM_VERIFIKASI,
    TAHAP_BERUBAH,
    TAHAP_DIBLOKIR,
    TAHAP_GAGAL,
    TAHAP_OK,
    TAHAP_SIMULASI,
    TAHAP_SUDAH,
    TAHAP_TERKIRIM,
    TAHAP_TIDAK_PASTI,
    akun_tersimpan,
    aman_dicentang,
    bisa_dikirim,
    jumlah_belum_selesai,
    keterangan,
    reset_server,
    ringkasan,
    run_ganti_akun,
    run_kirim,
    run_proses,
    siapkan_baris,
    tulis_laporan,
)
from core.koreksi_sumber import (
    JENIS_ANOMALI,
    JENIS_BILLING,
    JENIS_MURNI,
    JENIS_PERLU_DICEK,
    JENIS_TIDAK,
    KoreksiFileError,
    baca_koreksi,
    blth_dari_path,
)

LANGKAH = ("Pilih File", "Load & Simulasi", "Kirim", "Selesai")
NAMA_TUGAS = {"proses": "Load & Simulasi", "kirim": "Kirim"}
TEKS_DETAIL = (
    "Klik baris untuk keterangan lengkap. Klik 2x untuk menyalin IDPEL. "
    "Tekan Delete untuk mengeluarkan baris dari daftar."
)

# (kunci, judul, warna) kartu ringkasan. Kunci yang sama dipakai filter tabel.
KARTU = (
    ("SEMUA", "Semua Koreksi", INFO),
    (JENIS_MURNI, "720 Murni", PRIMARY),
    (JENIS_ANOMALI, "720 Anomali", PRIMARY),
    (JENIS_BILLING, "Koreksi Billing", PRIMARY),
    ("MERAH", "JN Masih ≥ 720", DANGER),
    (JENIS_PERLU_DICEK, "Perlu Dicek", WARNING),
    (JENIS_TIDAK, "Tidak Dikoreksi", SECONDARY),
)

# (id, judul, lebar, rata)
KOLOM = (
    ("centang", "Kirim", 46, CENTER),
    ("idpel", "IDPEL", 104, W),
    ("nama", "Nama", 140, W),
    ("jenis", "Jenis", 112, W),
    ("status", "Status", 120, W),
    ("pilihan", "Pilihan", 112, W),
    ("jn", "JN", 66, E),
    ("jn_hasil", "JN Hasil", 66, E),
    ("lalu", "Stan Lalu", 76, E),
    ("kini", "Stan Kini", 76, E),
    ("baru", "Stan Baru", 76, E),
    ("rp_lama", "RPTAG Lama", 96, E),
    ("rp_baru", "RPTAG Baru", 96, E),
    ("selisih", "Selisih", 96, E),
    ("ket", "Keterangan", 320, W),
)

WARNA_TAG = {
    "merah": {"background": "#7f1d1d", "foreground": "#ffffff"},
    "kuning": {"background": "#78350f", "foreground": "#ffffff"},
    "hijau": {"background": "#14532d", "foreground": "#ffffff"},
    "dicek": {"foreground": "#e67e22"},
    "redup": {"foreground": "#8a8f98"},
}

TEKS_KUNCI_KIRIM = (
    "Kirim belum diaktifkan. Load dan Simulasi aman dicoba; "
    "tidak ada data billing yang berubah."
)


def _rupiah(nilai):
    if not isinstance(nilai, (int, float)):
        return ""
    return f"{nilai:,.0f}".replace(",", ".")


def _angka(nilai):
    if not isinstance(nilai, (int, float)):
        return ""
    return f"{nilai:,.2f}".rstrip("0").rstrip(".").replace(",", "@").replace(
        ".", ",").replace("@", ".")


class HalamanKoreksi(tb.Frame):

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.rows = []
        self.per_iid = {}
        self.filter = "SEMUA"
        self.path = ""
        self.tugas = None
        self.akun = None
        self.path_laporan = None
        self.kartu = {}

        self._build_akun()
        self._build_langkah()
        self._build_file()
        self._build_kartu()
        self._build_aksi()
        self._build_log()
        self._build_tabel()

        self._muat_akun()
        self.perbarui()

    # ── BANGUN TAMPILAN ───────────────────────────────────

    @staticmethod
    def _ikut_lebar(label, wadah, sisa):
        """Bungkus teks label mengikuti lebar wadah, supaya tidak terpotong saat
        jendela diperkecil."""
        wadah.bind(
            "<Configure>",
            lambda e: label.config(wraplength=max(e.width - sisa, 60)),
            add="+",
        )

    def _build_akun(self):
        frame = tb.Frame(self)
        frame.pack(fill=X, padx=15, pady=(12, 0))
        self.akun_label = tb.Label(frame, font=("Segoe UI", 10))
        self.akun_label.pack(side=LEFT)
        self.ganti_btn = tb.Button(
            frame, text="Ganti Akun", bootstyle=(SECONDARY, OUTLINE),
            command=self._ganti_akun, width=12,
        )
        self.ganti_btn.pack(side=RIGHT)

    def _build_langkah(self):
        frame = tb.Frame(self)
        frame.pack(fill=X, padx=15, pady=(10, 4))
        self.langkah_label = []
        for i, nama in enumerate(LANGKAH):
            if i:
                tb.Label(frame, text="────", bootstyle=SECONDARY).pack(side=LEFT, padx=4)
            label = tb.Label(frame, text=f"○ {i + 1}. {nama}", font=("Segoe UI", 10))
            label.pack(side=LEFT)
            self.langkah_label.append(label)

    def _build_file(self):
        frame = tb.LabelFrame(self, text="  File Hasil Analisa  ")
        frame.pack(fill=X, padx=15, pady=6, ipadx=10, ipady=6)

        baris = tb.Frame(frame)
        baris.pack(fill=X)
        tb.Label(baris, text="File:", font=("Segoe UI", 10)).pack(side=LEFT, padx=(0, 8))
        self.path_var = tk.StringVar()
        tb.Entry(baris, textvariable=self.path_var, state="readonly").pack(
            side=LEFT, fill=X, expand=True, padx=(0, 8))
        tb.Label(baris, text="BLTH:", font=("Segoe UI", 10)).pack(side=LEFT, padx=(0, 6))
        self.blth_var = tk.StringVar()
        self.blth_var.trace_add("write", lambda *_: self._blth_berubah())
        self.blth_entry = tb.Entry(baris, textvariable=self.blth_var, width=8)
        self.blth_entry.pack(side=LEFT, padx=(0, 8))
        self.browse_btn = tb.Button(
            baris, text="Browse...", command=self._browse, bootstyle=SECONDARY, width=11,
        )
        self.browse_btn.pack(side=LEFT, padx=(0, 6))
        self.baca_btn = tb.Button(
            baris, text="Baca Ulang", command=self._baca_ulang,
            bootstyle=(SECONDARY, OUTLINE), width=11,
        )
        self.baca_btn.pack(side=LEFT)

        self.pesan_file = tb.Label(
            frame, font=("Segoe UI", 9), bootstyle=SECONDARY, wraplength=1000,
            justify=LEFT,
            text="Pilih file hasil_analisa yang sudah diisi pilihan koreksinya, "
                 "disimpan di Excel, lalu ditutup.",
        )
        self.pesan_file.pack(anchor=W, pady=(6, 0))
        self._ikut_lebar(self.pesan_file, frame, 24)

    def _build_kartu(self):
        frame = tb.Frame(self)
        frame.pack(fill=X, padx=15, pady=4)
        for kolom, (kunci, judul, warna) in enumerate(KARTU):
            frame.columnconfigure(kolom, weight=1, uniform="kartu")
            sel = tb.Frame(frame, bootstyle=warna, padding=2)
            sel.grid(row=0, column=kolom, sticky=NSEW, padx=3)
            isi = tb.Frame(sel, padding=(8, 5))
            isi.pack(fill=BOTH, expand=True)
            angka = tb.Label(isi, text="0", font=("Segoe UI", 16, "bold"), bootstyle=warna)
            angka.pack(anchor=W)
            nama = tb.Label(isi, text=judul, font=("Segoe UI", 9))
            nama.pack(anchor=W)
            self._ikut_lebar(nama, isi, 16)
            for w in (sel, isi, angka, nama):
                w.bind("<Button-1>", lambda _e, k=kunci: self._pilih_filter(k))
                w.configure(cursor="hand2")
            self.kartu[kunci] = (sel, angka, nama, warna)

    def _build_aksi(self):
        frame = tb.Frame(self)
        frame.pack(side=BOTTOM, fill=X, padx=15, pady=(4, 10))
        self.proses_btn = tb.Button(
            frame, text="Load & Simulasi", bootstyle=INFO, width=28, command=self._proses,
        )
        self.proses_btn.pack(side=LEFT, padx=(0, 6))
        self.kirim_btn = tb.Button(
            frame, text="Kirim Koreksi", bootstyle=SUCCESS, width=20, command=self._kirim,
        )
        self.kirim_btn.pack(side=LEFT, padx=(0, 6))
        self.stop_btn = tb.Button(
            frame, text="Berhenti", bootstyle=DANGER, width=10, command=self._berhenti,
        )
        self.stop_btn.pack(side=LEFT, padx=(0, 10))
        self.laporan_btn = tb.Button(
            frame, text="Buka Laporan", bootstyle=(SUCCESS, OUTLINE), width=13,
            command=self._buka_laporan,
        )
        self.status_label = tb.Label(frame, text="", font=("Segoe UI", 9), bootstyle=INFO)
        self.status_label.pack(side=RIGHT)
        self.progress = tb.Progressbar(
            frame, mode=DETERMINATE, bootstyle=SUCCESS, length=150,
        )
        self.progress.pack(side=RIGHT, padx=(0, 8))

        self.kunci_label = tb.Label(
            self, text=TEKS_KUNCI_KIRIM, font=("Segoe UI", 9, "italic"), bootstyle=WARNING,
        )
        if not ENABLE_KOREKSI_KIRIM:
            self.kunci_label.pack(side=BOTTOM, anchor=W, padx=15)

    def _build_log(self):
        self.log_text = ScrolledText(
            self, height=4, autohide=True, font=("Consolas", 9),
        )
        self.log_text.pack(side=BOTTOM, fill=X, padx=15, pady=(2, 2))
        self.log_text.text.config(state=DISABLED)

        self.detail_label = tb.Label(
            self, font=("Segoe UI", 9), bootstyle=SECONDARY, wraplength=1000,
            justify=LEFT, text=TEKS_DETAIL,
        )
        self.detail_label.pack(side=BOTTOM, anchor=W, padx=15, pady=(2, 0))
        self._ikut_lebar(self.detail_label, self, 30)

    def _build_tabel(self):
        frame = tb.Frame(self)
        frame.pack(fill=BOTH, expand=True, padx=15, pady=(4, 0))

        alat = tb.Frame(frame)
        alat.pack(fill=X, pady=(0, 4))
        self.filter_label = tb.Label(alat, font=("Segoe UI", 10, "bold"))
        self.filter_label.pack(side=LEFT)
        self.hapus_btn = tb.Button(
            alat, text="Hapus Centang", bootstyle=(SECONDARY, OUTLINE),
            command=lambda: self._centang_semua(False), width=14,
        )
        self.hapus_btn.pack(side=RIGHT, padx=(6, 0))
        self.aman_btn = tb.Button(
            alat, text="Centang yang Aman", bootstyle=(SECONDARY, OUTLINE),
            command=lambda: self._centang_semua(True), width=18,
        )
        self.aman_btn.pack(side=RIGHT)

        wadah = tb.Frame(frame)
        wadah.pack(fill=BOTH, expand=True)
        self.tree = tb.Treeview(
            wadah, columns=[k[0] for k in KOLOM], show="headings", height=8,
            selectmode="extended",
        )
        for kunci, judul, lebar, rata in KOLOM:
            self.tree.heading(kunci, text=judul)
            self.tree.column(kunci, width=lebar, minwidth=40, anchor=rata, stretch=False)
        for tag, warna in WARNA_TAG.items():
            self.tree.tag_configure(tag, **warna)
        gulir_y = tb.Scrollbar(wadah, orient=VERTICAL, command=self.tree.yview)
        gulir_x = tb.Scrollbar(wadah, orient=HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=gulir_y.set, xscrollcommand=gulir_x.set)
        self.tree.grid(row=0, column=0, sticky=NSEW)
        gulir_y.grid(row=0, column=1, sticky=NS)
        gulir_x.grid(row=1, column=0, sticky=EW)
        wadah.rowconfigure(0, weight=1)
        wadah.columnconfigure(0, weight=1)
        self.tree.bind("<Button-1>", self._klik_tabel)
        self.tree.bind("<<TreeviewSelect>>", self._pilih_baris)
        self.tree.bind("<Double-1>", self._salin_idpel)
        self.tree.bind("<Delete>", self._hapus_baris)

    # ── AKUN ──────────────────────────────────────────────

    def _muat_akun(self):
        try:
            self.terima_akun(akun_tersimpan())
        except Exception:
            self.terima_akun(None)

    def terima_akun(self, akun):
        self.akun = akun
        if akun:
            self.akun_label.config(
                text=f"Akun portal: {akun.get('nama') or '-'} "
                     f"({akun.get('userId') or '-'}), unit {akun.get('unitup') or '-'}",
                bootstyle=INFO,
            )
        else:
            self.akun_label.config(
                text="Akun portal: belum login. Login diminta saat menekan Load.",
                bootstyle=WARNING,
            )

    def _ganti_akun(self):
        self._mulai("akun", self._thread_ganti_akun, "Login portal...")

    def _thread_ganti_akun(self):
        run_ganti_akun(
            self.app.queue.put,
            self.app.billing_login_event,
            self.app.billing_credentials_holder,
        )

    # ── FILE ──────────────────────────────────────────────

    def _browse(self):
        path = filedialog.askopenfilename(
            title="Pilih file hasil analisa",
            filetypes=[("File hasil analisa", "*.xlsx"), ("Semua file", "*.*")],
        )
        if path:
            self.pilih_file(path)

    def pilih_file(self, path):
        """Dipanggil dari Browse dan dari drag-drop App."""
        if self.app.running:
            return
        self.path = path
        self.path_var.set(path)
        blth = blth_dari_path(path)
        if blth:
            self.blth_var.set(blth)
        self._baca_ulang()

    def _baca_ulang(self):
        if not self.path or self.app.running:
            return
        self.rows = []
        self.path_laporan = None
        self.laporan_btn.pack_forget()
        self.filter = "SEMUA"
        try:
            df = baca_koreksi(self.path)
        except KoreksiFileError as e:
            self.pesan_file.config(text=str(e), bootstyle=DANGER)
            messagebox.showwarning("File tidak bisa dipakai", str(e))
            self.perbarui()
            return
        self.rows = siapkan_baris(df)
        pesan = f"{len(self.rows):,} baris terbaca dari {os.path.basename(self.path)}."
        gaya = SUCCESS
        sejajar = df.attrs.get("tidak_sejajar_tanpa_koreksi", 0)
        if sejajar:
            pesan += (
                f" Perhatian: {sejajar:,} baris tanpa koreksi tidak sejajar dengan "
                "sheet status. Sheet kemungkinan pernah diurutkan, jadi periksa "
                "apakah ada pilihan koreksi yang tidak terbawa."
            )
            gaya = WARNING
        if not self.blth_valid():
            pesan += " Isi BLTH secara manual, contoh 202611."
            gaya = WARNING
        self.pesan_file.config(text=pesan, bootstyle=gaya)
        self.log(f"File dibaca: {self.path}")
        self.tampilkan()

    def blth_valid(self):
        blth = self.blth_var.get().strip()
        return len(blth) == 6 and blth.isdigit() and 1 <= int(blth[4:]) <= 12

    def _blth_berubah(self):
        # Hasil Load terikat ke satu periode; memakainya di periode lain akan
        # mengirim koreksi ke rekening bulan yang salah.
        if getattr(self, "rows", None) and any(r["TAHAP"] for r in self.rows):
            reset_server(self.rows)
            self.tampilkan()
        elif hasattr(self, "proses_btn"):
            self.perbarui()

    # ── TABEL ─────────────────────────────────────────────

    def _cocok_filter(self, r):
        return self._cocok_kunci(r, self.filter)

    @staticmethod
    def _cocok_kunci(r, kunci):
        if kunci == "SEMUA":
            return bool(r["JALUR"])
        if kunci == "MERAH":
            return r["PERINGATAN"] == PERINGATAN_MERAH
        if kunci == JENIS_PERLU_DICEK:
            return r["JENIS"] == kunci or r["TAHAP"] in (TAHAP_DIBLOKIR, TAHAP_GAGAL)
        return r["JENIS"] == kunci

    @staticmethod
    def _tag(r):
        if r["PERINGATAN"] == PERINGATAN_MERAH:
            return "merah"
        if r["TAHAP"] in (TAHAP_OK, TAHAP_SUDAH):
            return "hijau"
        if r["PERINGATAN"] == PERINGATAN_KUNING or r["TAHAP"] in (
            TAHAP_TIDAK_PASTI, TAHAP_BELUM_VERIFIKASI,
        ):
            return "kuning"
        if r["JENIS"] == JENIS_PERLU_DICEK or r["TAHAP"] in (
            TAHAP_DIBLOKIR, TAHAP_GAGAL, TAHAP_BERUBAH,
        ):
            return "dicek"
        if r["JENIS"] == JENIS_TIDAK:
            return "redup"
        return ""

    @staticmethod
    def _nilai(r):
        if bisa_dikirim(r):
            centang = "☑" if r["CENTANG"] else "☐"
        else:
            centang = ""
        status = r["TAHAP"]
        if not status:
            status = r["JENIS"] if r["JENIS"] in (JENIS_PERLU_DICEK, JENIS_TIDAK) else "Belum dimuat"
        return (
            centang, r["IDPEL"], r["NAMA"], r["JENIS"], status, r["PILIHAN"],
            _angka(r["JAM_NYALA"]), _angka(r["JN_HASIL"]), _angka(r["STAND_LALU"]),
            _angka(r["STAND_KINI"]), r["STAN_BARU_TEKS"], _rupiah(r["RPTAG_LAMA"]),
            _rupiah(r["RPTAG_BARU"]), _rupiah(r["SELISIH"]), keterangan(r),
        )

    def tampilkan(self):
        """Isi ulang tabel sesuai filter, lalu segarkan kartu dan tombol."""
        self.tree.delete(*self.tree.get_children())
        self.per_iid = {}
        for i, r in enumerate(self.rows):
            r["_IID"] = str(i)
            self.per_iid[r["_IID"]] = r
            if self._cocok_filter(r):
                self.tree.insert(
                    "", END, iid=r["_IID"], values=self._nilai(r), tags=(self._tag(r),),
                )
        self.perbarui()

    def _segarkan_baris(self, r):
        iid = r.get("_IID")
        cocok = self._cocok_filter(r)
        ada = iid is not None and self.tree.exists(iid)
        if ada and cocok:
            self.tree.item(iid, values=self._nilai(r), tags=(self._tag(r),))
        elif ada:
            self.tree.delete(iid)
        elif cocok and iid is not None:
            self.tree.insert("", END, iid=iid, values=self._nilai(r), tags=(self._tag(r),))

    def _pilih_filter(self, kunci):
        self.filter = kunci
        self.tampilkan()

    def _klik_tabel(self, event):
        if self.app.running or self.tree.identify_column(event.x) != "#1":
            return
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        r = self.per_iid.get(self.tree.identify_row(event.y))
        if r is None or not bisa_dikirim(r):
            return
        r["CENTANG"] = not r["CENTANG"]
        self._segarkan_baris(r)
        self.perbarui()

    def _pilih_baris(self, _event=None):
        pilihan = self.tree.selection()
        r = self.per_iid.get(pilihan[0]) if pilihan else None
        if r is None:
            return
        ket = keterangan(r) or "Tidak ada catatan."
        alasan = f"Alasan: {r['ALASAN']}. " if r["ALASAN"] else ""
        self.detail_label.config(text=f"{r['IDPEL']}: {alasan}{ket}")

    def _salin_idpel(self, event):
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        if self.tree.identify_column(event.x) == "#1":
            return  # kolom centang: klik cepat tetap berarti centang
        r = self.per_iid.get(self.tree.identify_row(event.y))
        if r is None:
            return
        self.clipboard_clear()
        self.clipboard_append(r["IDPEL"])
        self.status_label.config(text=f"IDPEL {r['IDPEL']} disalin", bootstyle=SUCCESS)

    def _hapus_baris(self, _event=None):
        """Keluarkan baris terpilih dari daftar kerja. File Excel tidak berubah,
        jadi Baca Ulang mengembalikannya."""
        if self.app.running:
            return
        terpilih = [self.per_iid[i] for i in self.tree.selection()]
        # Baris terkirim tetap di daftar supaya masuk laporan.
        hapus = [r for r in terpilih if r["TAHAP"] not in TAHAP_TERKIRIM]
        if len(hapus) != len(terpilih):
            self.status_label.config(
                text="Baris yang sudah dikirim tidak bisa dihapus", bootstyle=WARNING,
            )
        if not hapus:
            return
        ditandai = {id(r) for r in hapus}
        self.rows = [r for r in self.rows if id(r) not in ditandai]
        self.log("Dikeluarkan dari daftar: " + ", ".join(r["IDPEL"] for r in hapus))
        self.detail_label.config(text=TEKS_DETAIL)
        self.tampilkan()

    def _centang_semua(self, nilai):
        for r in self.rows:
            if bisa_dikirim(r):
                r["CENTANG"] = nilai and aman_dicentang(r)
        self.tampilkan()

    # ── STATUS TAMPILAN ───────────────────────────────────

    def _posisi_langkah(self):
        tahap = {r["TAHAP"] for r in self.rows}
        if tahap & set(TAHAP_TERKIRIM):
            return 3
        if TAHAP_SIMULASI in tahap:
            return 2
        return 1 if self.rows else 0

    def perbarui(self):
        """Segarkan kartu, langkah, dan keaktifan tombol."""
        for kunci, (_sel, angka, nama, _warna) in self.kartu.items():
            jumlah = sum(1 for r in self.rows if self._cocok_kunci(r, kunci))
            angka.config(text=f"{jumlah:,}")
            nama.config(font=("Segoe UI", 9, "bold" if kunci == self.filter else "normal"))

        judul = next(k[1] for k in KARTU if k[0] == self.filter)
        self.filter_label.config(text=judul)

        posisi = self._posisi_langkah()
        for i, label in enumerate(self.langkah_label):
            if i < posisi:
                label.config(text=f"✓ {i + 1}. {LANGKAH[i]}", bootstyle=SUCCESS)
            elif i == posisi:
                label.config(text=f"● {i + 1}. {LANGKAH[i]}", bootstyle=INFO)
            else:
                label.config(text=f"○ {i + 1}. {LANGKAH[i]}", bootstyle=SECONDARY)

        sibuk = self.app.running
        jalan = NORMAL if not sibuk else DISABLED
        sisa = jumlah_belum_selesai(self.rows)
        sudah_jalan = any(r["TAHAP"] for r in self.rows)
        terpilih = sum(1 for r in self.rows if r["CENTANG"] and bisa_dikirim(r))

        def status(syarat):
            return NORMAL if syarat and not sibuk else DISABLED

        self.proses_btn.config(
            state=status(sisa and self.blth_valid()),
            text=f"Ulangi yang Belum Beres ({sisa:,})" if sudah_jalan and sisa
            else "Load & Simulasi",
        )
        self.kirim_btn.config(
            state=status(ENABLE_KOREKSI_KIRIM and terpilih),
            text=f"Kirim Koreksi ({terpilih:,})",
        )
        self.stop_btn.config(state=NORMAL if self.tugas else DISABLED)
        self.browse_btn.config(state=jalan)
        self.baca_btn.config(state=status(self.path))
        self.ganti_btn.config(state=jalan)
        self.blth_entry.config(state=jalan)
        self.aman_btn.config(state=status(self.rows))
        self.hapus_btn.config(state=status(self.rows))

    def log(self, pesan):
        teks = self.log_text.text
        teks.config(state=NORMAL)
        teks.insert(END, f"{pesan}\n")
        teks.see(END)
        teks.config(state=DISABLED)

    # ── MENJALANKAN TUGAS ─────────────────────────────────

    def _mulai(self, tugas, target, teks):
        if self.app.running:
            return
        self.app.stop = False
        self.app.billing_login_event.clear()
        self.app.billing_credentials_holder.cancel()
        self.tugas = tugas
        self.progress["value"] = 0
        self.status_label.config(text=teks, bootstyle=INFO)
        self.app._set_running(True)

        def jalan():
            error = None
            try:
                target()
            except KoreksiBerhenti as e:
                error = str(e)
            except (BillingAuthError, BillingError) as e:
                error = f"Login portal: {e}"
            except Exception as e:
                error = f"Terjadi kesalahan: {e}"
            self.app.queue.put(("koreksi_selesai", error))

        threading.Thread(target=jalan, daemon=True).start()

    def _argumen(self):
        return {
            "progress_callback": self.app.queue.put,
            "stop_flag": lambda: self.app.stop,
            "login_event": self.app.billing_login_event,
            "credentials_holder": self.app.billing_credentials_holder,
        }

    def _proses(self):
        blth = self.blth_var.get().strip()
        self._mulai(
            "proses", lambda: run_proses(self.rows, blth, **self._argumen()),
            "Load & Simulasi...",
        )

    def _kirim(self):
        target = [r for r in self.rows if r["CENTANG"] and bisa_dikirim(r)]
        if not target or not self._konfirmasi(target):
            return
        blth = self.blth_var.get().strip()
        self._mulai(
            "kirim", lambda: run_kirim(self.rows, blth, **self._argumen()),
            "Mengirim koreksi...",
        )

    def _konfirmasi(self, target):
        """Dialog terakhir sebelum menulis ke billing. True kalau disetujui."""
        dialog = tb.Toplevel(self.app.root)
        dialog.title("Konfirmasi Kirim Koreksi")
        dialog.transient(self.app.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        frm = tb.Frame(dialog, padding=20)
        frm.pack(fill=BOTH, expand=True)

        akun = self.akun or {}
        lama = sum(r["RPTAG_LAMA"] or 0 for r in target)
        baru = sum(r["RPTAG_BARU"] or 0 for r in target)
        bermasalah = sum(1 for r in target if not aman_dicentang(r))
        per_jenis = {}
        for r in target:
            per_jenis[r["JENIS"]] = per_jenis.get(r["JENIS"], 0) + 1

        tb.Label(
            frm, text=f"Kirim {len(target):,} koreksi ke billing?",
            font=("Segoe UI", 13, "bold"), bootstyle=DANGER,
        ).pack(anchor=W, pady=(0, 4))
        tb.Label(
            frm, text="Perubahan langsung masuk ke billing dan tidak bisa dibatalkan.",
            font=("Segoe UI", 9), bootstyle=SECONDARY,
        ).pack(anchor=W, pady=(0, 10))

        isi = [
            ("Akun", f"{akun.get('nama') or '-'} ({akun.get('userId') or '-'})"),
            ("Unit / BLTH", f"{akun.get('unitup') or '-'} / {self.blth_var.get()}"),
        ]
        isi += [(j, f"{per_jenis[j]:,} baris") for j in sorted(per_jenis)]
        isi += [
            ("RPTAG sebelum", f"Rp {_rupiah(lama)}"),
            ("RPTAG sesudah", f"Rp {_rupiah(baru)}"),
            ("Selisih", f"Rp {_rupiah(baru - lama)}"),
        ]
        tabel = tb.Frame(frm)
        tabel.pack(fill=X, pady=(0, 10))
        for i, (kiri, kanan) in enumerate(isi):
            tb.Label(tabel, text=kiri, font=("Segoe UI", 10)).grid(
                row=i, column=0, sticky=W, padx=(0, 24), pady=1)
            tb.Label(tabel, text=kanan, font=("Segoe UI", 10, "bold")).grid(
                row=i, column=1, sticky=W, pady=1)
        if bermasalah:
            tb.Label(
                frm, text=f"{bermasalah:,} baris yang dicentang masih berperingatan, "
                          "termasuk JN hasil ≥ 720.",
                font=("Segoe UI", 10, "bold"), bootstyle=DANGER,
            ).pack(anchor=W, pady=(0, 10))

        hasil = {"ya": False}
        setuju = tk.BooleanVar(value=False)
        tombol = tb.Frame(frm)

        def kirim():
            hasil["ya"] = True
            dialog.destroy()

        tombol_kirim = tb.Button(
            tombol, text="Kirim", bootstyle=DANGER, width=12, command=kirim, state=DISABLED,
        )
        tb.Checkbutton(
            frm, text="Saya sudah memeriksa hasil simulasi", variable=setuju,
            command=lambda: tombol_kirim.config(state=NORMAL if setuju.get() else DISABLED),
        ).pack(anchor=W, pady=(0, 12))
        tombol.pack(fill=X)
        tombol_kirim.pack(side=RIGHT, padx=(8, 0))
        tb.Button(
            tombol, text="Batal", bootstyle=SECONDARY, width=12, command=dialog.destroy,
        ).pack(side=RIGHT)

        dialog.bind("<Escape>", lambda _e: dialog.destroy())
        dialog.update_idletasks()
        root = self.app.root
        x = root.winfo_x() + (root.winfo_width() - dialog.winfo_width()) // 2
        y = root.winfo_y() + (root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")
        dialog.wait_window()
        return hasil["ya"]

    def _berhenti(self):
        self.app.stop = True
        self.status_label.config(text="Menunggu baris yang sedang diproses...", bootstyle=WARNING)

    def _buka_laporan(self):
        if self.path_laporan and os.path.exists(self.path_laporan):
            os.startfile(self.path_laporan)

    # ── PESAN DARI THREAD ─────────────────────────────────

    def terima(self, kind, data):
        if kind == "koreksi_log":
            self.log(data)
        elif kind == "koreksi_baris":
            self._segarkan_baris(data)
        elif kind == "koreksi_progres":
            selesai, total, teks = data
            self.progress["value"] = selesai * 100 / max(total, 1)
            self.status_label.config(text=teks, bootstyle=INFO)
        elif kind == "koreksi_akun":
            self.terima_akun(data)
        elif kind == "koreksi_selesai":
            self._selesai(data)

    def _selesai(self, error):
        tugas = self.tugas
        self.tugas = None
        self.app._set_running(False)
        self.app._perbarui_label_unit()
        self.progress["value"] = 100 if not error else self.progress["value"]

        # Ulangi bisa mengubah baris Tidak Pasti, jadi laporannya ikut diperbarui.
        if tugas != "akun" and any(r["TAHAP"] in TAHAP_TERKIRIM for r in self.rows):
            self._simpan_laporan()
        self.tampilkan()

        if error:
            self.status_label.config(text="Berhenti", bootstyle=DANGER)
            self.log(f"ERROR: {error}")
            messagebox.showerror("Koreksi", error)
            return
        hitung = ringkasan(self.rows)
        teks = ", ".join(f"{k} {v:,}" for k, v in sorted(hitung.items()))
        sisa = jumlah_belum_selesai(self.rows)
        self.status_label.config(
            text=f"Selesai, {sisa:,} belum beres" if sisa else "Selesai",
            bootstyle=WARNING if sisa else SUCCESS,
        )
        if tugas != "akun":
            self.log(f"{NAMA_TUGAS[tugas]} selesai: {teks}")
        if tugas == "proses":
            merah = sum(1 for r in self.rows if r["PERINGATAN"] == PERINGATAN_MERAH)
            if merah:
                self._pilih_filter("MERAH")
                messagebox.showwarning(
                    "JN hasil masih ≥ 720",
                    f"{merah:,} baris masih ≥ 720 jam nyala setelah simulasi. Baris "
                    "ditandai merah dan tidak dicentang otomatis. Periksa stan barunya.",
                )
        elif tugas == "kirim":
            messagebox.showinfo("Kirim Koreksi Selesai", teks)

    def _simpan_laporan(self):
        akun = self.akun or {}
        try:
            self.path_laporan = tulis_laporan(
                self.rows, self.blth_var.get().strip(), akun.get("unitup"), akun,
            )
        except OSError as e:
            self.log(f"ERROR laporan tidak tersimpan: {e}")
            return
        self.log(f"Laporan: {self.path_laporan}")
        self.laporan_btn.pack(side=LEFT)
