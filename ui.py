import os
import queue
import threading
from datetime import datetime
from tkinter import filedialog, messagebox
import tkinter as tk

import ttkbootstrap as tb
from ttkbootstrap.constants import *
from ttkbootstrap.scrolled import ScrolledText

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except ImportError:
    HAS_DND = False

from core.loader import read_blth
from core.pipeline import (
    run_db_check,
    run_db_update,
    run_pipeline,
    run_unduh_dlpd,
)
from core import settings
from ui_dialogs import DialogMixin
from config import (
    APP_NAMA,
    APP_PEMBUAT,
    APP_TAHUN,
    APP_TEMPAT,
    APP_VERSI,
    ENABLE_DB_DOWNLOAD,
    ENABLE_UNDUH_DLPD,
    THEME_DARK,
    THEME_LIGHT,
)


class CredentialsHolder:
    """Thread-safe holder untuk passing kredensial dari UI thread ke pipeline thread."""

    def __init__(self):
        self._lock = threading.Lock()
        self._creds = None

    def set(self, username, password, token_info=None):
        """`token_info` hanya dipakai portal billing (kode enkripsi yang
        di-paste user). Pemanggil SIMBA tetap cukup dua argumen."""
        with self._lock:
            self._creds = {
                "username": username,
                "password": password,
                "token_info": token_info,
            }

    def cancel(self):
        with self._lock:
            self._creds = None

    def get(self):
        with self._lock:
            return self._creds


class VerificationResultHolder:
    """Thread-safe holder untuk keputusan lanjut/batal dari dialog verifikasi."""

    def __init__(self):
        self._lock = threading.Lock()
        self._proceed = None

    def set(self, proceed):
        with self._lock:
            self._proceed = proceed

    def get(self):
        with self._lock:
            return bool(self._proceed)


# Siklus billing: baca meter dilakukan di akhir bulan (median tanggal 26) dan
# hasilnya menagih rekening bulan BERIKUTNYA. Jadi sejak tanggal 20 ke atas,
# periode yang sedang dikerjakan orang billing sudah bulan depan - itulah yang
# dipakai sebagai tebakan awal combobox periode.
TANGGAL_GANTI_PERIODE = 20

# Batas bawah pilihan tahun. Tetap, karena file DPM lama masih boleh dibuka;
# batas atasnya yang ikut berjalan (lihat daftar_tahun).
TAHUN_AWAL = 2020


def daftar_tahun(hari_ini=None):
    """Pilihan tahun untuk combobox: TAHUN_AWAL s.d. tahun berjalan + 1.

    Dihitung, bukan didaftar tetap, supaya tidak pernah mentok - daftar yang
    dipaku akan diam-diam kedaluwarsa dan memaksa user memilih tahun yang
    salah. Batas atasnya +1 karena periode_default() melompat ke Januari tahun
    berikutnya sejak 20 Desember; tanpa itu, tebakannya sendiri tidak akan ada
    di daftar.
    """
    now = hari_ini or datetime.now()
    return [str(t) for t in range(TAHUN_AWAL, now.year + 2)]


def periode_default(hari_ini=None):
    """Tebakan periode (tahun, bulan) berdasarkan tanggal hari ini.

    Tanggal 1-19  -> bulan berjalan.
    Tanggal 20-31 -> bulan berikutnya (ikut pergantian tahun di Desember).

    Cuma nilai awal combobox; user tetap bisa menggantinya, dan memilih file
    DPM akan menimpanya dengan thblrek dari file itu (lihat _autofill_blth).
    """
    now = hari_ini or datetime.now()
    tahun, bulan = now.year, now.month
    if now.day >= TANGGAL_GANTI_PERIODE:
        bulan += 1
        if bulan > 12:
            bulan = 1
            tahun += 1
    return str(tahun), f"{bulan:02d}"


STEPS = ["Load", "Prepare", "Analyze", "Download", "Export"]

STEP_THRESHOLDS = [0, 10, 20, 22, 85]


