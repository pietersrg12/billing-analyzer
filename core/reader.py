"""
Meter digit reader menggunakan YOLOv8 detection (two-stage).
Stage 1: Deteksi area display meter (display_detector.pt)
Stage 2: Deteksi digit individual di area crop (digit_detector.pt)
"""

import threading
from pathlib import Path

import cv2
import numpy as np

_DISPLAY_MODEL = None
_DIGIT_MODEL = None
_DISPLAY_MODEL_PATH = None
_DIGIT_MODEL_PATH = None
_MODEL_LOCK = threading.Lock()


def _load_model(model_path, is_display=False):
    global _DISPLAY_MODEL, _DIGIT_MODEL, _DISPLAY_MODEL_PATH, _DIGIT_MODEL_PATH
    p = str(model_path)

    with _MODEL_LOCK:
        if is_display:
            if _DISPLAY_MODEL is not None and _DISPLAY_MODEL_PATH == p:
                return _DISPLAY_MODEL
        else:
            if _DIGIT_MODEL is not None and _DIGIT_MODEL_PATH == p:
                return _DIGIT_MODEL

        if not Path(p).exists():
            return None
        try:
            from ultralytics import YOLO
        except ImportError:
            return None
        try:
            model = YOLO(p)
            if is_display:
                _DISPLAY_MODEL = model
                _DISPLAY_MODEL_PATH = p
            else:
                _DIGIT_MODEL = model
                _DIGIT_MODEL_PATH = p
            return model
        except Exception:
            return None


def _get_display_bbox(image_path, display_model_path, conf_threshold=0.3):
    """Stage 1: deteksi bounding box area display meter."""
    model = _load_model(display_model_path, is_display=True)
    if model is None:
        return None

    results = model.predict(
        source=image_path, conf=conf_threshold, verbose=False, device="cpu"
    )
    if not results or len(results[0].boxes) == 0:
        return None

    box = results[0].boxes[0]
    return [int(v) for v in box.xyxy[0].tolist()]


def _remove_overlapping(detections, overlap_thresh=0.5):
    """Remove overlapping detections (same digit detected twice), keep highest confidence."""
    if not detections:
        return []
    dets = sorted(detections, key=lambda d: d["confidence"], reverse=True)
    kept = []
    for d in dets:
        is_dup = False
        for k in kept:
            x_overlap = min(d["x2"], k["x2"]) - max(d["x1"], k["x1"])
            if x_overlap > 0:
                min_w = min(d["w"], k["w"])
                if min_w > 0 and x_overlap / min_w > overlap_thresh:
                    is_dup = True
                    break
                y_overlap = min(d["y2"], k["y2"]) - max(d["y1"], k["y1"])
                if y_overlap > 0 and d["h"] > 0 and k["h"] > 0:
                    min_h = min(d["h"], k["h"])
                    if x_overlap / min_w > 0.3 and y_overlap / min_h > overlap_thresh:
                        is_dup = True
                        break
        if not is_dup:
            kept.append(d)
    return kept


