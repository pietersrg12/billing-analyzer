# -*- coding: utf-8 -*-
"""
Pembuat gambar pendukung untuk PPT karya inovasi SIMBA.

Jalankan:  python -u presentasi/siapkan_gambar.py
           python -u presentasi/siapkan_gambar.py --ulang   (bangun ulang xlsx)

Hasil:     presentasi/gambar/*.png

Skrip ini TERPISAH dari buat_ppt.py supaya pembuatan slide tetap ringan dan
bisa diulang tanpa membuka Excel atau menjalankan aplikasi. buat_ppt.py hanya
menyisipkan PNG yang ada; kalau belum dibuat, slide tetap jadi dengan kotak
penampung.

Empat kelompok gambar, masing-masing berdiri sendiri - yang gagal dilaporkan,
yang lain tetap jalan:
  1. berkas contoh hasil Excel (aturan terbaru, foto dari cache)
  2. tangkapan lembar CABUT_PASANG / KOREKSI_STAND / baris berfoto
  3. tangkapan jendela aplikasi + dialog Pengaturan Rule
  4. contoh foto kWh meter vs bukan meter

TIDAK menyentuh jaringan SIMBA sama sekali - semua foto diambil dari cache
foto/{BLTH}/{IDPEL}.jpg hasil proses sebelumnya.

PENTING: langkah 2 menolak jalan kalau Excel sedang terbuka. Excel cenderung
memakai satu proses untuk semua workbook, jadi otomasi COM akan menumpang di
sesi yang sedang Anda pakai - mengubah tampilannya dan berisiko menggantung.
Tutup Excel dulu, lalu jalankan ulang.
"""

import os
import queue
import subprocess
import sys
import threading
import time
import traceback

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

GAMBAR_DIR = os.path.join(SRC, "presentasi", "gambar")
CONTOH_XLSX = os.path.join(GAMBAR_DIR, "_contoh_hasil.xlsx")

DPM = os.path.join(SRC, "dpm", "2608", "t total blm final.xlsx")
BLTH = "202608"

ULANG = "--ulang" in sys.argv
# Foto meter memuat pita informasi (nama pelanggan + koordinat GPS) di bawah.
# Bawaannya ditampilkan utuh; --potong-overlay memotong pita itu.
POTONG = "--potong-overlay" in sys.argv
hasil_log = []


def catat(nama, ok, ket=""):
    hasil_log.append((nama, ok, ket))
    print(("  [v] " if ok else "  [x] ") + nama + (" - " + ket if ket else ""),
          flush=True)


def ps(skrip, timeout=900):
    p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                        "-Command", skrip],
                       capture_output=True, text=True, timeout=timeout)
    return ((p.stdout or "") + (p.stderr or ""))


# --------------------------------------------------------------- 1. berkas contoh

def buat_contoh_excel():
    """Bangun berkas hasil kecil dengan aturan yang berlaku sekarang.

    Berkas di hasil/202608/ dibuat sebelum perbaikan cabut/pasang dan sebelum
    rule set sekarang, jadi angkanya tidak cocok dengan slide.
    """
    import pandas as pd
    from core import loader, analyzer, cabut_pasang, koreksi, excel, classifier
    from core.photo import build_bulan_list
    from core.settings import load_rules
    import config

    cfg = load_rules()
    dpm, db = loader.load_data(DPM, config.DB_FILE)
    df = analyzer.prepare(dpm, db, cfg)
    df = analyzer.apply_analysis(df, cfg)

    stanbaca = loader.load_stanbaca_data(config.STAN_BACA_DB_FILE)
    if stanbaca is not None:
        df = analyzer.compute_stanbaca_comparison(df, stanbaca, BLTH, cfg)

    df = cabut_pasang.compute_cabut_pasang(df, cfg)

    # Cuplikan: SEMUA baris cabut/pasang bermasalah + beberapa per status.
    masalah = df["ADA_CABUT_PASANG"].fillna(False) & (df["MASALAH_CABUT_PASANG"] != "")
    ambil = [df[masalah]]
    for status, grup in df[~masalah].groupby("STATUS"):
        n = 4 if status in ("Normal", "DATA BARU") else 10
        ambil.append(grup.sort_values("JAM_NYALA", ascending=False).head(n))
    kecil = pd.concat(ambil).drop_duplicates(subset="IDPEL").copy()
    kecil["IDPEL"] = kecil["IDPEL"].astype(str)

    # Foto diambil dari cache di disk, bukan dari SIMBA.
    bulan_list = build_bulan_list(BLTH, config.JUMLAH_BULAN_FOTO)
    results = {}
    for idpel in kecil["IDPEL"]:
        per_bulan = {}
        for i, bl in enumerate(bulan_list, 1):
            p = os.path.join(config.FOTO_DIR, bl, f"{idpel}.jpg")
            if os.path.exists(p):
                per_bulan[i] = p
        if per_bulan:
            results[idpel] = per_bulan

    klasifikasi = {}
    if classifier.is_available(config.MODEL_PATH):
        terbaru = {i: r[1] for i, r in results.items() if 1 in r}
        klasifikasi = classifier.classify_all(terbaru, config.MODEL_PATH) or {}

    kecil = koreksi.tambah_saran_koreksi(kecil, cfg, klasifikasi=klasifikasi)

    os.makedirs(GAMBAR_DIR, exist_ok=True)
    sheet_map = excel.export_excel(kecil, CONTOH_XLSX, bulan_list,
                                   klasifikasi=klasifikasi)
    excel.format_excel(CONTOH_XLSX, sheet_map, results, bulan_list, cfg=cfg)

    mb = os.path.getsize(CONTOH_XLSX) / 1024 / 1024
    return f"{len(kecil)} baris, {len(results)} pelanggan berfoto, {mb:.1f} MB"