class App(DialogMixin):

    def __init__(self, root):
        self.root = root
        self.root.title("PLN Billing Analyzer")
        self.root.minsize(720, 680)
        self.root.resizable(True, True)

        self.queue = queue.Queue()
        self.stop = False
        self.running = False
        self.is_dark = True
        self.current_step = -1
        self.login_event = threading.Event()
        self.credentials_holder = CredentialsHolder()
        self.verify_event = threading.Event()
        self.verify_holder = VerificationResultHolder()
        # Portal billing punya jalur login sendiri: host, token, dan skema
        # kredensialnya beda dari SIMBA, jadi tidak bisa berbagi event.
        self.billing_login_event = threading.Event()
        self.billing_credentials_holder = CredentialsHolder()

        self._build_header()
        self._build_input_section()
        self._build_progress_section()
        self._build_action_buttons()
        self._build_log_section()

        self.root.after(100, self._process_queue)

    # ── HEADER ────────────────────────────────────────────

    def _build_header(self):
        header = tb.Frame(self.root, bootstyle=PRIMARY)
        header.pack(fill=X, padx=0, pady=0)

        inner = tb.Frame(header)
        inner.pack(fill=X, padx=15, pady=10)

        title = tb.Label(
            inner,
            text="⚡ PLN Billing Analyzer",
            font=("Segoe UI", 18, "bold"),
            bootstyle=(INVERSE, PRIMARY),
        )
        title.pack(side=LEFT)

        btn_frame = tb.Frame(inner)
        btn_frame.pack(side=RIGHT)

        self.theme_btn = tb.Button(
            btn_frame,
            text="☀ Light",
            bootstyle=WARNING,
            command=self._toggle_theme,
            width=10,
        )
        self.theme_btn.pack(side=RIGHT, padx=(5, 0))

        self.rule_settings_btn = tb.Button(
            btn_frame,
            text="⚙ Pengaturan Rule",
            bootstyle=(INFO, OUTLINE),
            command=self._show_rule_settings_dialog,
            width=18,
        )
        self.rule_settings_btn.pack(side=RIGHT, padx=(5, 0))

        self.about_btn = tb.Button(
            btn_frame,
            text="ℹ",
            bootstyle=(SECONDARY, OUTLINE),
            command=self._show_about_dialog,
            width=3,
        )
        self.about_btn.pack(side=RIGHT, padx=(5, 0))

        if ENABLE_DB_DOWNLOAD:
            self.db_check_btn = tb.Button(
                btn_frame,
                text="🗄 Cek Database",
                bootstyle=(SUCCESS, OUTLINE),
                command=self._check_database,
                width=16,
            )
            self.db_check_btn.pack(side=RIGHT, padx=(5, 0))
        else:
            self.db_check_btn = None

    def _toggle_theme(self):
        style = tb.Style()
        if self.is_dark:
            style.theme_use(THEME_LIGHT)
            self.theme_btn.config(text="🌙 Dark", bootstyle=SECONDARY)
        else:
            style.theme_use(THEME_DARK)
            self.theme_btn.config(text="☀ Light", bootstyle=WARNING)
        self.is_dark = not self.is_dark

    # ── INPUT SECTION ─────────────────────────────────────

    def _build_input_section(self):
        frame = tb.LabelFrame(self.root, text="  Input Data  ")
        frame.pack(fill=X, padx=15, pady=(15, 5), ipadx=10, ipady=8)

        # Row 1: File path
        file_frame = tb.Frame(frame)
        file_frame.pack(fill=X, pady=(0, 8))

        tb.Label(file_frame, text="File DPM:", font=("Segoe UI", 10)).pack(
            side=LEFT, padx=(0, 8)
        )

        self.path_var = tk.StringVar()
        self.path_entry = tb.Entry(
            file_frame, textvariable=self.path_var, font=("Segoe UI", 10)
        )
        self.path_entry.pack(side=LEFT, fill=X, expand=True, padx=(0, 8))

        self.browse_btn = tb.Button(
            file_frame,
            text="Browse...",
            command=self._browse,
            bootstyle=SECONDARY,
            width=12,
        )
        self.browse_btn.pack(side=RIGHT)

        if ENABLE_UNDUH_DLPD:
            self.unduh_dlpd_btn = tb.Button(
                file_frame,
                text="⬇  Unduh DLPD",
                command=self._unduh_dlpd,
                bootstyle=INFO,
                width=15,
            )
            self.unduh_dlpd_btn.pack(side=RIGHT, padx=(0, 8))
        else:
            self.unduh_dlpd_btn = None

        # Drag & drop hint
        if HAS_DND:
            self.drop_label = tb.Label(
                frame,
                text="💡 Unduh atau drop file DPM ke area ini",
                font=("Segoe UI", 9, "italic"),
                bootstyle=SECONDARY,
            )
            self.drop_label.pack(pady=(0, 8))
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind("<<Drop>>", self._on_drop)

        # Row 2: Periode
        period_frame = tb.Frame(frame)
        period_frame.pack(fill=X)

        tb.Label(period_frame, text="Periode:", font=("Segoe UI", 10)).pack(
            side=LEFT, padx=(0, 8)
        )

        sekarang = datetime.now()

        self.year_var = tk.StringVar()
        self.year_cb = tb.Combobox(
            period_frame,
            textvariable=self.year_var,
            values=daftar_tahun(sekarang),
            width=8,
            state="readonly",
            bootstyle=INFO,
        )
        self.year_cb.pack(side=LEFT, padx=(0, 4))

        tb.Label(period_frame, text="-", font=("Segoe UI", 10)).pack(
            side=LEFT, padx=(0, 4)
        )

        self.month_var = tk.StringVar()
        self.month_cb = tb.Combobox(
            period_frame,
            textvariable=self.month_var,
            values=[f"{i:02d}" for i in range(1, 13)],
            width=5,
            state="readonly",
            bootstyle=INFO,
        )
        self.month_cb.pack(side=LEFT)

        # `sekarang` yang sama dipakai daftar_tahun() di atas, jadi tebakannya
        # dijamin ada di daftar - tidak perlu jalur cadangan.
        tahun_awal, bulan_awal = periode_default(sekarang)
        self.year_cb.set(tahun_awal)
        self.month_cb.set(bulan_awal)

    def _autofill_blth(self, path):
        """Baca thblrek dari file DPM, auto-fill combobox tahun & bulan."""
        try:
            blth = read_blth(path)
        except Exception:
            blth = None
        if not blth or len(blth) != 6 or not blth.isdigit():
            return
        year, month = blth[:4], blth[4:]
        if year in self.year_cb["values"]:
            self.year_cb.set(year)
        if month in self.month_cb["values"]:
            self.month_cb.set(month)

    def _browse(self):
        path = filedialog.askopenfilename(
            filetypes=[
                ("Excel files", "*.xlsx *.xls *.xlsb *.xlsm"),
                ("All files", "*.*"),
            ]
        )
        if path:
            self.path_var.set(path)
            self._autofill_blth(path)

    def _on_drop(self, event):
        path = event.data.strip("{}")
        if os.path.isfile(path):
            self.path_var.set(path)
            self._autofill_blth(path)

    # ── PROGRESS SECTION ──────────────────────────────────

    def _build_progress_section(self):
        frame = tb.LabelFrame(self.root, text="  Progress  ")
        frame.pack(fill=X, padx=15, pady=5, ipadx=10, ipady=8)

        # Step indicators
        steps_frame = tb.Frame(frame)
        steps_frame.pack(fill=X, pady=(0, 12))

        self.step_indicators = []
        self.step_labels = []
        self.step_connectors = []

        for i, step in enumerate(STEPS):
            if i > 0:
                connector = tb.Label(
                    steps_frame, text="─────", font=("Segoe UI", 10), bootstyle=SECONDARY
                )
                connector.pack(side=LEFT, padx=2)
                self.step_connectors.append(connector)

            indicator_frame = tb.Frame(steps_frame)
            indicator_frame.pack(side=LEFT, padx=2)

            indicator = tb.Label(
                indicator_frame,
                text="○",
                font=("Segoe UI", 16),
                bootstyle=SECONDARY,
            )
            indicator.pack()

            label = tb.Label(
                indicator_frame,
                text=step,
                font=("Segoe UI", 9),
                bootstyle=SECONDARY,
            )
            label.pack()

            self.step_indicators.append(indicator)
            self.step_labels.append(label)

        # Progress bar
        bar_frame = tb.Frame(frame)
        bar_frame.pack(fill=X, pady=(0, 5))

        self.progress_bar = tb.Progressbar(
            bar_frame, mode=DETERMINATE, length=500, bootstyle=SUCCESS
        )
        self.progress_bar.pack(side=LEFT, fill=X, expand=True, padx=(0, 8))

        self.percent_label = tb.Label(
            bar_frame, text="0%", font=("Segoe UI", 10, "bold"), width=6
        )
        self.percent_label.pack(side=RIGHT)

        # Status + ETA
        info_frame = tb.Frame(frame)
        info_frame.pack(fill=X)

        self.status_label = tb.Label(
            info_frame, text="Siap", font=("Segoe UI", 10), bootstyle=INFO
        )
        self.status_label.pack(side=LEFT)

        self.eta_label = tb.Label(
            info_frame, text="", font=("Segoe UI", 10), bootstyle=SECONDARY
        )
        self.eta_label.pack(side=RIGHT)

    def _update_steps(self, percent):
        for i, threshold in enumerate(STEP_THRESHOLDS):
            if i < len(STEP_THRESHOLDS) - 1:
                if percent >= STEP_THRESHOLDS[i + 1]:
                    self._set_step_state(i, "done")
                    self.current_step = i
                elif percent >= threshold:
                    self._set_step_state(i, "active")
                    self.current_step = i
                    break
            else:
                if percent >= 100:
                    self._set_step_state(i, "done")
                elif percent >= threshold:
                    self._set_step_state(i, "active")
                    self.current_step = i

    def _set_step_state(self, index, state):
        indicator = self.step_indicators[index]
        label = self.step_labels[index]

        if state == "done":
            indicator.config(text="✓", bootstyle=SUCCESS)
            label.config(bootstyle=SUCCESS)
            if index < len(self.step_connectors):
                self.step_connectors[index].config(bootstyle=SUCCESS)
        elif state == "active":
            indicator.config(text="●", bootstyle=INFO)
            label.config(bootstyle=INFO)
        elif state == "error":
            indicator.config(text="✗", bootstyle=DANGER)
            label.config(bootstyle=DANGER)

    def _reset_steps(self):
        for i in range(len(STEPS)):
            self.step_indicators[i].config(text="○", bootstyle=SECONDARY)
            self.step_labels[i].config(bootstyle=SECONDARY)
        for conn in self.step_connectors:
            conn.config(bootstyle=SECONDARY)
        self.current_step = -1

    # ── ACTION BUTTONS ────────────────────────────────────

    def _build_action_buttons(self):
        frame = tb.Frame(self.root)
        frame.pack(fill=X, padx=15, pady=10)

        self.run_btn = tb.Button(
            frame,
            text="▶  Jalankan",
            command=self._run,
            bootstyle=SUCCESS,
            width=20,
        )
        self.run_btn.pack(side=LEFT, padx=(0, 8))

        self.cancel_btn = tb.Button(
            frame,
            text="■  Cancel",
            command=self._cancel,
            bootstyle=DANGER,
            width=15,
            state=DISABLED,
        )
        self.cancel_btn.pack(side=LEFT)

    def _set_running(self, running):
        self.running = running
        state_run = DISABLED if running else NORMAL
        state_cancel = NORMAL if running else DISABLED

        self.run_btn.config(state=state_run)
        self.cancel_btn.config(state=state_cancel)
        self.browse_btn.config(state=state_run)
        self.year_cb.config(state="disabled" if running else "readonly")
        self.month_cb.config(state="disabled" if running else "readonly")
        self.path_entry.config(state="disabled" if running else NORMAL)
        if getattr(self, "db_check_btn", None) is not None:
            self.db_check_btn.config(state=state_run)
        if getattr(self, "unduh_dlpd_btn", None) is not None:
            self.unduh_dlpd_btn.config(state=state_run)

    # ── LOG SECTION ───────────────────────────────────────

    def _build_log_section(self):
        frame = tb.LabelFrame(self.root, text="  Log Aktivitas  ")
        frame.pack(fill=BOTH, expand=True, padx=15, pady=(5, 15), ipadx=8, ipady=8)

        self.log_text = ScrolledText(
            frame, height=12, autohide=True, font=("Consolas", 9)
        )
        self.log_text.pack(fill=BOTH, expand=True)

        # Configure tags for colored output
        text_widget = self.log_text.text
        text_widget.tag_configure("error", foreground="#e74c3c")
        text_widget.tag_configure("success", foreground="#2ecc71")
        text_widget.tag_configure("info", foreground="#3498db")
        text_widget.tag_configure("timestamp", foreground="#95a5a6")

        btn_frame = tb.Frame(frame)
        btn_frame.pack(fill=X, pady=(8, 0))

        tb.Button(
            btn_frame, text="Clear Log", command=self._clear_log, bootstyle=SECONDARY, width=10
        ).pack(side=LEFT, padx=(0, 5))

        tb.Button(
            btn_frame, text="Copy Log", command=self._copy_log, bootstyle=SECONDARY, width=10
        ).pack(side=LEFT)

    def _add_log(self, message, level="info"):
        text_widget = self.log_text.text
        timestamp = datetime.now().strftime("%H:%M:%S")

        text_widget.config(state=NORMAL)
        text_widget.insert(END, f"[{timestamp}] ", "timestamp")

        tag = level
        text_widget.insert(END, f"{message}\n", tag)
        text_widget.see(END)
        text_widget.config(state=DISABLED)

    def _clear_log(self):
        text_widget = self.log_text.text
        text_widget.config(state=NORMAL)
        text_widget.delete("1.0", END)
        text_widget.config(state=DISABLED)

    def _copy_log(self):
        text_widget = self.log_text.text
        content = text_widget.get("1.0", END).strip()
        if content:
            self.root.clipboard_clear()
            self.root.clipboard_append(content)

    # ── PIPELINE EXECUTION ────────────────────────────────

    def _cancel(self):
        self.stop = True
        self._add_log("Cancel requested...", "error")

    def _run(self):
        path = self.path_var.get().strip()
        if not path or not os.path.isfile(path):
            messagebox.showwarning("Peringatan", "Pilih file DPM terlebih dahulu.")
            return

        year = self.year_var.get()
        month = self.month_var.get()
        if not year or not month:
            messagebox.showwarning("Peringatan", "Pilih tahun dan bulan.")
            return

        blth = year + month
        self.stop = False
        self.login_event.clear()
        self.credentials_holder.cancel()
        self.verify_event.clear()
        self.verify_holder.set(None)
        self._error_occurred = False
        self._set_running(True)
        self._reset_steps()
        self.progress_bar["value"] = 0
        self.percent_label.config(text="0%")
        self.status_label.config(text="Memulai...", bootstyle=INFO)
        self.eta_label.config(text="")

        t = threading.Thread(
            target=self._run_thread, args=(path, blth), daemon=True
        )
        t.start()

    def _run_thread(self, dpm_path, blth):
        try:
            run_pipeline(
                dpm_path,
                blth,
                progress_callback=self.queue.put,
                stop_flag=lambda: self.stop,
                login_event=self.login_event,
                credentials_holder=self.credentials_holder,
                verify_event=self.verify_event,
                verify_holder=self.verify_holder,
            )
        except Exception as e:
            self.queue.put(("log", f"ERROR: {e}"))
            self.queue.put(("error", str(e)))

        self.queue.put(("done", None))


    # ── CEK & UPDATE DATABASE ─────────────────────────────

    def _check_database(self):
        """Cek kelengkapan database untuk periode yang dipilih."""
        if self.running:
            return

        year = self.year_var.get()
        month = self.month_var.get()
        if not year or not month:
            messagebox.showwarning(
                "Peringatan", "Pilih tahun dan bulan dulu sebelum cek database."
            )
            return

        blth = year + month
        self._set_running(True)
        self.status_label.config(text="Mengecek database...", bootstyle=INFO)
        self._add_log(f"Cek kelengkapan database untuk periode {blth}", "info")

        t = threading.Thread(target=self._check_db_thread, args=(blth,), daemon=True)
        t.start()

    def _check_db_thread(self, blth):
        # Membaca database ratusan ribu baris makan beberapa detik - jangan
        # sampai membekukan Tk. Hasilnya dikembalikan lewat queue seperti
        # semua pesan pipeline lain.
        try:
            hasil = run_db_check(blth, progress_callback=self.queue.put)
            self.queue.put(("db_check_result", hasil))
        except Exception as e:
            self.queue.put(("log", f"ERROR cek database: {e}"))
            self.queue.put(("db_check_result", None))


    def _start_db_update(self, bulan_rekening, bulan_stanbaca):
        self.stop = False
        self.billing_login_event.clear()
        self.billing_credentials_holder.cancel()
        self.login_event.clear()
        self.credentials_holder.cancel()
        self._error_occurred = False
        self._set_running(True)
        self.progress_bar["value"] = 0
        self.percent_label.config(text="0%")
        self.status_label.config(text="Update database...", bootstyle=INFO)
        self.eta_label.config(text="")

        t = threading.Thread(
            target=self._db_update_thread,
            args=(bulan_rekening, bulan_stanbaca),
            daemon=True,
        )
        t.start()

    def _db_update_thread(self, bulan_rekening, bulan_stanbaca):
        # Sengaja TIDAK memakai pesan "done": handler-nya memunculkan
        # "Proses analisa selesai!" yang keliru untuk pekerjaan unduh.
        try:
            hasil = run_db_update(
                bulan_rekening,
                bulan_stanbaca,
                progress_callback=self.queue.put,
                stop_flag=lambda: self.stop,
                login_event=self.login_event,
                credentials_holder=self.credentials_holder,
                billing_login_event=self.billing_login_event,
                billing_credentials_holder=self.billing_credentials_holder,
            )
            self.queue.put(("db_update_done", hasil))
        except Exception as e:
            self.queue.put(("log", f"ERROR update database: {e}"))
            self.queue.put(("db_update_done", None))

    def _finish_db_update(self, hasil):
        self._set_running(False)
        self.eta_label.config(text="")

        if hasil is None:
            self.status_label.config(text="Update database gagal", bootstyle=DANGER)
            self.progress_bar["value"] = 0
            self.percent_label.config(text="0%")
            return

        baris = []
        for judul, kunci in (("Rekening", "rekening"), ("Stan baca", "stanbaca")):
            stat = hasil.get(kunci)
            if stat:
                baris.append(
                    f"{judul}: {stat['n_total']:,} baris "
                    f"(+{stat['n_baru']:,} baru)\n{stat['path']}"
                )

        if not baris:
            self.status_label.config(text="Update dibatalkan", bootstyle=WARNING)
            return

        self.progress_bar["value"] = 100
        self.percent_label.config(text="100%")
        self.status_label.config(text="Database diperbarui ✓", bootstyle=SUCCESS)
        messagebox.showinfo("Update Database Selesai", "\n\n".join(baris))


    # ── UNDUH FILE DLPD ───────────────────────────────────

    def _unduh_dlpd(self):
        """Buka dialog pilihan Kd Proses lalu unduh file input DLPD."""
        if self.running:
            return

        year = self.year_var.get()
        month = self.month_var.get()
        if not year or not month:
            messagebox.showwarning(
                "Peringatan", "Pilih tahun dan bulan dulu sebelum unduh DLPD."
            )
            return

        kd_proses = self._show_kd_proses_dialog()
        if not kd_proses:
            return

        blth = year + month
        self.stop = False
        self.billing_login_event.clear()
        self.billing_credentials_holder.cancel()
        self._error_occurred = False
        self._set_running(True)
        self.progress_bar["value"] = 0
        self.percent_label.config(text="0%")
        self.status_label.config(text="Unduh file DLPD...", bootstyle=INFO)
        self.eta_label.config(text="")

        t = threading.Thread(
            target=self._unduh_dlpd_thread, args=(blth, kd_proses), daemon=True
        )
        t.start()

    def _unduh_dlpd_thread(self, blth, kd_proses):
        # Pesan sendiri, bukan "done": handler "done" memunculkan
        # "Proses analisa selesai!" yang keliru untuk pekerjaan unduh.
        try:
            stat = run_unduh_dlpd(
                blth,
                kd_proses,
                progress_callback=self.queue.put,
                stop_flag=lambda: self.stop,
                billing_login_event=self.billing_login_event,
                billing_credentials_holder=self.billing_credentials_holder,
            )
            self.queue.put(("unduh_dlpd_done", stat))
        except Exception as e:
            self.queue.put(("log", f"ERROR unduh DLPD: {e}"))
            self.queue.put(("unduh_dlpd_done", None))

    def _finish_unduh_dlpd(self, stat):
        self._set_running(False)
        self.eta_label.config(text="")

        if stat is None:
            self.status_label.config(text="Unduh DLPD gagal/dibatalkan", bootstyle=DANGER)
            self.progress_bar["value"] = 0
            self.percent_label.config(text="0%")
            return

        # Isi sendiri kolom File DPM - inti fitur ini memang menghapus langkah
        # pilih-file manual yang rawan salah file/salah periode.
        self.path_var.set(stat["path"])

        self.progress_bar["value"] = 100
        self.percent_label.config(text="100%")
        self.status_label.config(text="File DLPD siap ✓", bootstyle=SUCCESS)

        pesan = [
            f"File tersimpan:\n{stat['path']}",
            f"Baris DLPD   : {stat['n_dlpd']:,}",
            f"Dapat kelainan_bc_meter: {stat['n_cocok']:,}",
        ]
        if stat["n_tak_cocok"]:
            pesan.append(
                f"Tanpa pasangan di DPM: {stat['n_tak_cocok']:,}\n"
                f"(keterangan_dlpd-nya dibiarkan apa adanya)"
            )
        pesan.append("Kolom File DPM sudah terisi - tinggal tekan Jalankan.")
        messagebox.showinfo("Unduh DLPD Selesai", "\n\n".join(pesan))


    # ── QUEUE PROCESSING ──────────────────────────────────

    def _process_queue(self):
        try:
            while True:
                msg = self.queue.get_nowait()
                kind = msg[0]
                data = msg[1]

                if kind == "log":
                    level = "error" if "ERROR" in data or "error" in data.lower() else "info"
                    if "✔" in data or "SELESAI" in data:
                        level = "success"
                    self._add_log(data, level)
                    self.status_label.config(text=data[:50], bootstyle=INFO)

                elif kind == "percent":
                    p = data
                    self.progress_bar["value"] = p
                    self.percent_label.config(text=f"{p:.0f}%")
                    self._update_steps(p)

                elif kind == "eta":
                    if isinstance(data, (int, float)):
                        mins, secs = divmod(int(data), 60)
                        self.eta_label.config(text=f"ETA: {mins:02d}:{secs:02d}")
                    else:
                        self.eta_label.config(text=f"ETA: {data}")

                elif kind == "simba_login_required":
                    self.status_label.config(text="Menunggu login SIMBA...", bootstyle=WARNING)
                    self._show_simba_login_dialog()

                elif kind == "billing_login_required":
                    self.status_label.config(
                        text="Menunggu login portal billing...", bootstyle=WARNING
                    )
                    self._show_billing_login_dialog()

                elif kind == "db_check_result":
                    self._show_db_check_dialog(data)

                elif kind == "db_update_done":
                    self._finish_db_update(data)

                elif kind == "unduh_dlpd_done":
                    self._finish_unduh_dlpd(data)

                elif kind == "verification_required":
                    self.status_label.config(text="Menunggu verifikasi database...", bootstyle=WARNING)
                    self._show_verification_dialog(data)

                elif kind == "error":
                    if self.current_step >= 0:
                        self._set_step_state(self.current_step, "error")
                    self._error_occurred = True

                elif kind == "done":
                    self._set_running(False)
                    if getattr(self, "_error_occurred", False):
                        self.status_label.config(text="Selesai dengan error", bootstyle=DANGER)
                        self.eta_label.config(text="")
                        self._error_occurred = False
                    else:
                        self.progress_bar["value"] = 100
                        self.percent_label.config(text="100%")
                        self.status_label.config(text="Selesai ✓", bootstyle=SUCCESS)
                        self.eta_label.config(text="")
                        for i in range(len(STEPS)):
                            self._set_step_state(i, "done")
                        messagebox.showinfo("Selesai", "Proses analisa selesai!")

        except queue.Empty:
            pass

        self.root.after(100, self._process_queue)