def _filter_digit_row(detections):
    """Temukan baris digit paling konsisten dari deteksi."""
    if not detections:
        return []

    for d in detections:
        d["h"] = d["y2"] - d["y1"]
        d["w"] = d["x2"] - d["x1"]
        d["aspect"] = d["h"] / (d["w"] + 1e-6)

    candidates = [
        d for d in detections if 0.4 < d["aspect"] < 3.0 and d["h"] > 3 and d["w"] > 2
    ]
    if not candidates:
        return []

    # Hapus deteksi overlap
    candidates = _remove_overlapping(candidates)

    candidates.sort(key=lambda d: d["cy"])
    median_h = np.median([d["h"] for d in candidates])
    y_gap = median_h * 0.6

    rows = []
    current = [candidates[0]]
    for det in candidates[1:]:
        if abs(det["cy"] - current[-1]["cy"]) < y_gap:
            current.append(det)
        else:
            current.sort(key=lambda d: d["cx"])
            rows.append(current)
            current = [det]
    current.sort(key=lambda d: d["cx"])
    rows.append(current)

    if not rows:
        candidates.sort(key=lambda d: d["cx"])
        return candidates if len(candidates) >= 2 else candidates[:1]

    scored = []
    for row in rows:
        if len(row) < 2:
            continue

        n = len(row)

        h_vals = [d["h"] for d in row]
        h_cv = np.std(h_vals) / (np.mean(h_vals) + 1e-6)
        h_score = max(0, 1 - h_cv)

        w_vals = [d["w"] for d in row]
        w_cv = np.std(w_vals) / (np.mean(w_vals) + 1e-6)
        w_score = max(0, 1 - w_cv)

        xs = [d["cx"] for d in row]
        gaps = np.diff(xs)
        if len(gaps) >= 1:
            mean_gap = np.mean(gaps)
            gap_cv = np.std(gaps) / (mean_gap + 1e-6)
            gap_score = max(0, 1 - min(gap_cv, 2) / 2)
            min_gap_ratio = min(gaps) / (mean_gap + 1e-6) if mean_gap > 0 else 1
            gap_penalty = 0.5 if (len(gaps) > 1 and min_gap_ratio < 0.35) else 0
        else:
            gap_score = 0
            gap_penalty = 0

        # n_score: prefer 5-6 digit (typical meter), toleransi 4-7
        n_score = np.exp(-0.5 * ((n - 6) / 1.8) ** 2)

        avg_conf = np.mean([d["confidence"] for d in row])
        conf_score = min(avg_conf, 1.0)

        score = n_score * 3 + h_score + w_score + gap_score - gap_penalty + conf_score
        scored.append((score, row))

    scored.sort(key=lambda x: -x[0])
    if not scored:
        return []

    best = scored[0][1]
    best.sort(key=lambda d: d["cx"])

    # Cleanup: hapus outlier hanya jika baris terlalu panjang (> 6 digit)
    if len(best) > 6:
        keep = [True] * len(best)

        # Iteratif hapus deteksi yang menyebabkan gap terlalu kecil
        changed = True
        while changed and sum(keep) > 5:
            changed = False
            idx = [i for i, k in enumerate(keep) if k]
            if len(idx) < 6:
                break
            best_xs = np.array([best[i]["cx"] for i in idx])
            best_gaps = np.diff(best_xs)
            min_gap = np.min(best_gaps)
            mean_gap = np.mean(best_gaps)

            if min_gap < mean_gap * 0.35:
                min_pos = int(np.argmin(best_gaps))
                i1, i2 = idx[min_pos], idx[min_pos + 1]
                if best[i1]["confidence"] < best[i2]["confidence"]:
                    keep[i1] = False
                else:
                    keep[i2] = False
                changed = True

        # Hapus confidence outlier hanya jika masih > 6
        if sum(keep) > 6:
            idx = [i for i, k in enumerate(keep) if k]
            confs = np.array([best[i]["confidence"] for i in idx])
            median_conf = np.median(confs)
            for i in idx:
                if best[i]["confidence"] < median_conf * 0.25 and sum(keep) > 6:
                    keep[i] = False

        best = [d for i, d in enumerate(best) if keep[i]]

    return best


def _run_digit_inference(digit_model, image, conf_threshold, iou_threshold, imgsz):
    """Run digit inference and return filtered detection row."""
    results = digit_model.predict(
        source=image, conf=conf_threshold, iou=iou_threshold,
        imgsz=imgsz, verbose=False, device="cpu",
    )
    if not results or len(results[0].boxes) == 0:
        return None

    boxes = results[0].boxes
    detections = []
    for i in range(len(boxes)):
        detections.append({
            "class": int(boxes.cls[i]),
            "confidence": float(boxes.conf[i]),
            "x1": float(boxes.xyxy[i][0]),
            "y1": float(boxes.xyxy[i][1]),
            "x2": float(boxes.xyxy[i][2]),
            "y2": float(boxes.xyxy[i][3]),
            "cx": float((boxes.xyxy[i][0] + boxes.xyxy[i][2]) / 2),
            "cy": float((boxes.xyxy[i][1] + boxes.xyxy[i][3]) / 2),
        })

    return _filter_digit_row(detections)