# --------------------------------------------------- 2. tangkapan lembar Excel

# Tangkapan jendela, bukan CopyPicture/Chart.Export: cara clipboard itu
# menggantung kalau Excel dijalankan tanpa jendela.
PS_TANGKAP = r'''
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public class W {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out R r);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)]
    public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc f, IntPtr p);
  public delegate bool EnumProc(IntPtr h, IntPtr p);
  public struct R { public int L, T, Rt, B; }

  // Telusuri SEMUA jendela tingkat atas. FindWindow ternyata tidak menemukan
  // jendela Tk maupun Toplevel dialognya, jadi dicocokkan sendiri di sini.
  public static List<string> Judul() {
    var hasil = new List<string>();
    EnumWindows(delegate(IntPtr h, IntPtr p) {
      if (!IsWindowVisible(h)) return true;
      var sb = new StringBuilder(512);
      GetWindowTextW(h, sb, 512);
      if (sb.Length > 0) hasil.Add(h.ToInt64() + "|" + sb.ToString());
      return true;
    }, IntPtr.Zero);
    return hasil;
  }
}
"@
function Cari([string]$judul) {
  foreach ($baris in [W]::Judul()) {
    $i = $baris.IndexOf("|")
    if ($baris.Substring($i + 1) -eq $judul) { return [IntPtr][int64]$baris.Substring(0, $i) }
  }
  foreach ($baris in [W]::Judul()) {          # cadangan: cocok sebagian
    $i = $baris.IndexOf("|")
    if ($baris.Substring($i + 1) -like "*$judul*") { return [IntPtr][int64]$baris.Substring(0, $i) }
  }
  return [IntPtr]::Zero
}
function DaftarJudul() {
  return (([W]::Judul() | ForEach-Object { $_.Substring($_.IndexOf("|") + 1) }) -join " / ")
}
function Tangkap([IntPtr]$h, [string]$out) {
  if ($h -eq [IntPtr]::Zero) { return "jendela tidak ketemu. Yang terlihat: " + (DaftarJudul) }
  [void][W]::ShowWindow($h, 9)          # SW_RESTORE
  [void][W]::BringWindowToTop($h)
  [void][W]::SetForegroundWindow($h)
  Start-Sleep -Milliseconds 900
  $r = New-Object W+R
  [void][W]::GetWindowRect($h, [ref]$r)
  $w = $r.Rt - $r.L; $ht = $r.B - $r.T
  if ($w -le 10 -or $ht -le 10) { return "ukuran jendela tidak wajar ($w x $ht)" }
  $bmp = New-Object System.Drawing.Bitmap $w, $ht
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.CopyFromScreen($r.L, $r.T, 0, 0, $bmp.Size)
  $bmp.Save($out, [System.Drawing.Imaging.ImageFormat]::Png)
  $g.Dispose(); $bmp.Dispose()
  return $null
}
'''

