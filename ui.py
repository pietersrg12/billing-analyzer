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
from core.pipeline import run_pipeline
from core import settings
from config import THEME_DARK, THEME_LIGHT


class CredentialsHolder:
    """Thread-safe holder untuk passing kredensial dari UI thread ke pipeline thread."""

    def __init__(self):
        self._lock = threading.Lock()
        self._creds = None

    def set(self, username, password):
        with self._lock:
            self._creds = {"username": username, "password": password}

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
