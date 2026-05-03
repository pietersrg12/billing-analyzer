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

from core.pipeline import run_pipeline
from config import THEME_DARK, THEME_LIGHT


STEPS = ["Load", "Prepare", "Analyze", "Download", "Export"]

STEP_THRESHOLDS = [0, 10, 20, 25, 85]


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

    def _browse(self):
        path = filedialog.askopenfilename(
            filetypes=[
                ("Excel files", "*.xlsx *.xls *.xlsb *.xlsm"),
                ("All files", "*.*"),
            ]
        )
        if path:
            self.path_var.set(path)

    def _on_drop(self, event):
        path = event.data.strip("{}")
        if os.path.isfile(path):
            self.path_var.set(path)

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
            )
        except Exception as e:
            self.queue.put(("log", f"ERROR: {e}"))
            self.queue.put(("error", str(e)))

        self.queue.put(("done", None))

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

                elif kind == "login_wait":
                    self.status_label.config(text="Menunggu login...", bootstyle=WARNING)
                    messagebox.showinfo(
                        "Login Diperlukan",
                        "Browser Chrome telah dibuka.\n\n"
                        "1. Login ke portal PLN\n"
                        "2. Selesaikan captcha\n"
                        "3. Klik OK setelah selesai login",
                    )
                    self.login_event.set()

                elif kind == "error":
                    if self.current_step >= 0:
                        self._set_step_state(self.current_step, "error")

                elif kind == "done":
                    self._set_running(False)
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
