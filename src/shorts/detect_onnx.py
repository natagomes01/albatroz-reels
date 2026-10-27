"""Cross-platform person and face detection: YuNet (faces, OpenCV) + YOLOX-S (bodies, onnxruntime).

The fallback for machines without Apple Vision (Windows, Linux). Same contract as Vision: boxes
in pixels of `scale_to`, origin top-left. Models are downloaded once into a cache outside the
repo, checked by sha256, and loaded once per process. Licenses: YuNet MIT (opencv_zoo), YOLOX
Apache-2.0 (Megvii); see THIRD_PARTY.md.
"""
from __future__ import annotations

import hashlib
import os
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from shorts import machine


@dataclass(frozen=True)
class Model:
    file: str
    url: str
    sha256: str


YUNET = Model(
    "face_detection_yunet_2023mar.onnx",
    "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/"
    "face_detection_yunet_2023mar.onnx",
    "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
)
YOLOX_S = Model(
    "yolox_s.onnx",
    "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_s.onnx",
    "c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063",
)

YOLOX_SIZE = 640        # square network input
PERSON_SCORE = 0.35     # objectness x class score for COCO class 0
FACE_SCORE = 0.6
NMS_IOU = 0.45


def models_dir() -> Path:
    """SHORTS_MODELS_DIR, else <machine.cache_dir()>/models."""
    env = os.environ.get("SHORTS_MODELS_DIR")
    return Path(env).expanduser() if env else machine.cache_dir() / "models"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_model(model: Model, directory: Path | None = None) -> Path:
    """Path of a verified model file, downloading it on first use. A wrong hash is an error, never
    a silent re-download: it means a corrupt cache or a changed upstream file."""
    directory = directory or models_dir()
    path = directory / model.file
    if not path.exists():
        directory.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        urllib.request.urlretrieve(model.url, tmp)
        got = _sha256(tmp)
        if got != model.sha256:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"{model.file}: sha256 {got} != expected {model.sha256} ({model.url})")
        os.replace(tmp, path)
        return path
    got = _sha256(path)
    if got != model.sha256:
        raise RuntimeError(f"{path}: sha256 {got} != expected {model.sha256}; delete it to download again")
    return path


@lru_cache(maxsize=1)
def _face_detector():
    import cv2
    try:  # OpenCV 5 warns once per process that the new graph engine ignores the DNN target
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
    except AttributeError:
        pass
    return cv2.FaceDetectorYN.create(str(ensure_model(YUNET)), "", (320, 320), FACE_SCORE, 0.3, 5000)


@lru_cache(maxsize=1)
def _body_session():
    import onnxruntime as ort
    opts = ort.SessionOptions()
    opts.log_severity_level = 3
    return ort.InferenceSession(str(ensure_model(YOLOX_S)), opts, providers=["CPUExecutionProvider"])


@lru_cache(maxsize=1)
def _grid():
    """YOLOX anchor-free decode grid: (cells xy, stride) for strides 8, 16, 32."""
    import numpy as np
    cells, strides = [], []
    for s in (8, 16, 32):
        n = YOLOX_SIZE // s
        xv, yv = np.meshgrid(np.arange(n), np.arange(n))
        cells.append(np.stack((xv, yv), 2).reshape(-1, 2))
        strides.append(np.full((n * n, 1), s))
    return np.concatenate(cells).astype(np.float32), np.concatenate(strides).astype(np.float32)


def _nms(xywh, scores, iou: float) -> list[int]:
    import cv2
    keep = cv2.dnn.NMSBoxes(xywh.tolist(), scores.tolist(), 0.0, iou)
    return [int(i) for i in (keep.flatten() if len(keep) else [])]


def detect_people(bgr, threshold: float = PERSON_SCORE):
    """Person boxes [(x, y, w, h)] in pixels of `bgr` (an HxWx3 uint8 array)."""
    import cv2
    import numpy as np

    h, w = bgr.shape[:2]
    r = min(YOLOX_SIZE / h, YOLOX_SIZE / w)
    padded = np.full((YOLOX_SIZE, YOLOX_SIZE, 3), 114, dtype=np.uint8)
    nh, nw = int(round(h * r)), int(round(w * r))
    padded[:nh, :nw] = cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_LINEAR)
    blob = padded.transpose(2, 0, 1)[None].astype(np.float32)   # BGR 0-255, no normalization
    session = _body_session()
    out = session.run(None, {session.get_inputs()[0].name: blob})[0][0]
    cells, strides = _grid()
    scores = out[:, 4] * out[:, 5]                               # objectness x P(person)
    mask = scores >= threshold
    if not mask.any():
        return []
    out, scores, cells, strides = out[mask], scores[mask], cells[mask], strides[mask]
    cxcy = (out[:, :2] + cells) * strides / r
    wh = np.exp(out[:, 2:4]) * strides / r
    xywh = np.concatenate((cxcy - wh / 2, wh), 1)
    return [tuple(float(v) for v in xywh[i]) for i in _nms(xywh, scores, NMS_IOU)]


def detect_faces(bgr):
    """Face boxes [(x, y, w, h)] in pixels of `bgr`."""
    h, w = bgr.shape[:2]
    det = _face_detector()
    det.setInputSize((w, h))
    _, faces = det.detect(bgr)
    return [] if faces is None else [tuple(float(v) for v in f[:4]) for f in faces]


def detect(bgra: bytes, w: int, h: int, upper_body_only: bool, scale_to: tuple[int, int]):
    """(bodies, faces) as vision.Box lists in pixels of `scale_to`, origin top-left.

    `upper_body_only` is accepted for parity with Vision and ignored: YOLOX finds a seated,
    desk-cropped speaker as it is, and the top edge (the one the close-up headroom uses) is the
    same either way.
    """
    import numpy as np

    from shorts.vision import Box

    bgr = np.ascontiguousarray(np.frombuffer(bgra, np.uint8).reshape(h, w, 4)[:, :, :3])
    sx, sy = scale_to[0] / w, scale_to[1] / h

    def boxes(found):
        out = []
        for x, y, bw, bh in found:
            x0, y0 = max(x, 0.0), max(y, 0.0)
            x1, y1 = min(x + bw, w), min(y + bh, h)
            if x1 > x0 and y1 > y0:
                out.append(Box(x0 * sx, y0 * sy, (x1 - x0) * sx, (y1 - y0) * sy))
        return out

    return boxes(detect_people(bgr)), boxes(detect_faces(bgr))
