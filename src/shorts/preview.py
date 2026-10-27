"""`shorts track --preview`: a small video with the crop window and the tracked body drawn (spec 8.1)."""
from __future__ import annotations

import os
from pathlib import Path

from shorts.audio import select_expr
from shorts.ffmpeg import FFMPEG, VideoInfo, encoder_args, run
from shorts.ffmpeg import HDR_TO_SDR
from shorts.render import _quote
from shorts.shots import Crop
from shorts.timeline import Span, group_edl
from shorts.vision import Box

PREVIEW_W = 640
THICKNESS = 10
OFFSCREEN = (-1000, -1000, 2, 2)  # where the body box goes while Vision has lost the person


def _rect(box: Box | None) -> tuple[int, int, int, int]:
    if box is None:
        return OFFSCREEN
    return (int(round(box.x)), int(round(box.y)), max(int(round(box.w)), 2), max(int(round(box.h)), 2))


def _commands(crops: list[Crop], bodies: list[Box | None], fps: int) -> str:
    """drawbox positions per frame as sendcmd lines, emitted only when a box moves."""
    lines: list[str] = []
    last: dict[str, tuple[int, int, int, int]] = {}
    for i, (crop, body) in enumerate(zip(crops, bodies)):
        for name, rect in (("crop", (crop.x, crop.y, crop.w, crop.h)), ("body", _rect(body))):
            if last.get(name) == rect:
                continue
            last[name] = rect
            x, y, w, h = rect
            # floored like render._sendcmd: a command fires at or past its time, never round up
            lines.append(f"{max(i / fps - 0.0005, 0):.4f} drawbox@{name} x {x}, drawbox@{name} y {y}, "
                         f"drawbox@{name} w {w}, drawbox@{name} h {h};")
    return "\n".join(lines) + "\n"


def track_preview(master: Path, info: VideoInfo, edl: list[Span], segments: list[Span] | None,
                  crops: list[Crop], bodies: list[Box | None], out: Path, fps: int = 30) -> Path:
    """Source frames of the clip, crop window in lime, tracked body in red, 640 px wide, no audio."""
    if not crops:
        raise ValueError("track_preview needs at least one crop window")
    if len(crops) != len(bodies):
        raise ValueError("track_preview needs one body entry per output frame")
    out.parent.mkdir(parents=True, exist_ok=True)
    groups = group_edl(edl, segments)
    cmds = out.with_suffix(".cmd")
    cmds.write_text(_commands(crops, bodies, fps), encoding="utf-8")
    graph: list[str] = []
    for i, (window, spans) in enumerate(groups):
        tone = f",{HDR_TO_SDR}" if info.is_hdr else ""
        graph.append(f"[{i}:v:0]fps={fps},select='{select_expr(spans, window.start)}',"
                     f"setpts=N/FRAME_RATE/TB{tone}[v{i}]")
    if len(groups) == 1:
        src = "[v0]"
    else:
        graph.append("".join(f"[v{i}]" for i in range(len(groups)))
                     + f"concat=n={len(groups)}:v=1:a=0[vcat]")
        src = "[vcat]"
    c0, (bx, by, bw, bh) = crops[0], _rect(bodies[0])
    graph.append(
        f"{src}sendcmd=f={_quote(cmds)},"
        f"drawbox@crop=x={c0.x}:y={c0.y}:w={c0.w}:h={c0.h}:color=lime:t={THICKNESS},"
        f"drawbox@body=x={bx}:y={by}:w={bw}:h={bh}:color=red:t={THICKNESS},"
        f"scale={PREVIEW_W}:-2,format=yuv420p[v]"
    )
    graph_file = out.with_suffix(".graph.txt")
    graph_file.write_text(";\n".join(graph) + "\n", encoding="utf-8")
    tmp = Path(str(out) + ".tmp.mp4")
    cmd = [FFMPEG, "-y", "-hide_banner", "-nostats"]
    for window, _ in groups:
        cmd += ["-ss", f"{window.start:.3f}", "-to", f"{window.end:.3f}", "-i", str(master)]
    cmd += ["-/filter_complex", str(graph_file), "-map", "[v]", "-an",
            *encoder_args(preview=True), "-frames:v", str(len(crops)), str(tmp)]
    try:
        run(cmd)
        os.replace(tmp, out)
    finally:
        tmp.unlink(missing_ok=True)  # also on Ctrl-C
    return out
