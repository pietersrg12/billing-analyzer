"""
Dialog-dialog UI PLN Billing Analyzer.

Dipisah dari ui.py sebagai mixin, bukan sebagai fungsi lepas: seluruh metode di
sini memakai atribut instance App (self.root, self.queue, self.status_label,
self.billing_credentials_holder, ...). Dengan mixin, pemisahan ini murni
memindahkan teks - tidak ada satu pun pemanggilan yang berubah.

Pemisahannya sendiri bukan sekadar kerapian: PyArmor versi trial menolak code
object di atas 35.728 byte, dan ui.py yang utuh mencapai 45.632 byte sehingga
tidak bisa diacak sama sekali. Setelah dipecah, keduanya jauh di bawah batas.
Kalau nanti menambah dialog baru, perhatikan batas itu.
"""

import glob
import os

import tkinter as tk
from tkinter import messagebox

import ttkbootstrap as tb
from ttkbootstrap.constants import *

from config import (
    APP_DATA_DIR,
    APP_NAMA,
    APP_PEMBUAT,
    APP_TAHUN,
    APP_TEMPAT,
    APP_VERSI,
)
from core import settings


# Field yang diisi dalam PERSEN - dapat sufiks "%" di kanan kotak isian.
FIELD_PERSEN = {"kenaikan_persen_min", "penurunan_persen_min", "trend_persen_min"}

# Pengelompokan field untuk dialog Pengaturan Rule:
#   (judul grup, kalimat penjelas, [(key, label), ...])
#
# Label ditulis sebagai kalimat utuh bersatuan, bukan istilah teknis - dialog
# ini dipakai orang yang tidak membaca kode. Sengaja memakai kata "median"
# (bukan "rata-rata") karena core/analyzer.py memang menghitung median; nama
# kolom Excel RATA2 dibiarkan apa adanya supaya file hasil tidak berubah.
# Jumlah bulan tidak ditulis di label ("median riwayat", bukan "median 6
# bulan") karena mengikuti jumlah_bulan_rata2 yang bisa diubah user.
RULE_FIELD_GROUPS = [
    ("Riwayat Pemakaian",
     "Jendela riwayat yang jadi dasar semua perbandingan di bawah. Nilai "
     "pembanding memakai MEDIAN, bukan rata-rata, supaya satu bulan ekstrem "
     "tidak menggeser patokan.", [
        ("jumlah_bulan_rata2", "Jumlah bulan riwayat yang dipakai (bulan)"),
    ]),
    ("Kenaikan",
     "Ditandai \"Kenaikan\" bila pemakaian bulan ini melewati KEDUA batas di "
     "bawah. Batas pemakaian minimum menyaring pelanggan kecil, karena naik "
     "50% dari 40 kWh cuma +20 kWh dan itu bukan anomali.", [
        ("kenaikan_pemakaian_min", "Pemakaian minimum agar ikut dicek (kWh)"),
        ("kenaikan_persen_min", "Selisih pemakaian minimal di atas median"),
    ]),
    ("Penurunan",
     "Ditandai \"Penurunan\" bila pemakaian turun sebanyak batas ini tapi "
     "tidak nol - pemakaian nol ditangani rule Meter Macet.", [
        ("penurunan_persen_min", "Selisih pemakaian minimal di bawah median"),
    ]),
    ("Jam Nyala (sheet >720JN)",
     "Jam nyala = pemakaian (kWh) dibagi daya (kW). 720 jam setara sebulan "
     "penuh nonstop, jadi di atasnya berarti pemakaian melampaui kemampuan "
     "fisik daya terpasang. Konstanta CAP-720 sengaja sedikit di bawah batas "
     "supaya stand hasil koreksi tidak lagi melewatinya.", [
        ("jam_nyala_tinggi_min", "Masuk sheet >720JN bila jam nyala minimal (jam)"),
        ("stand_p1_jam_konstan", "Jam yang dipakai usulan koreksi CAP-720 (jam)"),
    ]),
    ("Trend Naik",
     "Ditandai bila pemakaian naik terus TANPA TERPUTUS sepanjang riwayat, "
     "dan totalnya tumbuh melewati batas di bawah.", [
        ("trend_min_bulan", "Minimal jumlah bulan data tersedia (bulan)"),
        ("trend_persen_min", "Selisih pemakaian bulan terakhir vs bulan pertama"),
    ]),
    ("Stand Tidak Wajar",
     "Selisih stand (stand kini - stand lalu) seharusnya persis sama dengan "
     "pemakaian yang ditagih. Ditandai bila bedanya melewati toleransi ini.", [
        ("stand_tidak_wajar_toleransi", "Toleransi beda selisih stand vs pemakaian (kWh)"),
    ]),
    ("Cabut/Pasang Meter",
     "Saat ganti meter atau mutasi tarif, pemakaian dipecah dua segmen: "
     "(stand cabut - stand awal) + (stand kini - stand pasang). Ditandai bila "
     "hasilnya beda dari pemakaian yang ditagih.", [
        ("cabut_pasang_toleransi", "Toleransi beda pemakaian hitung vs ditagih (kWh)"),
    ]),
]


