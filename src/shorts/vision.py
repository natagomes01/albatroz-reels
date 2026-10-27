"""Person and face detection, fed one downscaled frame at a time from ffmpeg.

Apple Vision on macOS; YuNet + YOLOX-S in ONNX (`detect_onnx`) elsewhere or with
SHORTS_DETECTOR=onnx. Both return the same `Box` contract.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from shorts import machine
from shorts.ffmpeg import FFMPEG, HDR_TO_SDR, FFmpegError, VideoInfo, probe
from shorts.timeline import Span


@dataclass(frozen=True)
class Box:  # pixels in the SOURCE frame, origin top-left
    x: float
    y: float
    w: float
    h: float

    @property
    def cx(self) -> float:
        return self.x + self.w / 2


@dataclass(frozen=True)
class Detections:
    t: float  # class-timeline seconds
    bodies: list[Box]
    faces: list[Box]


def _scaled_size(src_w: int, src_h: int, width: int) -> tuple[int, int]:
    h = int(round(width * src_h / src_w / 2)) * 2
    return width, h


def sample_command(
    master: Path, span: Span, info: VideoInfo, fps: float = 3.0, width: int = 640
) -> tuple[list[str], int, int]:
    """ffmpeg command for Vision sampling, plus the output frame size.

    Maps only the first video stream (iPhone masters carry extra data streams). The size comes
    from the DISPLAYED dimensions (probe swaps them for a ±90° rotation; ffmpeg autorotates).
    HDR frames are tone-mapped after the downscale, so Vision sees the same SDR picture the
    render produces, at a fraction of the cost of tone-mapping full frames.
    """
    w, h = _scaled_size(info.width, info.height, width)
    vf = f"fps={fps},scale={w}:{h}" + (f",{HDR_TO_SDR}" if info.is_hdr else "")
    cmd = [
        FFMPEG, "-v", "error", "-ss", f"{span.start:.3f}", "-t", f"{span.duration:.3f}",
        "-i", str(master), "-map", "0:v:0", "-vf", vf, "-f", "rawvideo", "-pix_fmt", "bgra", "-",
    ]
    return cmd, w, h


def sample_frames(
    master: Path, span: Span, fps: float = 3.0, width: int = 640
) -> Iterator[tuple[float, bytes, int, int]]:
    """Yield (t_class, bgra_bytes, w, h), one frame at a time (never the whole clip in memory).

    Raises FFmpegError if ffmpeg fails after the last frame is read; a failed decode must not
    turn into a silent "weak tracking" warning. A consumer that stops early is not an error.
    """
    cmd, w, h = sample_command(master, span, probe(master), fps, width)
    frame_size = w * h * 4
    with tempfile.TemporaryFile() as err:  # a file, not a pipe: stderr can never block stdout
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err)
        assert proc.stdout is not None
        i = 0
        drained = False
        try:
            while True:
                buf = proc.stdout.read(frame_size)
                if len(buf) < frame_size:
                    drained = True
                    break
                yield span.start + i / fps, buf, w, h
                i += 1
        finally:
            proc.stdout.close()
            code = proc.wait()
        if drained and code != 0:
            err.seek(0)
            raise FFmpegError(cmd, err.read().decode("utf-8", "replace"))


def _to_boxes(observations, w_out: float, h_out: float) -> list[Box]:
    boxes = []
    for obs in observations or []:
        bb = obs.boundingBox()  # normalized, origin bottom-left
        x = bb.origin.x * w_out
        y = (1.0 - bb.origin.y - bb.size.height) * h_out
        boxes.append(Box(x, y, bb.size.width * w_out, bb.size.height * h_out))
    return boxes


DETECTORS = ("vision", "onnx")


def detector_name() -> str:
    """"vision" (Apple Vision) on macOS, "onnx" elsewhere; SHORTS_DETECTOR overrides."""
    name = os.environ.get("SHORTS_DETECTOR") or machine.default_detector()
    if name not in DETECTORS:
        raise ValueError(f"SHORTS_DETECTOR={name!r}: expected one of {', '.join(DETECTORS)}")
    return name


def detect(
    bgra: bytes, w: int, h: int, upper_body_only: bool, scale_to: tuple[int, int]
) -> tuple[list[Box], list[Box]]:
    """(bodies, faces) on one BGRA frame, in pixels of `scale_to` = (src_w, src_h), origin top-left."""
    if detector_name() == "onnx":
        from shorts import detect_onnx
        return detect_onnx.detect(bgra, w, h, upper_body_only, scale_to)
    return _detect_vision(bgra, w, h, upper_body_only, scale_to)


def _detect_vision(
    bgra: bytes, w: int, h: int, upper_body_only: bool, scale_to: tuple[int, int]
) -> tuple[list[Box], list[Box]]:
    """Run human-rectangle and face-rectangle requests on one BGRA frame."""
    import Quartz  # pyobjc; imported lazily so pure modules and tests never need it
    import Vision

    provider = Quartz.CGDataProviderCreateWithData(None, bgra, len(bgra), None)
    image = Quartz.CGImageCreate(
        w, h, 8, 32, w * 4, Quartz.CGColorSpaceCreateDeviceRGB(),
        Quartz.kCGBitmapByteOrder32Little | Quartz.kCGImageAlphaNoneSkipFirst,
        provider, None, False, Quartz.kCGRenderingIntentDefault,
    )
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(image, None)
    body_req = Vision.VNDetectHumanRectanglesRequest.alloc().init()
    body_req.setUpperBodyOnly_(upper_body_only)
    face_req = Vision.VNDetectFaceRectanglesRequest.alloc().init()
    ok, err = handler.performRequests_error_([body_req, face_req], None)
    if not ok:
        raise RuntimeError(f"Vision request failed: {err}")
    sw, sh = scale_to
    return _to_boxes(body_req.results(), sw, sh), _to_boxes(face_req.results(), sw, sh)