PS_EXCEL = PS_TANGKAP + r'''
$ErrorActionPreference = "Stop"
$xl = $null; $wb = $null
try {
  $xl = New-Object -ComObject Excel.Application
  $xl.Visible = $true
  $xl.DisplayAlerts = $false
  $wb = $xl.Workbooks.Open("__XLSX__", $false, $true)
  $xl.WindowState = -4137            # xlMaximized
  $xl.DisplayFormulaBar = $false
  $xl.DisplayStatusBar = $false
  $xl.DisplayFullScreen = $true      # sembunyikan ribbon
  Start-Sleep -Milliseconds 1800
  $h = [IntPtr][int64]$xl.Hwnd

  function Simpan($sheetName, $rangeA1, $out) {
    $ws = $null
    foreach ($s in $wb.Worksheets) { if ($s.Name -eq $sheetName) { $ws = $s } }
    if (-not $ws) { Write-Output "LEWAT|$out|lembar '$sheetName' tidak ada"; return }
    $ws.Activate()
    $xl.ActiveWindow.DisplayGridlines = $false
    $xl.ActiveWindow.DisplayHeadings = $false
    [void]$ws.Range($rangeA1).Select()
    $xl.ActiveWindow.Zoom = $true     # zoom pas ke rentang terpilih
    $xl.ActiveWindow.ScrollRow = 1
    $xl.ActiveWindow.ScrollColumn = 1
    [void]$ws.Range("A1").Select()
    Start-Sleep -Milliseconds 1200
    $err = Tangkap $h $out
    if ($err) { Write-Output "LEWAT|$out|$err" } else { Write-Output "OK|$out" }
  }

__PANGGILAN__

} catch {
  Write-Output ("ERROR|" + $_.Exception.Message)
} finally {
  try { if ($xl) { $xl.DisplayFullScreen = $false; $xl.DisplayFormulaBar = $true } } catch {}
  if ($wb) { $wb.Close($false); [void][Runtime.InteropServices.Marshal]::ReleaseComObject($wb) }
  if ($xl) { $xl.Quit(); [void][Runtime.InteropServices.Marshal]::ReleaseComObject($xl) }
  [GC]::Collect(); [GC]::WaitForPendingFinalizers()
}
'''


def excel_sedang_terbuka():
    keluaran = ps('(Get-Process EXCEL -ErrorAction SilentlyContinue | '
                  'Measure-Object).Count', timeout=60)
    try:
        return int(keluaran.strip().splitlines()[-1]) > 0
    except (ValueError, IndexError):
        return False


def tangkap_lembar_excel(permintaan):
    """permintaan: list of (nama_sheet, rentang_A1, nama_file_png)."""
    if excel_sedang_terbuka():
        catat("tangkapan lembar Excel", False,
              "Excel sedang terbuka - tutup dulu semua jendela Excel, "
              "lalu jalankan ulang skrip ini")
        return
    panggilan = "\n".join(
        '  Simpan "{}" "{}" "{}"'.format(
            s, r, os.path.join(GAMBAR_DIR, f).replace("\\", "\\\\"))
        for s, r, f in permintaan)
    skrip = (PS_EXCEL
             .replace("__XLSX__", CONTOH_XLSX.replace("\\", "\\\\"))
             .replace("__PANGGILAN__", panggilan))
    keluaran = ps(skrip)
    terlihat = False
    for baris in keluaran.splitlines():
        baris = baris.strip()
        if baris.startswith("OK|"):
            catat("excel: " + os.path.basename(baris.split("|")[1]), True)
            terlihat = True
        elif baris.startswith("LEWAT|"):
            _, f, ket = baris.split("|", 2)
            catat("excel: " + os.path.basename(f), False, ket)
            terlihat = True
        elif baris.startswith("ERROR|"):
            catat("excel (COM)", False, baris.split("|", 1)[1][:200])
            terlihat = True
    if not terlihat:
        catat("tangkapan lembar Excel", False,
              "tidak ada keluaran: " + keluaran.strip()[:200])


# ------------------------------------------------- 3. tangkapan jendela aplikasi