class DialogMixin:
    """Kumpulan dialog modal. Di-mixin ke ui.App."""

    # ── PILIH UNIT ────────────────────────────────────────

    def _unit_terdeteksi(self):
        """Kode unit yang databasenya sudah ada di folder data.

        Dibaca dari NAMA file (database_44320.xlsx), bukan dari isinya - jauh
        lebih murah daripada membuka file ratusan ribu baris hanya untuk
        mengisi daftar pilihan.
        """
        pola = os.path.join(APP_DATA_DIR, "database_*.xls*")
        unit = set()
        for berkas in glob.glob(pola):
            nama = os.path.splitext(os.path.basename(berkas))[0]
            for awalan in ("database_stand_baca_", "database_"):
                if nama.startswith(awalan):
                    sisa = nama[len(awalan):]
                    if sisa:
                        unit.add(sisa)
                    break
        return sorted(unit)

    def _show_unit_dialog(self):
        """Dialog pilih unit aktif. Return kode unit, atau None kalau batal."""
        sekarang = settings.get_unit_aktif() or ""

        dialog = tb.Toplevel(self.root)
        dialog.title("Unit Aktif")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        frm = tb.Frame(dialog, padding=20)
        frm.pack(fill=BOTH, expand=True)

        tb.Label(
            frm, text="Unit Aktif", font=("Segoe UI", 13, "bold"), bootstyle=PRIMARY
        ).pack(anchor=W, pady=(0, 4))

        tb.Label(
            frm,
            text="Menentukan database mana yang dipakai dan diperbarui. Tiap unit "
                 "punya databasenya sendiri, jadi salah unit membuat aplikasi "
                 "melaporkan database milik orang lain.",
            font=("Segoe UI", 9), bootstyle=SECONDARY, wraplength=420,
        ).pack(anchor=W, pady=(0, 12))

        tb.Label(frm, text="Kode unit (unitup)", font=("Segoe UI", 9)).pack(anchor=W)
        unit_var = tk.StringVar(value=sekarang)
        entry = tb.Entry(frm, textvariable=unit_var, width=44)
        entry.pack(fill=X, pady=(2, 2))
        tb.Label(
            frm,
            text="Mis. 44320. Terisi sendiri setiap kali Anda login, jadi biasanya "
                 "tidak perlu diketik manual.",
            font=("Segoe UI", 8, "italic"), bootstyle=SECONDARY, wraplength=420,
        ).pack(anchor=W, pady=(0, 10))

        terdeteksi = self._unit_terdeteksi()
        if terdeteksi:
            kotak = tb.LabelFrame(frm, text="  Database yang sudah ada  ")
            kotak.pack(fill=X, pady=(0, 12))
            isi = tb.Frame(kotak, padding=8)
            isi.pack(fill=X)
            for i, kode in enumerate(terdeteksi):
                tb.Button(
                    isi, text=kode, bootstyle=(INFO, OUTLINE), width=10,
                    command=lambda k=kode: unit_var.set(k),
                ).grid(row=i // 4, column=i % 4, padx=4, pady=3)
        else:
            tb.Label(
                frm,
                text="Belum ada database unit mana pun. Setelah login lewat "
                     "Update Database, unit ini terisi sendiri.",
                font=("Segoe UI", 9), bootstyle=WARNING, wraplength=420,
            ).pack(anchor=W, pady=(0, 12))

        hasil = {"unit": None}

        def _simpan():
            u = unit_var.get().strip().upper()
            if not u:
                messagebox.showwarning(
                    "Peringatan", "Kode unit tidak boleh kosong.", parent=dialog
                )
                return
            settings.set_unit_aktif(u)
            hasil["unit"] = u
            dialog.destroy()

        def _batal():
            hasil["unit"] = None
            dialog.destroy()

        btn = tb.Frame(frm)
        btn.pack(fill=X)
        tb.Button(btn, text="Simpan", command=_simpan, bootstyle=SUCCESS,
                  width=12).pack(side=RIGHT, padx=(8, 0))
        tb.Button(btn, text="Batal", command=_batal, bootstyle=SECONDARY,
                  width=12).pack(side=RIGHT)

        dialog.bind("<Return>", lambda e: _simpan())
        dialog.bind("<Escape>", lambda e: _batal())
        dialog.protocol("WM_DELETE_WINDOW", _batal)

        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")
        entry.focus_set()

        dialog.wait_window()

        if hasil["unit"]:
            self._perbarui_label_unit(hasil["unit"])
        return hasil["unit"]

    # ── RULE SETTINGS DIALOG ──────────────────────────────

    def _show_rule_settings_dialog(self):
        """Dialog untuk mengubah threshold rule anomali. Simpan/Reset/Batal."""

        current = settings.load_rules()

        dialog = tb.Toplevel(self.root)
        dialog.title("Pengaturan Rule Deteksi Anomali")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.geometry("580x660")

        tb.Label(
            dialog,
            text="Pengaturan Rule Deteksi Anomali",
            font=("Segoe UI", 13, "bold"),
            bootstyle=PRIMARY,
        ).pack(anchor=W, padx=15, pady=(15, 10))

        body = tb.Frame(dialog, padding=(15, 0, 5, 0))
        body.pack(fill=BOTH, expand=True)

        canvas = tk.Canvas(body, highlightthickness=0)
        scrollbar = tb.Scrollbar(body, orient=VERTICAL, command=canvas.yview)
        scroll_frame = tb.Frame(canvas)

        scroll_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        field_vars = {}
        row = 0
        for group_title, group_desc, fields in RULE_FIELD_GROUPS:
            tb.Label(
                scroll_frame,
                text=group_title,
                font=("Segoe UI", 10, "bold"),
                bootstyle=INFO,
            ).grid(row=row, column=0, columnspan=3, sticky=W, pady=(12, 2), padx=(0, 10))
            row += 1

            # Kalimat penjelas grup: dialog ini dipakai orang yang tidak
            # membaca kode, jadi tiap rule dijelaskan sekali di sini daripada
            # memaksa label field jadi panjang.
            # Sengaja TIDAK memakai bootstyle=SECONDARY: di tema darkly warnanya
            # abu gelap di atas latar gelap dan praktis tidak terbaca. Ukuran
            # font yang lebih kecil sudah cukup membedakannya dari label field.
            tb.Label(
                scroll_frame,
                text=group_desc,
                font=("Segoe UI", 9),
                wraplength=520,
                justify=LEFT,
            ).grid(row=row, column=0, columnspan=3, sticky=W, pady=(0, 8), padx=(10, 15))
            row += 1

            for key, label in fields:
                tb.Label(
                    scroll_frame, text=label, font=("Segoe UI", 9),
                    wraplength=300, justify=LEFT,
                ).grid(row=row, column=0, sticky=W, padx=(10, 8), pady=2)
                var = tk.StringVar(value=str(current.get(key, settings.DEFAULT_RULES[key])))
                entry = tb.Entry(scroll_frame, textvariable=var, width=8, font=("Segoe UI", 9))
                entry.grid(row=row, column=1, sticky=W, pady=2)
                tb.Label(
                    scroll_frame,
                    text="%" if key in FIELD_PERSEN else "",
                    font=("Segoe UI", 9),
                ).grid(row=row, column=2, sticky=W, pady=2, padx=(3, 15))
                field_vars[key] = var
                row += 1

        btn_frame = tb.Frame(dialog, padding=(15, 10, 15, 15))
        btn_frame.pack(fill=X)

        def _reset():
            for key, var in field_vars.items():
                var.set(str(settings.DEFAULT_RULES[key]))

        def _save():
            new_rules = {}
            try:
                for key, var in field_vars.items():
                    # Field persen berlabel "(%)" dan bertanda "%" di sebelah
                    # kotaknya, jadi isian "50%" wajar diketik dan harus
                    # diterima - tanpa rstrip, float("50%") gagal dan input
                    # yang maksudnya sudah jelas ditolak sebagai bukan angka.
                    raw = var.get().strip().rstrip("%").strip()
                    if isinstance(settings.DEFAULT_RULES[key], int):
                        new_rules[key] = int(float(raw))
                    else:
                        new_rules[key] = float(raw)
            except ValueError:
                messagebox.showerror(
                    "Input tidak valid",
                    "Semua nilai harus berupa angka.",
                    parent=dialog,
                )
                return
            settings.save_rules(new_rules)
            messagebox.showinfo("Tersimpan", "Pengaturan rule disimpan.", parent=dialog)
            canvas.unbind_all("<MouseWheel>")
            dialog.destroy()

        def _cancel():
            canvas.unbind_all("<MouseWheel>")
            dialog.destroy()

        tb.Button(
            btn_frame, text="Reset ke Default", command=_reset, bootstyle=WARNING, width=16
        ).pack(side=LEFT)
        tb.Button(
            btn_frame, text="Batal", command=_cancel, bootstyle=SECONDARY, width=10
        ).pack(side=RIGHT, padx=(8, 0))
        tb.Button(
            btn_frame, text="Simpan", command=_save, bootstyle=SUCCESS, width=10
        ).pack(side=RIGHT)

        dialog.protocol("WM_DELETE_WINDOW", _cancel)

        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")

        dialog.wait_window()

    # ── VERIFIKASI DATABASE DIALOG ────────────────────────

    def _show_verification_dialog(self, payload):
        """Dialog ringkasan coverage database. Blocking sampai user Lanjut/Batal."""

        n_bulan = payload.get("n_bulan", 6)

        dialog = tb.Toplevel(self.root)
        dialog.title("Verifikasi Database")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        frm = tb.Frame(dialog, padding=20)
        frm.pack(fill=BOTH, expand=True)

        tb.Label(
            frm,
            text="Verifikasi Coverage Database",
            font=("Segoe UI", 13, "bold"),
            bootstyle=PRIMARY,
        ).pack(anchor=W, pady=(0, 4))

        tb.Label(
            frm,
            text=f"Mengecek apakah database sudah terisi {n_bulan} bulan terakhir "
                 f"(sesuai Pengaturan Rule).",
            font=("Segoe UI", 9),
            bootstyle=SECONDARY,
            wraplength=420,
        ).pack(anchor=W, pady=(0, 12))

        def _render_db_summary(title, cov):
            box = tb.LabelFrame(frm, text=f"  {title}  ")
            box.pack(fill=X, pady=(0, 10))
            inner = tb.Frame(box, padding=8)
            inner.pack(fill=X)

            if cov is None:
                tb.Label(inner, text="Fitur ini tidak diaktifkan.", bootstyle=SECONDARY).pack(
                    anchor=W
                )
                return

            if not cov.get("available"):
                tb.Label(
                    inner,
                    text="Database tidak ditemukan / kosong.",
                    bootstyle=DANGER,
                ).pack(anchor=W)
                return

            missing = cov.get("missing_bulan") or []
            if missing:
                tb.Label(
                    inner,
                    text=f"⚠ Bulan belum ada datanya (db-wide): {', '.join(missing)}",
                    font=("Segoe UI", 9, "bold"),
                    bootstyle=DANGER,
                    wraplength=400,
                ).pack(anchor=W)
            else:
                tb.Label(
                    inner,
                    text="Semua bulan yang diharapkan sudah ada datanya.",
                    bootstyle=SUCCESS,
                ).pack(anchor=W)

            n_checked = cov.get("n_idpel_checked", 0)
            n_incomplete = cov.get("n_idpel_incomplete", 0)
            n_efektif = cov.get("n_bulan_efektif", n_bulan)
            style = SUCCESS if n_incomplete == 0 else WARNING
            tb.Label(
                inner,
                text=f"{n_incomplete} dari {n_checked} pelanggan riwayatnya belum "
                     f"lengkap {n_efektif} bulan yang tersedia di database.",
                bootstyle=style,
            ).pack(anchor=W, pady=(4, 0))

            sample = cov.get("sample_incomplete") or []
            if sample:
                sample_txt = ", ".join(f"{idpel} ({n}bln)" for idpel, n in sample[:10])
                tb.Label(
                    inner,
                    text=f"Contoh: {sample_txt}",
                    font=("Segoe UI", 8, "italic"),
                    bootstyle=SECONDARY,
                    wraplength=400,
                ).pack(anchor=W, pady=(2, 0))

        _render_db_summary("Database Rekening", payload.get("rekening"))
        _render_db_summary("Database Stan Baca", payload.get("stanbaca"))

        has_missing = any(
            (cov or {}).get("missing_bulan")
            for cov in (payload.get("rekening"), payload.get("stanbaca"))
        )

        ack_var = tb.BooleanVar(value=False)
        if has_missing:
            tb.Checkbutton(
                frm,
                text="Saya paham database belum lengkap dan tetap ingin melanjutkan"
                     " (hasil analisis bisa keliru untuk bulan yang hilang).",
                variable=ack_var,
                bootstyle="danger",
                command=lambda: proceed_btn.config(
                    state=NORMAL if ack_var.get() else DISABLED
                ),
            ).pack(anchor=W, pady=(4, 0), fill=X)

        btn_frame = tb.Frame(frm)
        btn_frame.pack(fill=X, pady=(8, 0))

        def _proceed():
            self.verify_holder.set(True)
            dialog.destroy()

        def _cancel():
            self.verify_holder.set(False)
            self.stop = True
            dialog.destroy()

        proceed_btn = tb.Button(
            btn_frame, text="Lanjut", command=_proceed, bootstyle=SUCCESS, width=12
        )
        proceed_btn.pack(side=RIGHT, padx=(8, 0))
        if has_missing:
            proceed_btn.config(state=DISABLED)
        tb.Button(
            btn_frame, text="Batal", command=_cancel, bootstyle=SECONDARY, width=12
        ).pack(side=RIGHT)

        dialog.protocol("WM_DELETE_WINDOW", _cancel)

        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")

        dialog.wait_window()

        self.verify_event.set()

    # ── SIMBA LOGIN DIALOG ────────────────────────────────

    def _show_simba_login_dialog(self):
        """Modal dialog untuk input kredensial SIMBA. Blocking sampai user submit/cancel."""

        dialog = tb.Toplevel(self.root)
        dialog.title("Login SIMBA")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        frm = tb.Frame(dialog, padding=20)
        frm.pack(fill=BOTH, expand=True)

        tb.Label(
            frm,
            text="Login SIMBA",
            font=("Segoe UI", 14, "bold"),
            bootstyle=PRIMARY,
        ).grid(row=0, column=0, columnspan=2, sticky=W, pady=(0, 4))

        tb.Label(
            frm,
            text="Masukkan kredensial SIMBA Anda untuk mengambil data foto meter.",
            font=("Segoe UI", 9),
            bootstyle=SECONDARY,
            wraplength=320,
        ).grid(row=1, column=0, columnspan=2, sticky=W, pady=(0, 12))

        tb.Label(frm, text="Username:", font=("Segoe UI", 10)).grid(
            row=2, column=0, sticky=W, pady=4
        )
        username_var = tk.StringVar()
        user_entry = tb.Entry(
            frm, textvariable=username_var, font=("Segoe UI", 10), width=28
        )
        user_entry.grid(row=2, column=1, sticky=EW, pady=4, padx=(8, 0))

        tb.Label(frm, text="Password:", font=("Segoe UI", 10)).grid(
            row=3, column=0, sticky=W, pady=4
        )
        password_var = tk.StringVar()
        pass_entry = tb.Entry(
            frm,
            textvariable=password_var,
            font=("Segoe UI", 10),
            width=28,
            show="•",
        )
        pass_entry.grid(row=3, column=1, sticky=EW, pady=4, padx=(8, 0))

        hint = tb.Label(
            frm,
            text="Format: 12345.namauser (5 digit unitup + nama)",
            font=("Segoe UI", 8, "italic"),
            bootstyle=SECONDARY,
        )
        hint.grid(row=4, column=0, columnspan=2, sticky=W, pady=(2, 12))

        btn_frame = tb.Frame(frm)
        btn_frame.grid(row=5, column=0, columnspan=2, sticky=EW)

        result = {"submitted": False}

        def submit():
            u = username_var.get().strip()
            p = password_var.get()
            if not u or not p:
                messagebox.showwarning(
                    "Peringatan",
                    "Username dan password tidak boleh kosong.",
                    parent=dialog,
                )
                return
            self.credentials_holder.set(u, p)
            result["submitted"] = True
            dialog.destroy()

        def cancel():
            self.credentials_holder.cancel()
            self.stop = True
            dialog.destroy()

        tb.Button(
            btn_frame, text="Login", command=submit, bootstyle=SUCCESS, width=12
        ).pack(side=RIGHT, padx=(8, 0))
        tb.Button(
            btn_frame, text="Cancel", command=cancel, bootstyle=SECONDARY, width=12
        ).pack(side=RIGHT)

        dialog.bind("<Return>", lambda e: submit())
        dialog.bind("<Escape>", lambda e: cancel())
        dialog.protocol("WM_DELETE_WINDOW", cancel)

        # Center dialog on root
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")

        user_entry.focus_set()
        dialog.wait_window()

        # Lepas pipeline thread
        self.login_event.set()

    def _show_db_check_dialog(self, payload):
        """Ringkasan kelengkapan database. Opsi update hanya muncul kalau kurang."""
        self._set_running(False)

        if payload is None:
            self.status_label.config(text="Cek database gagal", bootstyle=DANGER)
            return

        blth = payload.get("blth", "")
        n_bulan = payload.get("n_bulan", 6)
        unitup = payload.get("unitup")

        dialog = tb.Toplevel(self.root)
        dialog.title("Cek Database")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        frm = tb.Frame(dialog, padding=20)
        frm.pack(fill=BOTH, expand=True)

        tb.Label(
            frm,
            text="Kelengkapan Database",
            font=("Segoe UI", 13, "bold"),
            bootstyle=PRIMARY,
        ).pack(anchor=W, pady=(0, 4))

        tb.Label(
            frm,
            text=f"Unit {unitup or '(belum diketahui - login dulu)'} - untuk "
                 f"menganalisis periode {blth}, database wajib punya {n_bulan} "
                 f"bulan sebelumnya. Tiap unit punya databasenya sendiri.",
            font=("Segoe UI", 9),
            bootstyle=SECONDARY,
            wraplength=470,
        ).pack(anchor=W, pady=(0, 12))

        def _render(title, cov):
            box = tb.LabelFrame(frm, text=f"  {title}  ")
            box.pack(fill=X, pady=(0, 10))
            inner = tb.Frame(box, padding=8)
            inner.pack(fill=X)

            if cov is None:
                tb.Label(
                    inner, text="Fitur ini tidak diaktifkan.", bootstyle=SECONDARY
                ).pack(anchor=W)
                return

            if not cov.get("available"):
                tb.Label(
                    inner,
                    text="Database tidak ditemukan / kosong - semua bulan perlu diunduh.",
                    bootstyle=DANGER,
                ).pack(anchor=W)

            missing = cov.get("missing_bulan") or []
            if missing:
                tb.Label(
                    inner,
                    text=f"⚠ Belum ada datanya: {', '.join(missing)}",
                    font=("Segoe UI", 9, "bold"),
                    bootstyle=DANGER,
                    wraplength=450,
                ).pack(anchor=W)
            elif cov.get("available"):
                tb.Label(
                    inner,
                    text=f"✓ Lengkap {n_bulan} bulan.",
                    bootstyle=SUCCESS,
                ).pack(anchor=W)

            # Jumlah baris per bulan: check_coverage menganggap sebuah bulan
            # "ada" walau isinya cuma satu baris, jadi bulan yang tarikannya
            # gagal separuh cuma kelihatan dari angka ini.
            jumlah = cov.get("jumlah_per_bulan") or {}
            if jumlah:
                teks = "   ".join(f"{b}: {n:,}" for b, n in jumlah.items())
                tb.Label(
                    inner,
                    text=f"Baris per bulan - {teks}",
                    font=("Segoe UI", 8),
                    bootstyle=SECONDARY,
                    wraplength=450,
                    justify=LEFT,
                ).pack(anchor=W, pady=(4, 0))

        _render("Database Rekening", payload.get("rekening"))
        _render("Database Stan Baca", payload.get("stanbaca"))

        kurang_rek = list((payload.get("rekening") or {}).get("missing_bulan") or [])
        kurang_sb = list((payload.get("stanbaca") or {}).get("missing_bulan") or [])
        ada_kurang = bool(kurang_rek or kurang_sb)

        if ada_kurang:
            # Dirinci per database: satu bulan rekening dan satu bulan stan
            # baca ditarik dari sistem yang berbeda, jadi angka gabungan malah
            # menyesatkan.
            rincian = []
            if kurang_rek:
                rincian.append(f"{len(kurang_rek)} bulan rekening (portal billing)")
            if kurang_sb:
                rincian.append(f"{len(kurang_sb)} bulan stan baca (SIMBA)")
            tb.Label(
                frm,
                text="Tekan Update Database untuk mengunduh " + " dan ".join(rincian)
                     + ". Anda akan diminta login ke sistem yang bersangkutan.",
                font=("Segoe UI", 9),
                bootstyle=WARNING,
                wraplength=470,
            ).pack(anchor=W, pady=(0, 8))

        btn_frame = tb.Frame(frm)
        btn_frame.pack(fill=X, pady=(4, 0))

        def _tutup():
            dialog.destroy()

        def _update():
            dialog.destroy()
            self._start_db_update(kurang_rek, kurang_sb)

        tb.Button(
            btn_frame, text="Tutup", command=_tutup, bootstyle=SECONDARY, width=12
        ).pack(side=RIGHT)

        if ada_kurang:
            tb.Button(
                btn_frame,
                text="⬇  Update Database",
                command=_update,
                bootstyle=SUCCESS,
                width=20,
            ).pack(side=RIGHT, padx=(0, 8))
            self.status_label.config(text="Database belum lengkap", bootstyle=WARNING)
        else:
            self.status_label.config(text="Database lengkap ✓", bootstyle=SUCCESS)

        dialog.protocol("WM_DELETE_WINDOW", _tutup)

        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")

        dialog.wait_window()

    # ── LOGIN PORTAL BILLING DIALOG ───────────────────────

    def _show_billing_login_dialog(self):
        """Dialog kredensial portal billing. Blocking sampai user submit/cancel."""

        dialog = tb.Toplevel(self.root)
        dialog.title("Login Portal Billing")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        frm = tb.Frame(dialog, padding=20)
        frm.pack(fill=BOTH, expand=True)

        tb.Label(
            frm,
            text="Login Portal Billing",
            font=("Segoe UI", 13, "bold"),
            bootstyle=PRIMARY,
        ).pack(anchor=W, pady=(0, 4))

        tb.Label(
            frm,
            text="Dipakai untuk mengunduh database rekening "
                 "(Monitoring Billing Detail).",
            font=("Segoe UI", 9),
            bootstyle=SECONDARY,
            wraplength=430,
        ).pack(anchor=W, pady=(0, 12))

        tb.Label(frm, text="Username (NIP)", font=("Segoe UI", 9)).pack(anchor=W)
        username_var = tk.StringVar()
        user_entry = tb.Entry(frm, textvariable=username_var, width=44)
        user_entry.pack(fill=X, pady=(2, 2))
        tb.Label(
            frm,
            text="NIP portal billing, mis. 9716018H2Y - beda dari username SIMBA.",
            font=("Segoe UI", 8, "italic"),
            bootstyle=SECONDARY,
        ).pack(anchor=W, pady=(0, 8))

        tb.Label(frm, text="Password", font=("Segoe UI", 9)).pack(anchor=W)
        password_var = tk.StringVar()
        pass_entry = tb.Entry(frm, textvariable=password_var, show="•", width=44)
        pass_entry.pack(fill=X, pady=(2, 8))

        kode_head = tb.Frame(frm)
        kode_head.pack(fill=X)
        tb.Label(kode_head, text="Kode Enkripsi", font=("Segoe UI", 9)).pack(side=LEFT)

        # Entry, bukan Text: widget Text tidak punya opsi `show`, jadi isinya
        # tidak bisa disamarkan. Kodenya panjang (±500 karakter) sehingga
        # kotaknya menggulir mendatar - itu wajar dan tidak mengganggu karena
        # isinya di-paste, bukan diketik.
        kode_var = tk.StringVar()
        kode_entry = tb.Entry(frm, textvariable=kode_var, show="*", width=44)
        kode_entry.pack(fill=X, pady=(2, 2))

        def _tempel():
            try:
                isi = self.root.clipboard_get()
            except tk.TclError:
                return
            kode_var.set(isi.strip())

        tb.Button(
            kode_head, text="Tempel", command=_tempel, bootstyle=(INFO, OUTLINE), width=9
        ).pack(side=RIGHT)

        tb.Label(
            frm,
            text="Tempel kode dari generator Anda. Kode ini dibuat ulang setiap "
                 "kali login, jadi tidak disimpan aplikasi.",
            font=("Segoe UI", 8, "italic"),
            bootstyle=SECONDARY,
            wraplength=430,
            justify=LEFT,
        ).pack(anchor=W, pady=(0, 12))

        result = {"submitted": False}

        def submit():
            u = username_var.get().strip()
            p = password_var.get()
            k = kode_var.get().strip()
            if not u or not p:
                messagebox.showwarning(
                    "Peringatan",
                    "Username dan password tidak boleh kosong.",
                    parent=dialog,
                )
                return
            if not k:
                messagebox.showwarning(
                    "Peringatan", "Kode enkripsi tidak boleh kosong.", parent=dialog
                )
                return
            self.billing_credentials_holder.set(u, p, k)
            result["submitted"] = True
            dialog.destroy()

        def cancel():
            self.billing_credentials_holder.cancel()
            self.stop = True
            dialog.destroy()

        btn_frame = tb.Frame(frm)
        btn_frame.pack(fill=X)
        tb.Button(
            btn_frame, text="Login", command=submit, bootstyle=SUCCESS, width=12
        ).pack(side=RIGHT, padx=(8, 0))
        tb.Button(
            btn_frame, text="Batal", command=cancel, bootstyle=SECONDARY, width=12
        ).pack(side=RIGHT)

        dialog.bind("<Escape>", lambda e: cancel())
        dialog.protocol("WM_DELETE_WINDOW", cancel)

        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")
        user_entry.focus_set()

        dialog.wait_window()

        # Lepas thread pipeline
        self.billing_login_event.set()

    def _show_kd_proses_dialog(self):
        """Dialog centang Kd Proses. Return list kode, atau None kalau batal."""
        setelan = settings.load_unduh_settings()

        dialog = tb.Toplevel(self.root)
        dialog.title("Pilih Kd Proses")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        frm = tb.Frame(dialog, padding=20)
        frm.pack(fill=BOTH, expand=True)

        tb.Label(
            frm, text="Kd Proses Kelompok", font=("Segoe UI", 13, "bold"),
            bootstyle=PRIMARY,
        ).pack(anchor=W, pady=(0, 4))

        tb.Label(
            frm,
            text="Pilih kelompok proses yang mau diunduh. Pilihan ini dipakai "
                 "untuk export DLPD maupun DPM.",
            font=("Segoe UI", 9), bootstyle=SECONDARY, wraplength=420,
        ).pack(anchor=W, pady=(0, 10))

        kotak = tb.LabelFrame(frm, text="  Kode  ")
        kotak.pack(fill=X, pady=(0, 10))
        grid = tb.Frame(kotak, padding=8)
        grid.pack(fill=X)

        dipilih = set(setelan["kd_proses_dipilih"])
        vars_kode = {}
        for i, kode in enumerate(setelan["kd_proses_tersedia"]):
            var = tk.BooleanVar(value=kode in dipilih)
            vars_kode[kode] = var
            tb.Checkbutton(grid, text=kode, variable=var, bootstyle="success-round-toggle").grid(
                row=i // 4, column=i % 4, sticky=W, padx=6, pady=3
            )

        tb.Label(
            frm, text="Daftar kode yang tersedia (pisahkan dengan koma)",
            font=("Segoe UI", 9),
        ).pack(anchor=W)
        tersedia_var = tk.StringVar(value=", ".join(setelan["kd_proses_tersedia"]))
        tb.Entry(frm, textvariable=tersedia_var, width=52).pack(fill=X, pady=(2, 2))
        tb.Label(
            frm,
            text="Kode disimpan tanpa awalan unit. Awalannya (mis. 44BIM) "
                 "ditempel otomatis dari unit tempat Anda login, jadi setelan "
                 "ini tetap benar di unit mana pun.",
            font=("Segoe UI", 8, "italic"), bootstyle=SECONDARY,
            wraplength=420, justify=LEFT,
        ).pack(anchor=W, pady=(0, 12))

        hasil = {"kode": None}

        def _simpan_daftar():
            """Terapkan daftar kode yang diketik, bangun ulang centangnya."""
            baru = [k.strip().upper() for k in tersedia_var.get().split(",") if k.strip()]
            if not baru:
                messagebox.showwarning(
                    "Peringatan", "Daftar kode tidak boleh kosong.", parent=dialog
                )
                return
            setelan["kd_proses_tersedia"] = baru
            setelan["kd_proses_dipilih"] = [
                k for k, v in vars_kode.items() if v.get() and k in baru
            ]
            settings.save_unduh_settings(setelan)
            dialog.destroy()
            # Buka ulang supaya centangnya mengikuti daftar yang baru.
            hasil["kode"] = self._show_kd_proses_dialog()

        def _ok():
            kode = [k for k, v in vars_kode.items() if v.get()]
            if not kode:
                messagebox.showwarning(
                    "Peringatan", "Pilih minimal satu Kd Proses.", parent=dialog
                )
                return
            setelan["kd_proses_tersedia"] = [
                k.strip().upper() for k in tersedia_var.get().split(",") if k.strip()
            ] or setelan["kd_proses_tersedia"]
            setelan["kd_proses_dipilih"] = kode
            settings.save_unduh_settings(setelan)
            hasil["kode"] = kode
            dialog.destroy()

        def _batal():
            hasil["kode"] = None
            dialog.destroy()

        btn = tb.Frame(frm)
        btn.pack(fill=X)
        tb.Button(btn, text="Terapkan Daftar", command=_simpan_daftar,
                  bootstyle=(INFO, OUTLINE), width=16).pack(side=LEFT)
        tb.Button(btn, text="Unduh", command=_ok, bootstyle=SUCCESS,
                  width=12).pack(side=RIGHT, padx=(8, 0))
        tb.Button(btn, text="Batal", command=_batal, bootstyle=SECONDARY,
                  width=12).pack(side=RIGHT)

        dialog.bind("<Escape>", lambda e: _batal())
        dialog.protocol("WM_DELETE_WINDOW", _batal)

        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")

        dialog.wait_window()
        return hasil["kode"]

    # ── TENTANG ───────────────────────────────────────────

    def _show_about_dialog(self):
        dialog = tb.Toplevel(self.root)
        dialog.title("Tentang")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        frm = tb.Frame(dialog, padding=24)
        frm.pack(fill=BOTH, expand=True)

        tb.Label(
            frm, text="⚡ " + APP_NAMA, font=("Segoe UI", 15, "bold"),
            bootstyle=PRIMARY,
        ).pack(anchor=CENTER)

        tb.Label(
            frm, text=f"Versi {APP_VERSI}",
            font=("Segoe UI", 9), bootstyle=SECONDARY,
        ).pack(anchor=CENTER, pady=(2, 14))

        tb.Label(
            frm,
            text="Deteksi anomali pemakaian listrik dari data DLPD:\n"
                 "analisa stand & pemakaian, cek stan baca, validasi\n"
                 "cabut/pasang, verifikasi foto meter, dan usulan koreksi.",
            font=("Segoe UI", 9), justify=CENTER,
        ).pack(anchor=CENTER, pady=(0, 16))

        tb.Separator(frm).pack(fill=X, pady=(0, 12))

        tb.Label(
            frm, text=f"Dibuat di {APP_TEMPAT}, {APP_TAHUN}",
            font=("Segoe UI", 10), justify=CENTER,
        ).pack(anchor=CENTER)
        tb.Label(
            frm, text=APP_PEMBUAT, font=("Segoe UI", 12, "bold"),
            bootstyle=INFO, justify=CENTER,
        ).pack(anchor=CENTER, pady=(2, 16))

        tb.Button(frm, text="Tutup", command=dialog.destroy,
                  bootstyle=SECONDARY, width=12).pack(anchor=CENTER)

        dialog.bind("<Escape>", lambda e: dialog.destroy())

        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")

        dialog.wait_window()
