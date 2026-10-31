"""
Bungkus dataset + skrip training jadi satu ZIP untuk dibawa ke komputer GPU
lewat flashdisk (komputer GPU tidak bisa mengakses folder ini).

Satu ZIP tanpa kompresi: ribuan file kecil menyalin sangat lambat ke
flashdisk, satu file besar jauh lebih cepat. JPEG memang tidak bisa
dikompres lagi, jadi ZIP_STORED tidak membuang ruang.

Isi paket:
  dataset/            images/, labels/, dataset.yaml (tanpa path absolut)
  digit_detector.pt   titik awal fine-tune + pembanding "lama" (--awal)
  display_detector.pt, reader.py, evaluasi_ocr.py
  test/               foto asli pelanggan test (tidak dipakai training) + test.csv
  latih_ocr.py        skrip training
  latih.bat           klik dua kali: training lalu evaluasi lama vs baru
  BACA_SAYA.txt       langkah di komputer GPU

    python tools/ml/buat_paket_gpu.py --awal ml_data/digit_v6/weights/best.pt --nama digit_v7
"""
import argparse
import os
import zipfile

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
YOLO_DIR = os.path.join(ROOT, "ml_data", "ocr_v1", "yolo")
OUT = os.path.join(ROOT, "ml_data", "paket_gpu_ocr.zip")

LATIH_BAT = r"""@echo off
cd /d "%~dp0"
python -c "import torch; print('GPU:', torch.cuda.is_available() and torch.cuda.get_device_name(0))"
python latih_ocr.py --data dataset\dataset.yaml --nama {nama} %*
if errorlevel 1 (echo Training gagal. & pause & exit /b 1)
python evaluasi_ocr.py --baru dataset\runs\{nama}\weights\best.pt
echo.
echo Selesai. Salin SELURUH folder ini ke flashdisk:
echo   %~dp0dataset\runs\{nama}
echo (berisi weights\best.pt dan weights\evaluasi.txt)
pause
"""

BACA_SAYA = r"""LATIH MODEL OCR STAND - KOMPUTER GPU
=====================================

1. Ekstrak ZIP ini ke folder mana saja, misal C:\latih_ocr

2. Sekali saja - pasang Python 3.10/3.11 lalu, di Command Prompt:
     nvidia-smi
   Laptop dengan dua GPU (mis. Radeon bawaan + NVIDIA RTX) tetap bisa:
   yang dipakai NVIDIA-nya. Pasang torch versi CUDA (bukan +cpu):
     pip uninstall -y torch torchvision
     pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
   (kalau "No matching distribution": ganti cu128 -> cu130, lalu cu126)
   Cek: python -c "import torch; print(torch.cuda.is_available())"  -> True
   lalu:
     pip install ultralytics

3. Klik dua kali latih.bat
   Baris pertama harus "GPU: NVIDIA ...". Kalau "GPU: False", torch yang
   terpasang versi CPU - ulangi langkah 2 (pip uninstall torch dulu).
   Training berhenti sendiri kalau tidak membaik 20 epoch (biasanya < 1 jam).
   Setelah itu evaluasi model lama vs baru berjalan otomatis (+- 20 menit)
   dan skornya tampil di layar.

4. Salin kembali ke flashdisk seluruh folder:
     dataset\runs\{nama}
   (weights\best.pt = model baru, weights\evaluasi.txt = skor,
    results.png / confusion_matrix.png = grafik training.)

Tanpa GPU NVIDIA (mis. AMD Radeon): latih.bat --imgsz 320 --epochs 30
  (+- 6-8 jam di CPU, tinggal semalam).

Opsi: latih.bat --model yolov8s.pt --epochs 150
  model lebih besar, sedikit lebih akurat, butuh internet untuk unduh bobot.
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--awal", default=os.path.join(ROOT, "model", "digit_detector.pt"),
                    help="model titik awal (hasil putaran sebelumnya)")
    ap.add_argument("--nama", default="digit_v7")
    a = ap.parse_args()
    if not os.path.exists(os.path.join(YOLO_DIR, "dataset.yaml")):
        raise SystemExit("Jalankan buat_dataset_yolo.py dulu.")
    n = 0
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_STORED) as z:
        for sub in ("images", "labels"):
            base = os.path.join(YOLO_DIR, sub)
            for dirpath, _, files in os.walk(base):
                for f in files:
                    if f.endswith(".cache"):
                        continue
                    p = os.path.join(dirpath, f)
                    z.write(p, os.path.join("dataset", os.path.relpath(p, YOLO_DIR)))
                    n += 1
        z.write(os.path.join(YOLO_DIR, "dataset.yaml"), "dataset/dataset.yaml")
        z.write(a.awal, "digit_detector.pt")
        z.write(os.path.join(ROOT, "model", "display_detector.pt"), "display_detector.pt")
        z.write(os.path.join(ROOT, "core", "reader.py"), "reader.py")
        for f in ("latih_ocr.py", "evaluasi_ocr.py"):
            z.write(os.path.join(ROOT, "tools", "ml", f), f)
        # Foto asli (bukan crop): evaluasi mengukur jalur penuh foto -> stand.
        t = pd.read_csv(os.path.join(YOLO_DIR, "test.csv"), dtype=str)
        rel = []
        for r in t.itertuples():
            nama = f"foto/{r.BLTH}_{r.IDPEL}.jpg"
            z.write(r.path, "test/" + nama)
            rel.append(nama)
        t["path"] = rel
        z.writestr("test/test.csv", t.drop(columns=["crop"]).to_csv(index=False))
        z.writestr("latih.bat", LATIH_BAT.replace("{nama}", a.nama).replace("\n", "\r\n"))
        z.writestr("BACA_SAYA.txt", BACA_SAYA.replace("{nama}", a.nama).replace("\n", "\r\n"))
    print(f"{n} file dataset -> {OUT} ({os.path.getsize(OUT) / 2**20:.0f} MB)")


if __name__ == "__main__":
    main()
