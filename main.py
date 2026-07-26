"""PLN Billing Analyzer - entry point.

Setup runtime environment (folder data user, log error global) lalu
launch GUI Tkinter.
"""

import os
import sys
import traceback
from datetime import datetime

from config import APP_DATA_DIR, FOTO_DIR, HASIL_DIR, resource_path


def _ensure_user_dirs():
    """Buat folder writable per user kalau belum ada."""
    for d in (APP_DATA_DIR, FOTO_DIR, HASIL_DIR):
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass


def _install_global_excepthook():
    """Tulis traceback uncaught exception ke error.log di APP_DATA_DIR.

    Penting saat running di .exe (no console) supaya user bisa kirim
    log file kalau crash.
    """
    log_path = os.path.join(APP_DATA_DIR, "error.log")

    def _hook(exc_type, exc_value, exc_tb):
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n=== {datetime.now().isoformat()} ===\n")
                traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
        except OSError:
            pass
        # Tetap panggil default handler kalau ada console
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _hook


def _set_window_icon(root):
    """Set icon window. Toleran kalau file tidak ada."""
    try:
        ico = resource_path("assets", "icon.ico")
        if os.path.exists(ico):
            root.iconbitmap(default=ico)
    except Exception:
        pass


def main():
    _ensure_user_dirs()
    _install_global_excepthook()

    import ttkbootstrap as tb
    from ui import App, HAS_DND

    if HAS_DND:
        from tkinterdnd2 import TkinterDnD
        root = TkinterDnD.Tk()
        tb.Style(theme="darkly")
    else:
        root = tb.Window(title="PLN Billing Analyzer", themename="darkly")

    root.title("PLN Billing Analyzer")
    _set_window_icon(root)
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