# Penanda dijadwalkan lewat root.after lalu mainloop - TIDAK boleh memanggil
# _show_rule_settings_dialog() secara berurutan, karena dialog itu diakhiri
# wait_window() yang memblokir sampai dialognya ditutup.
KODE_UI = r'''
import sys
sys.path.insert(0, r"__SRC__")
import ttkbootstrap as tb
from ui import App, HAS_DND

if HAS_DND:
    from tkinterdnd2 import TkinterDnD
    root = TkinterDnD.Tk()
    tb.Style(theme="darkly")
else:
    root = tb.Window(title="PLN Billing Analyzer", themename="darkly")
root.title("PLN Billing Analyzer")

app = App(root)
app.path_var.set(r"__DPM__")
app.year_cb.set("2026")
app.month_cb.set("08")

for pesan in [
    "LOAD DATA",
    "Database stan baca dimuat (124887 baris)",
    "PREPARE",
    "ANALYZE",
    "Cabut/pasang meter: 57 pelanggan, 19 stand bermasalah",
    "AMBIL DATA & FOTO DARI SIMBA (2247 pelanggan non-Normal)",
    "  [INFO] 2247/2247 (100%), ETA 0s",
    "  [DOWNLOAD] 1180/2247 ok=1174 fail=6 (52%), ETA 74s",
]:
    app._add_log(pesan)

app._update_steps(52)
app.progress_bar["value"] = 52
app.percent_label.config(text="52%")
app.status_label.config(text="Mengunduh foto meter...")
app.eta_label.config(text="ETA: 01:14")
app._set_running(True)

def tandai(t):
    print(t, flush=True)

root.after(1600, lambda: tandai("SIAP-UTAMA"))
root.after(11000, lambda: tandai("BUKA-DIALOG"))
root.after(11300, app._show_rule_settings_dialog)
root.mainloop()
'''


def potong_progres(sumber):
    """Potong panel Progress + Log jadi gambar melebar.

    Jendela aplikasinya tegak, jadi kalau dipasang utuh di slide yang ruang
    tingginya sempit hasilnya mengecil sampai tidak terbaca. Panel progres dan
    log saja sudah bercerita, dan bentuknya melebar - pas untuk slide alur.
    """
    from PIL import Image
    im = Image.open(sumber)
    w, h = im.size
    potong = im.crop((int(w * 0.02), int(h * 0.32),
                      int(w * 0.98), int(h * 0.90)))
    tujuan = os.path.join(GAMBAR_DIR, "app_progres.png")
    potong.save(tujuan, "PNG")
    catat("aplikasi: app_progres.png", True,
          f"potongan panel progres {potong.width}x{potong.height}")


def _pembaca(pipa, q):
    for baris in iter(pipa.readline, ""):
        q.put(baris.strip())
    q.put(None)


def _tunggu(q, penanda, batas=60):
    """Tunggu penanda muncul; None = proses mati, "" = kehabisan waktu."""
    tenggat = time.time() + batas
    while time.time() < tenggat:
        try:
            baris = q.get(timeout=1)
        except queue.Empty:
            continue
        if baris is None:
            return None
        if penanda in baris:
            return baris
    return ""


def tangkap_aplikasi():
    import tempfile
    kode = KODE_UI.replace("__SRC__", SRC).replace("__DPM__", DPM)
    fd, jalur = tempfile.mkstemp(suffix="_shot_ui.py", text=True)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(kode)

    proc = subprocess.Popen([sys.executable, "-u", jalur], cwd=SRC,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True)
    q = queue.Queue()
    threading.Thread(target=_pembaca, args=(proc.stdout, q), daemon=True).start()
    try:
        for penanda, berkas, judul, jeda in (
            ("SIAP-UTAMA", "app_utama.png", "PLN Billing Analyzer", 0),
            ("BUKA-DIALOG", "app_pengaturan.png",
             "Pengaturan Rule Deteksi Anomali", 2.5),
        ):
            hasil = _tunggu(q, penanda)
            if hasil is None:
                catat("aplikasi: " + berkas, False, "proses UI berhenti dini")
                break
            if hasil == "":
                catat("aplikasi: " + berkas, False,
                      "penanda " + penanda + " tidak muncul")
                continue
            if jeda:
                time.sleep(jeda)
            out = os.path.join(GAMBAR_DIR, berkas)
            skrip = PS_TANGKAP + (
                '\n$h = Cari "%s"\n'
                '$e = Tangkap $h "%s"\n'
                'if ($e) { Write-Output "GAGAL|$e" } else { Write-Output "OK" }\n'
                % (judul, out.replace("\\", "\\\\")))
            keluaran = ps(skrip, timeout=120).strip()
            ok = keluaran.splitlines()[-1].strip() == "OK" if keluaran else False
            catat("aplikasi: " + berkas, ok, "" if ok else keluaran[:160])
            if ok and berkas == "app_utama.png":
                potong_progres(out)
    finally:
        # Dialog Pengaturan memblokir mainloop, jadi prosesnya memang harus
        # dihentikan dari luar - bukan ditunggu selesai sendiri.
        try:
            proc.kill()
            proc.wait(timeout=20)
        except Exception:
            pass
        try:
            os.remove(jalur)
        except OSError:
            pass


