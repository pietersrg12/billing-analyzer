"""
KWH meter image classifier menggunakan YOLOv8.

Lazy-load model. Kalau ultralytics tidak terinstal atau file model
hilang, classify_all akan return {idpel: 'unknown'} untuk semua dan
pipeline tetap lanjut.
"""

import threading
import traceback
from pathlib import Path


_MODEL = None
_MODEL_PATH = None
_LOAD_FAILED = False
_LOAD_ERROR = None
_LOCK = threading.Lock()


def load_error():
    """Alasan model gagal dipakai, atau None kalau tidak ada masalah.

    Kegagalan model sengaja tidak menghentikan pipeline, tapi alasannya harus
    tetap bisa dibaca: tanpa ini semua foto jadi 'unknown' tanpa jejak apa pun.
    """
    return _LOAD_ERROR


def is_available(model_path):
    """Cek apakah model file ada dan YOLO benar-benar bisa dipakai.

    Sengaja mengimpor YOLO, bukan paket ultralytics saja: paket level atas
    bisa terimpor sementara YOLO gagal karena dependency turunannya
    (mis. torchvision) tidak ikut ter-bundle.
    """
    if not Path(model_path).exists():
        return False
    try:
        from ultralytics import YOLO  # noqa: F401
        return True
    except Exception:
        return False


def _load_model(model_path):
    """Lazy-load YOLO model. Thread-safe. Cache global."""
    global _MODEL, _MODEL_PATH, _LOAD_FAILED, _LOAD_ERROR

    with _LOCK:
        if _MODEL is not None and _MODEL_PATH == model_path:
            return _MODEL
        if _LOAD_FAILED and _MODEL_PATH == model_path:
            return None

        try:
            from ultralytics import YOLO
        except ImportError as e:
            _LOAD_FAILED = True
            _LOAD_ERROR = f"ultralytics tidak bisa di-import: {e}"
            _MODEL_PATH = model_path
            return None

        if not Path(model_path).exists():
            _LOAD_FAILED = True
            _LOAD_ERROR = f"file model tidak ada: {model_path}"
            _MODEL_PATH = model_path
            return None

        try:
            _MODEL = YOLO(model_path)
            _MODEL_PATH = model_path
            _LOAD_FAILED = False
            _LOAD_ERROR = None
            return _MODEL
        except Exception as e:
            _LOAD_FAILED = True
            _LOAD_ERROR = f"YOLO({model_path}) gagal: {type(e).__name__}: {e}\n{traceback.format_exc()}"
            _MODEL_PATH = model_path
            return None


def classify_foto(model, foto_path):
    """Klasifikasi 1 foto. Return label string atau 'error'."""
    global _LOAD_ERROR
    try:
        results = model.predict(str(foto_path), verbose=False)
        top1 = results[0].probs.top1
        names = results[0].names
        return names[top1]
    except Exception as e:
        _LOAD_ERROR = f"predict({foto_path}) gagal: {type(e).__name__}: {e}\n{traceback.format_exc()}"
        return "error"


def classify_all(idpel_to_path, model_path,
                 progress_callback=None, stop_flag=None):
    """Klasifikasi banyak foto secara sekuensial.

    Args:
        idpel_to_path: dict {idpel: filepath}. Filepath bisa None.
        model_path: path ke best.pt
        progress_callback: callable(done, total, idpel, label)
        stop_flag: callable() -> bool, untuk cancel

    Returns:
        dict {idpel: 'kwh_meter' | 'bukan_kwh' | 'unknown' | 'error'}
    """
    model = _load_model(model_path)

    if model is None:
        # Graceful fallback: semua jadi unknown
        return {idpel: "unknown" for idpel in idpel_to_path}

    hasil = {}
    items = list(idpel_to_path.items())
    total = len(items)

    for i, (idpel, path) in enumerate(items, start=1):
        if stop_flag and stop_flag():
            # Tandai sisa sebagai unknown agar mapping di Excel tetap utuh
            for j in range(i - 1, total):
                rest_idpel = items[j][0]
                hasil.setdefault(rest_idpel, "unknown")
            break

        if not path or not Path(path).exists():
            label = "unknown"
        else:
            label = classify_foto(model, path)

        hasil[idpel] = label

        if progress_callback:
            progress_callback(i, total, idpel, label)

    return hasil
