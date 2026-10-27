"""Silence detection with ffmpeg silencedetect (spec 10.2)."""
from __future__ import annotations

import re
from pathlib import Path

from shorts.ffmpeg import FFMPEG, run
from shorts.timeline import Span

_START = re.compile(r"silence_start:\s*(-?[0-9.]+)")
_END = re.compile(r"silence_end:\s*(-?[0-9.]+)")


def parse_silencedetect(stderr: str, offset: float, end: float | None = None) -> list[Span]:
    """Silences from silencedetect output, shifted by `offset` into the class timeline.

    A silence still open when the input ends is closed at `end` (class time) if given.
    """
    spans: list[Span] = []
    start: float | None = None
    for line in stderr.splitlines():
        m = _START.search(line)
        if m:
            start = max(float(m.group(1)), 0.0) + offset
            continue
        m = _END.search(line)
        if m and start is not None:
            spans.append(Span(start, float(m.group(1)) + offset))
            start = None
    if start is not None and end is not None and end > start:
        spans.append(Span(start, end))
    return spans


def detect_silences(master: Path, span: Span, noise_db: float = -35.0, min_dur: float = 0.3) -> list[Span]:
    """Silences of at least `min_dur` seconds below `noise_db` inside `span` (class timeline)."""
    proc = run(
        [FFMPEG, "-hide_banner", "-nostats", "-ss", f"{span.start:.3f}", "-t", f"{span.duration:.3f}",
         "-i", str(master), "-map", "0:a:0", "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}",
         "-f", "null", "-"]
    )
    return parse_silencedetect(proc.stderr.decode("utf-8", "replace"), span.start, span.end)