# ------------------------------------------------------- 4. contoh foto meter

def contoh_foto_meter(maks=300):
    """Cari satu foto kWh meter dan satu foto yang bukan, lewat classifier."""
    from core import classifier
    from PIL import Image
    import config

    if not classifier.is_available(config.MODEL_PATH):
        raise RuntimeError("ultralytics atau model/best.pt tidak tersedia")

    folder = os.path.join(config.FOTO_DIR, BLTH)
    berkas = sorted(f for f in os.listdir(folder) if f.lower().endswith(".jpg"))
    contoh = {os.path.splitext(f)[0]: os.path.join(folder, f)
              for f in berkas[:maks]}
    label = classifier.classify_all(contoh, config.MODEL_PATH) or {}

    diambil = {}
    for idpel, lab in label.items():
        if lab in ("kwh_meter", "bukan_kwh") and lab not in diambil:
            diambil[lab] = contoh[idpel]
        if len(diambil) == 2:
            break

    for lab, sumber in diambil.items():
        im = Image.open(sumber).convert("RGB")
        if POTONG:
            # Pita informasi di bawah foto memuat nama pelanggan dan koordinat
            # GPS rumahnya. Dipotong hanya kalau diminta lewat --potong-overlay;
            # bawaannya foto ditampilkan utuh sesuai pilihan pemakai.
            im = im.crop((0, 0, im.width, int(im.height * 0.78)))
        im.thumbnail((900, 900))
        im.save(os.path.join(GAMBAR_DIR, f"foto_{lab}.png"), "PNG")

    kurang = {"kwh_meter", "bukan_kwh"} - set(diambil)
    if kurang:
        raise RuntimeError("tidak ketemu contoh untuk: " + ", ".join(kurang)
                           + f" (dari {len(contoh)} foto diperiksa)")
    n = sum(1 for v in label.values() if v == "bukan_kwh")
    return f"diperiksa {len(contoh)} foto, {n} berlabel bukan_kwh"


# ------------------------------------------------------------------- jalankan

def main():
    os.makedirs(GAMBAR_DIR, exist_ok=True)

    print("\n[1/4] Berkas contoh hasil (aturan terbaru)...", flush=True)
    contoh_ada = os.path.exists(CONTOH_XLSX)
    if contoh_ada and not ULANG:
        catat("_contoh_hasil.xlsx", True, "sudah ada, dipakai ulang "
              "(pakai --ulang untuk membangun lagi)")
    else:
        try:
            catat("_contoh_hasil.xlsx", True, buat_contoh_excel())
            contoh_ada = True
        except Exception as e:
            catat("_contoh_hasil.xlsx", False, f"{type(e).__name__}: {e}")
            traceback.print_exc()

    print("\n[2/4] Tangkapan lembar Excel...", flush=True)
    if contoh_ada:
        tangkap_lembar_excel([
            ("CABUT_PASANG", "A1:P12", "excel_cabut_pasang.png"),
            ("KOREKSI_STAND", "A1:M14", "excel_koreksi_stand.png"),
            ("Stand Minus", "A1:H6", "excel_baris_foto.png"),
        ])
    else:
        catat("tangkapan lembar Excel", False, "berkas contoh tidak ada")

    print("\n[3/4] Tangkapan jendela aplikasi...", flush=True)
    try:
        tangkap_aplikasi()
    except Exception as e:
        catat("tangkapan aplikasi", False, f"{type(e).__name__}: {e}")
        traceback.print_exc()

    print("\n[4/4] Contoh foto meter...", flush=True)
    try:
        catat("foto_kwh_meter.png + foto_bukan_kwh.png", True,
              contoh_foto_meter())
    except Exception as e:
        catat("contoh foto meter", False, f"{type(e).__name__}: {e}")

    gagal = [n for n, ok, _ in hasil_log if not ok]
    print("\n" + "=" * 64, flush=True)
    print(f"Berhasil {len(hasil_log) - len(gagal)}/{len(hasil_log)}."
          f"  Gambar: {GAMBAR_DIR}", flush=True)
    if gagal:
        print("Gagal: " + ", ".join(gagal), flush=True)
        print("Yang gagal tampil sebagai kotak penampung di slide.", flush=True)
    print("=" * 64, flush=True)


if __name__ == "__main__":
    main()
