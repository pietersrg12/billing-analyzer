"""PLN Billing Analyzer - entry point.

Setup runtime environment (folder data user, log error global) lalu
launch GUI Tkinter.
"""

import os
import sys
import traceback
from datetime import datetime

from config import (
    APP_DATA_DIR,
    DB_BACKUP_DIR,
    FOTO_DIR,
    HASIL_DIR,
    UNDUHAN_DIR,
    resource_path,
)


def _ensure_user_dirs():
    """Buat folder writable per user kalau belum ada."""
    for d in (APP_DATA_DIR, FOTO_DIR, HASIL_DIR, UNDUHAN_DIR, DB_BACKUP_DIR):
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

    if "--selftest" in sys.argv:
        sys.exit(_selftest(sys.argv[1:]))

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


def _selftest(argv):
    """Uji mandiri isi bundle: pastikan dependency & resource benar-benar jalan.

    Pakai:
        PLN-Billing.exe --selftest [--dpm FILE.xlsx] [--blth 202606] [--foto FILE.jpg]

    Tanpa --dpm hanya cek import, model, dan database. Dengan --dpm, pipeline
    dijalankan penuh tanpa menyentuh SIMBA sampai file Excel benar-benar jadi.

    Hasil ditulis ke selftest.log di APP_DATA_DIR: .exe di-build tanpa console,
    jadi stdout tidak kelihatan saat dijalankan user.
    """
    from config import BUNDLE_DIR, MODEL_PATH, db_path, stanbaca_db_path

    # Pakai resolver, bukan konstanta bundled: setelah update database
    # otomatis, file yang benar-benar dibaca pipeline adalah .xlsx milik
    # user - itulah yang perlu diverifikasi selftest.
    DB_FILE = db_path()
    STAN_BACA_DB_FILE = stanbaca_db_path()

    baris = []
    gagal = []

    def tulis(msg):
        baris.append(msg)
        print(msg)

    def cek(nama, fn):
        try:
            tulis(f"  PASS  {nama}: {fn()}")
        except Exception as e:
            gagal.append(nama)
            tulis(f"  GAGAL {nama}: {type(e).__name__}: {e}")
            baris.append(traceback.format_exc())

    def arg(nama):
        if nama in argv:
            i = argv.index(nama)
            if i + 1 < len(argv):
                return argv[i + 1]
        return None

    dpm = arg("--dpm")
    blth_arg = arg("--blth")
    foto = arg("--foto")

    tulis(f"=== SELFTEST {datetime.now().isoformat()} ===")
    tulis(f"frozen      : {getattr(sys, 'frozen', False)}")
    tulis(f"python      : {sys.version.split()[0]}")
    tulis(f"BUNDLE_DIR  : {BUNDLE_DIR}")
    tulis(f"APP_DATA_DIR: {APP_DATA_DIR}")

    tulis("--- dependency ---")

    def versi(nama):
        return getattr(__import__(nama), "__version__", "terimport (tanpa __version__)")

    for nama in ("numpy", "pandas", "openpyxl", "pyxlsb", "requests",
                 "PIL", "cv2", "torch", "ultralytics"):
        cek(nama, lambda n=nama: versi(n))

    tulis("--- resource ---")

    def ukuran(p):
        if not os.path.exists(p):
            raise FileNotFoundError(p)
        return f"{os.path.getsize(p):,} byte"

    for nama, path in ((os.path.basename(DB_FILE), DB_FILE),
                       (os.path.basename(STAN_BACA_DB_FILE), STAN_BACA_DB_FILE),
                       ("model/best.pt", MODEL_PATH)):
        cek(nama, lambda p=path: ukuran(p))

    def baca_db():
        # Engine mengikuti ekstensi: .xlsb butuh pyxlsb, .xlsx hasil update
        # dibaca openpyxl.
        from core.loader import _read_excel_auto
        df = _read_excel_auto(DB_FILE).head(5)
        return f"terbaca, kolom={list(df.columns)}"

    cek(f"baca {os.path.basename(DB_FILE)}", baca_db)

    tulis("--- model YOLO ---")

    def klasifikasi():
        from core.classifier import classify_all, is_available
        if not is_available(MODEL_PATH):
            raise RuntimeError("classifier tidak tersedia (ultralytics atau model hilang)")
        if foto and not os.path.exists(foto):
            raise FileNotFoundError(f"--foto tidak ditemukan: {foto}")
        if not foto:
            return "model tersedia (inferensi dilewati: --foto tidak diberikan)"
        import core.classifier as clf
        hasil = classify_all({"TEST": foto}, MODEL_PATH)
        label = hasil.get("TEST")
        if label not in ("kwh_meter", "bukan_kwh"):
            raise RuntimeError(f"label tidak wajar: {label!r}\n{clf.load_error()}")
        return f"inferensi {os.path.basename(foto)} -> {label}"

    cek("classifier best.pt", klasifikasi)

    tulis("--- pipeline ---")

    if not dpm:
        tulis("  SKIP  pipeline penuh (--dpm tidak diberikan)")
    else:
        def pipeline_penuh():
            from core import pipeline as pl
            from core.loader import read_blth

            if not os.path.exists(dpm):
                raise FileNotFoundError(f"--dpm tidak ditemukan: {dpm}")
            blth = blth_arg or read_blth(dpm)
            if not blth:
                raise RuntimeError(
                    f"BLTH tidak terbaca dari {dpm} (kolom thblrek); pakai --blth"
                )
            # Selftest tidak boleh menyentuh SIMBA: butuh kredensial & jaringan.
            pl.ENABLE_PHOTO_DOWNLOAD = False

            keluaran = []

            def cb(event):
                if event[0] == "log":
                    pesan = str(event[1])
                    baris.append(f"        {pesan}")
                    if pesan.startswith("SELESAI ->"):
                        keluaran.append(pesan.split("->", 1)[1].strip())

            pl.run_pipeline(dpm, blth, progress_callback=cb)

            if not keluaran:
                raise RuntimeError("pipeline tidak melaporkan file keluaran")
            if not os.path.exists(keluaran[0]):
                raise RuntimeError(f"file Excel tidak terbentuk: {keluaran[0]}")
            return f"blth={blth}, {keluaran[0]} ({os.path.getsize(keluaran[0]):,} byte)"

        cek("pipeline penuh -> Excel", pipeline_penuh)

    tulis("=== SEMUA LOLOS ===" if not gagal else f"=== GAGAL: {', '.join(gagal)} ===")

    log_path = os.path.join(APP_DATA_DIR, "selftest.log")
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("\n".join(baris) + "\n")
    except OSError:
        pass

    return 1 if gagal else 0


if __name__ == "__main__":
    main()
