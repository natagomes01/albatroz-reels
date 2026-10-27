"""ffmpeg-full binaries, a runner that keeps the stderr tail, and ffprobe metadata."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from shorts import machine

def _tool(name: str) -> str:
    d = machine.ffmpeg_dir()
    if d is not None:
        return str(d / machine.exe(name))
    return shutil.which(name) or name


FFMPEG = _tool("ffmpeg")
FFPROBE = _tool("ffprobe")

# H.264 encoders; the default per OS is machine.default_encoder(). NVENC only by SHORTS_ENCODER.
ENCODERS = ("h264_videotoolbox", "libx264", "h264_nvenc")


def video_encoder() -> str:
    name = os.environ.get("SHORTS_ENCODER") or machine.default_encoder()
    if name not in ENCODERS:
        raise ValueError(f"SHORTS_ENCODER={name!r}: expected one of {', '.join(ENCODERS)}")
    return name


def encoder_args(preview: bool = False, encoder: str | None = None) -> list[str]:
    """`-c:v ...` arguments for a final render (about 10 Mb/s) or a light track preview."""
    enc = encoder or video_encoder()
    if enc == "h264_videotoolbox":
        rate = ["-b:v", "2M"] if preview else ["-b:v", "10M", "-maxrate", "14M", "-bufsize", "20M"]
        return ["-c:v", enc, *rate]
    cap = [] if preview else ["-maxrate", "14M", "-bufsize", "20M"]
    if enc == "libx264":
        q = ["-preset", "veryfast", "-crf", "26"] if preview else ["-preset", "medium", "-crf", "19"]
        return ["-c:v", enc, *q, *cap]
    q = ["-preset", "p4", "-rc", "vbr", "-cq", "28" if preview else "19", "-b:v", "2M" if preview else "10M"]
    return ["-c:v", enc, *q, *cap]

HDR_TRANSFERS = {"arib-std-b67", "smpte2084"}  # HLG, PQ
# Tone-maps an HDR (HLG/PQ) frame to SDR bt709. Shared by Vision sampling, color measurement and
# render, so everything that looks at pixels sees the same SDR image.
HDR_TO_SDR = (
    "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
    "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p"
)


class FFmpegError(RuntimeError):
    def __init__(self, cmd: list[str], stderr: str):
        self.cmd = cmd
        self.stderr_tail = "\n".join(stderr.strip().splitlines()[-20:])
        super().__init__(f"ffmpeg failed: {' '.join(cmd)}\n{self.stderr_tail}")


def run(args: list[str], capture_stdout: bool = False) -> subprocess.CompletedProcess:
    """Run ffmpeg/ffprobe; raise FFmpegError with the stderr tail and exact command on failure."""
    proc = subprocess.run(
        args,
        stdout=subprocess.PIPE if capture_stdout else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise FFmpegError(args, proc.stderr.decode("utf-8", "replace"))
    return proc


@dataclass(frozen=True)
class VideoInfo:
    width: int            # DISPLAYED size: swapped when the stream carries a ±90° rotation
    height: int
    fps: float
    duration: float
    color_transfer: str
    has_audio: bool
    rotation: int = 0     # display rotation in degrees (0, 90, -90, 180); ffmpeg autorotates on decode

    @property
    def is_hdr(self) -> bool:
        return self.color_transfer in HDR_TRANSFERS


def _rotation(stream: dict) -> int:
    for side in stream.get("side_data_list", []) or []:
        if "rotation" in side:
            return int(round(float(side["rotation"])))
    rotate = (stream.get("tags") or {}).get("rotate")
    return int(rotate) if rotate not in (None, "") else 0


def parse_probe(data: dict) -> VideoInfo:
    """First video stream and first audio stream only: iPhone .mov masters carry extra
    `data` streams (Core Media Metadata), which are ignored."""
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise ValueError("no video stream in input")
    rate = video.get("avg_frame_rate") or "0/0"
    if rate in ("0/0", "0/1"):
        rate = video.get("r_frame_rate") or "0/1"
    fps = float(Fraction(rate)) if rate not in ("0/0",) else 0.0
    width, height = int(video["width"]), int(video["height"])
    rotation = _rotation(video)
    if abs(rotation) % 180 == 90:
        width, height = height, width
    duration = data.get("format", {}).get("duration") or video.get("duration") or 0
    return VideoInfo(
        width=width,
        height=height,
        fps=fps,
        duration=float(duration),
        color_transfer=video.get("color_transfer", "unknown"),
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
        rotation=rotation,
    )


def probe(path: Path) -> VideoInfo:
    proc = run(
        [FFPROBE, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
        capture_stdout=True,
    )
    return parse_probe(json.loads(proc.stdout))
