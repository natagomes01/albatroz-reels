"""Automatic color correction measured every 10 minutes and interpolated (spec 10.3)."""
from __future__ import annotations

import math
from dataclasses import dataclass, fields
from pathlib import Path

from shorts.ffmpeg import FFMPEG, HDR_TO_SDR, probe, run

SAMPLE_W, SAMPLE_H = 64, 36
FRAMES_PER_POINT = 5
TARGET_MEAN = 0.45


@dataclass(frozen=True)
class Grade:
    rimin: float
    gimin: float
    bimin: float
    rimax: float
    gimax: float
    bimax: float
    gamma: float


NEUTRAL = Grade(0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0)


def _percentile(values: list[int], q: float) -> float:
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return float(ordered[idx])


def grade_from_stats(pixels_rgb: list[tuple[int, int, int]]) -> Grade:
    """Levels per channel from the 1st/99th percentile, gray-world balance, gamma to mid-gray."""
    if not pixels_rgb:
        return NEUTRAL
    chans = list(zip(*pixels_rgb))
    lo = [min(_percentile(list(c), 0.01) / 255, 0.10) for c in chans]
    hi = [max(_percentile(list(c), 0.99) / 255, lo[i] + 0.30) for i, c in enumerate(chans)]
    stretched = [
        [min(max((v / 255 - lo[i]) / (hi[i] - lo[i]), 0.0), 1.0) for v in c]
        for i, c in enumerate(chans)
    ]
    means = [sum(c) / len(c) for c in stretched]
    gray = sum(means) / 3
    # gray world: a channel brighter than average gets a higher white point (less gain)
    hi = [min(1.0, max(lo[i] + 0.30, hi[i] * (means[i] / gray if gray > 0 else 1.0))) for i in range(3)]
    luma = min(max(gray, 0.05), 0.95)
    gamma = min(max(math.log(luma) / math.log(TARGET_MEAN), 0.8), 1.4)
    return Grade(lo[0], lo[1], lo[2], hi[0], hi[1], hi[2], gamma)


def frames_command(master: Path, t: float, hdr: bool) -> list[str]:
    """A few small RGB frames around class time t. HDR is tone-mapped before the downscale, so
    the grade is measured on the SDR image the render will apply it to (review C1)."""
    vf = f"fps={FRAMES_PER_POINT / 10}"
    if hdr:
        vf += f",{HDR_TO_SDR}"
    vf += f",scale={SAMPLE_W}:{SAMPLE_H}:in_color_matrix=bt709,format=rgb24"
    return [FFMPEG, "-v", "error", "-ss", f"{t:.3f}", "-i", str(master), "-t", "10",
            "-map", "0:v:0", "-vf", vf, "-frames:v", str(FRAMES_PER_POINT),
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]


def _frames_rgb(master: Path, t: float, hdr: bool) -> list[tuple[int, int, int]]:
    raw = run(frames_command(master, t, hdr), capture_stdout=True).stdout
    return [(raw[i], raw[i + 1], raw[i + 2]) for i in range(0, len(raw) - 2, 3)]


def measure_points(master: Path, duration: float, every: float = 600.0) -> list[tuple[float, Grade]]:
    """One Grade every `every` seconds of the class (at least one), from a few sampled frames."""
    hdr = probe(master).is_hdr
    count = max(1, int(duration // every) + 1)
    times = [min(i * every, max(duration - 10.0, 0.0)) for i in range(count)]
    return [(t, grade_from_stats(_frames_rgb(master, t, hdr))) for t in times]


def interpolate_grade(points: list[tuple[float, Grade]], t: float) -> Grade:
    """Linear interpolation between measured points, clamped at both ends."""
    if not points:
        return NEUTRAL
    if t <= points[0][0]:
        return points[0][1]
    if t >= points[-1][0]:
        return points[-1][1]
    for (ta, ga), (tb, gb) in zip(points, points[1:]):
        if ta <= t <= tb:
            k = (t - ta) / (tb - ta) if tb > ta else 0.0
            return Grade(*(getattr(ga, f.name) + k * (getattr(gb, f.name) - getattr(ga, f.name)) for f in fields(Grade)))
    return points[-1][1]


def grade_filter(g: Grade) -> str:
    """colorlevels works in RGB and eq in YUV. The conversions around colorlevels are explicit
    bt709 (limited range), so ffmpeg never picks a different matrix and shifts the colors."""
    return (
        "scale=in_color_matrix=bt709:in_range=tv,format=gbrp,"
        f"colorlevels=rimin={g.rimin:.3f}:gimin={g.gimin:.3f}:bimin={g.bimin:.3f}"
        f":rimax={g.rimax:.3f}:gimax={g.gimax:.3f}:bimax={g.bimax:.3f},"
        "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,"
        f"eq=gamma={g.gamma:.3f}:saturation=1.05"
    )
