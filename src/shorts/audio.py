"""Voice treatment: gentle cleanup and two-pass loudness normalization (spec 10.4)."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from shorts.ffmpeg import FFMPEG, run
from shorts.timeline import Span, group_edl

CLEANUP = "highpass=f=70,afftdn=nr=6:nf=-45"
TARGET = "I=-14:TP=-1.5:LRA=11"


def select_expr(edl: list[Span], origin: float) -> str:
    """ffmpeg select/aselect expression keeping the EDL spans (times relative to `origin`).

    Uses half-open gte()*lt() terms: between() is inclusive at both ends and double-counts
    the shared boundary instant.
    """
    return "+".join(
        f"gte(t,{s.start - origin:.3f})*lt(t,{s.end - origin:.3f})" for s in edl
    )


def audio_filter(measured: dict | None) -> str:
    """Cleanup + loudnorm; with first-pass measurements, a linear second pass."""
    loud = f"loudnorm={TARGET}"
    if measured:
        loud += (
            f":measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
            f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
            f":offset={measured['target_offset']}:linear=true"
        )
    return f"{CLEANUP},{loud},aresample=48000"


def _last_json(stderr: str) -> dict:
    blocks = re.findall(r"\{[^{}]*\}", stderr)
    if not blocks:
        raise ValueError("loudnorm printed no JSON")
    return json.loads(blocks[-1])


def audio_inputs(master: Path, groups, audio_files: list[Path] | None) -> list[str]:
    """ffmpeg inputs for the sound of each group: the master seeked to the group's window, or
    the group's dereverbed WAV, which already starts at the window start (S8 audio spec 4.4)."""
    if audio_files is not None and len(audio_files) != len(groups):
        raise ValueError(f"{len(audio_files)} audio files for {len(groups)} segment groups")
    cmd: list[str] = []
    for i, (window, _) in enumerate(groups):
        if audio_files is not None:
            cmd += ["-i", str(audio_files[i])]
        else:
            cmd += ["-ss", f"{window.start:.3f}", "-to", f"{window.end:.3f}", "-i", str(master)]
    return cmd


def _concat_graph(groups) -> tuple[list[str], str]:
    """Per-group select filters and the concat input pads, shared by the loudnorm measurement
    and the render so both see the same signal."""
    parts = [
        f"[{i}:a:0]aselect='{select_expr(spans, window.start)}',asetpts=N/SR/TB[a{i}]"
        for i, (window, spans) in enumerate(groups)
    ]
    return parts, "".join(f"[a{i}]" for i in range(len(groups)))


def loudnorm_measure(master: Path, edl: list[Span], segments: list[Span] | None = None,
                     audio_files: list[Path] | None = None) -> dict:
    """First loudnorm pass over the EDL-selected audio, after the same cleanup filters.

    One input per segment (seeking straight to it, or its dereverbed WAV), concatenated in
    playback order, so far-apart or out-of-order segments cost no extra decoding.
    """
    groups = group_edl(edl, segments)
    cmd = [FFMPEG, "-hide_banner", "-nostats", *audio_inputs(master, groups, audio_files)]
    parts, pads = _concat_graph(groups)
    parts.append(f"{pads}concat=n={len(groups)}:v=0:a=1,{CLEANUP},loudnorm={TARGET}:print_format=json[out]")
    cmd += ["-filter_complex", ";".join(parts), "-map", "[out]", "-f", "null", "-"]
    proc = run(cmd)
    return _last_json(proc.stderr.decode("utf-8", "replace"))


def render_audio(master: Path, edl: list[Span], segments: list[Span] | None,
                 audio_files: list[Path] | None, measured: dict | None, out: Path) -> Path:
    """Sound only, as the render makes it (EDL, cleanup, two-pass loudnorm), to an AAC .m4a.
    Written to <out>.tmp.m4a, then moved over <out> only on success."""
    groups = group_edl(edl, segments)
    parts, pads = _concat_graph(groups)
    parts.append(f"{pads}concat=n={len(groups)}:v=0:a=1,{audio_filter(measured)}[out]")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.stem + ".tmp.m4a")
    try:
        run([FFMPEG, "-y", "-hide_banner", "-nostats", *audio_inputs(master, groups, audio_files),
             "-filter_complex", ";".join(parts), "-map", "[out]",
             "-c:a", "aac", "-b:a", "160k", "-ar", "48000", str(tmp)])
        os.replace(tmp, out)
    finally:
        tmp.unlink(missing_ok=True)
    return out