def _prepare_crop(img, display_box):
    """Crop display area and enhance contrast."""
    x1, y1, x2, y2 = display_box
    x1 = max(0, x1 - 15)
    y1 = max(0, y1 - 10)
    x2 = min(img.shape[1], x2 + 15)
    y2 = min(img.shape[0], y2 + 10)

    cropped = img[y1:y2, x1:x2]
    if cropped.size == 0:
        return None

    up_factor = max(1, min(3, 320 // max(cropped.shape[0], 1)))
    if up_factor > 1:
        cropped = cv2.resize(
            cropped, None, fx=up_factor, fy=up_factor, interpolation=cv2.INTER_CUBIC
        )

    return cropped


def _make_result(main_row):
    """Build result dict from a filtered digit row."""
    if not main_row:
        return None
    digit_chars = [str(d["class"]) for d in main_row]
    confs = [d["confidence"] for d in main_row]
    avg_conf = float(np.mean(confs)) if confs else 0.0
    return {
        "success": True,
        "stand": "".join(digit_chars),
        "confidence": avg_conf,
        "digit_confs": list(zip(digit_chars, [round(c, 4) for c in confs])),
        "n_digits": len(digit_chars),
    }


def read_meter_digits(
    image_path,
    model_path,
    display_model_path=None,
    conf_threshold=0.25,
    iou_threshold=0.45,
    imgsz=640,
):
    if display_model_path is None:
        mp = Path(model_path)
        display_model_path = str(mp.parent / "display_detector.pt")

    if not Path(image_path).exists():
        return {
            "success": False,
            "stand": None,
            "confidence": 0.0,
            "digit_confs": [],
            "error": f"File tidak ditemukan: {image_path}",
        }

    img = cv2.imread(str(image_path))
    if img is None:
        return {
            "success": False,
            "stand": None,
            "confidence": 0.0,
            "digit_confs": [],
            "error": "Gambar tidak bisa dibaca",
        }
    digit_model = _load_model(model_path, is_display=False)
    if digit_model is None:
        return {
            "success": False,
            "stand": None,
            "confidence": 0.0,
            "digit_confs": [],
            "error": "Digit model tidak bisa di-load",
        }

    def _try_inference(image_source, method_label):
        best_result = None
        for conf in [conf_threshold, conf_threshold * 0.6, conf_threshold * 0.3]:
            main_row = _run_digit_inference(
                digit_model, image_source, conf, iou_threshold, imgsz
            )
            r = _make_result(main_row)
            if r is None:
                continue
            if best_result is None or r["n_digits"] > best_result["n_digits"]:
                r["method"] = method_label
                best_result = r
            if r["n_digits"] >= 5:
                r["method"] = method_label
                return r
        return best_result

    # Stage 1: Deteksi area display
    display_box = _get_display_bbox(str(image_path), display_model_path)

    # Stage 2: Deteksi digit pada crop display
    if display_box:
        cropped = _prepare_crop(img, display_box)
        if cropped is not None:
            result = _try_inference(cropped, "two_stage")
            if result and result["n_digits"] >= 4:
                return result

    # Fallback: deteksi langsung pada gambar penuh
    result = _try_inference(str(image_path), "full_image")
    if result:
        return result

    return {
        "success": False,
        "stand": None,
        "confidence": 0.0,
        "digit_confs": [],
        "error": "Tidak ada digit terdeteksi",
    }


def read_meter_batch(
    idpel_to_path,
    model_path,
    display_model_path=None,
    progress_callback=None,
    stop_flag=None,
    conf_threshold=0.25,
):
    hasil = {}
    items = list(idpel_to_path.items())
    total = len(items)

    for i, (idpel, path) in enumerate(items, start=1):
        if stop_flag and stop_flag():
            for j in range(i - 1, total):
                hasil.setdefault(items[j][0], {
                    "success": False,
                    "stand": None,
                    "confidence": 0.0,
                    "error": "Cancelled",
                })
            break

        if not path or not Path(path).exists():
            result = {
                "success": False,
                "stand": None,
                "confidence": 0.0,
                "error": "File not found",
            }
        else:
            result = read_meter_digits(
                path, model_path, display_model_path, conf_threshold
            )

        hasil[idpel] = result

        if progress_callback:
            progress_callback(i, total, idpel, result)

    return hasil


def is_available(model_path):
    if not Path(model_path).exists():
        return False
    try:
        import ultralytics
        return True
    except ImportError:
        return False
