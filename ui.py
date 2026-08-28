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


STEPS = ["Load", "Prepare", "Analyze", "Download", "Export"]

STEP_THRESHOLDS = [0, 10, 20, 22, 85]

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


class App:

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
                text="💡 Drop file DPM ke area ini",
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

        self.year_var = tk.StringVar()
        self.year_cb = tb.Combobox(
            period_frame,
            textvariable=self.year_var,
            values=[str(i) for i in range(2020, 2031)],
            width=8,
            state="readonly",
            bootstyle=INFO,
        )
        self.year_cb.pack(side=LEFT, padx=(0, 4))
        self.year_cb.set("2025")

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
        self.month_cb.set("01")

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

    def _show_db_check_dialog(self, payload):
        """Ringkasan kelengkapan database. Opsi update hanya muncul kalau kurang."""
        self._set_running(False)

        if payload is None:
            self.status_label.config(text="Cek database gagal", bootstyle=DANGER)
            return

        blth = payload.get("blth", "")
        n_bulan = payload.get("n_bulan", 6)

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
            text=f"Untuk menganalisis periode {blth}, database wajib punya "
                 f"{n_bulan} bulan sebelumnya.",
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

        kode_text = tk.Text(frm, height=4, width=44, wrap="char", font=("Consolas", 8))
        kode_text.pack(fill=X, pady=(2, 2))

        def _tempel():
            try:
                isi = self.root.clipboard_get()
            except tk.TclError:
                return
            kode_text.delete("1.0", "end")
            kode_text.insert("1.0", isi.strip())

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
            k = kode_text.get("1.0", "end").strip()
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
