"""
Latih digit detector baru. Jalankan di komputer GPU.

Mulai dari model/digit_detector.pt (kelas 0-9 sama, jadi tidak perlu unduh
bobot dari internet). fliplr/flipud = 0: digit yang dicerminkan bukan digit
lagi (2 vs 5, 6 vs 9) - model lama dilatih dengan fliplr 0.5.

    python tools/ml/latih_ocr.py --data ml_data/ocr_v1/yolo/dataset.yaml
    python tools/ml/latih_ocr.py --data ... --model yolov8s.pt --epochs 150

Hasil: <data>/../runs/<nama>/weights/best.pt
"""
import argparse
import os

from ultralytics import YOLO

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Di paket flashdisk (buat_paket_gpu.py) model awal ada di samping skrip ini.
_DI_PAKET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "digit_detector.pt")
MODEL_AWAL = _DI_PAKET if os.path.exists(_DI_PAKET) else os.path.join(ROOT, "model", "digit_detector.pt")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--model", default=MODEL_AWAL)
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--nama", default="digit_v6")
    a = ap.parse_args()

    import torch
    device = 0 if torch.cuda.is_available() else "cpu"
    print("device:", torch.cuda.get_device_name(0) if device == 0 else "CPU (lambat!)")

    data = os.path.abspath(a.data)
    YOLO(a.model).train(
        data=data,
        project=os.path.join(os.path.dirname(data), "runs"),
        name=a.nama,
        exist_ok=True,
        epochs=a.epochs,
        patience=20,
        imgsz=a.imgsz,
        batch=a.batch if device == 0 else 8,
        device=device,
        workers=4 if device == 0 else 0,
        optimizer="AdamW",
        lr0=0.001,
        cos_lr=True,
        # augmentasi: foto lapangan miring, gelap, silau - tapi jangan dicermin
        fliplr=0.0,
        flipud=0.0,
        degrees=8,
        shear=3,
        perspective=0.0005,
        scale=0.4,
        translate=0.1,
        hsv_h=0.02,
        hsv_s=0.6,
        hsv_v=0.5,
        mosaic=0.5,
        close_mosaic=10,
        erasing=0.2,
        plots=True,
    )


if __name__ == "__main__":
    main()
